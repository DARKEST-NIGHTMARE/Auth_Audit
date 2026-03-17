from fastapi import APIRouter, Depends, HTTPException, status, Form, UploadFile, File, Request, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import uuid
import os
import shutil
from datetime import datetime, timezone
from .. import models, schemas
from ..core import database, dependencies, config
settings = config.settings
from ..services.security_service import SecurityService 
from ..models import EventType
from ..logger import get_logger
from ..services.auth_service import AuthService
from ..services.location_service import LocationService
from ..core.dependencies import get_http_client

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# Location logic moved to LocationService

@router.post("/login")
async def login(request: Request,response: Response, payload: schemas.LoginRequest, db: AsyncSession = Depends(database.get_db)):
    client_ip = request.client.host
    location_str = "Unknown"
    location_source = "Unknown"
    lat = payload.latitude
    lon = payload.longitude

    # 1. Check if we have exact GPS from the browser
    if lat and lon:
        http_client = request.app.state.http_client
        location_str = await LocationService.get_coord_location(lat, lon, http_client)
        location_source = "GPS (Precise)"
        
    # 2. If no GPS, fallback to IP Geolocation
    if not location_str or location_str == "Unknown":
        http_client = request.app.state.http_client
        ip_data = await LocationService.get_ip_location_data(client_ip, http_client)
        location_str = ip_data["location"]
        lat = ip_data["lat"]
        lon = ip_data["lon"]
        location_source = "IP (Approximate)"

    if await SecurityService.is_ip_locked_out(db, client_ip):

        stmt = select(models.User).where(models.User.email == payload.username)
        result = await db.execute(stmt)
        target_user = result.scalars().first()


        await SecurityService.log_event(
            db, 
            EventType.ACCOUNT_LOCKED, 
            client_ip, 
            user_id=target_user.id if target_user else None, 
            event_metadata={
                "reason": "Too many failed attempts",
                "targeted_email": payload.username,
                "location": location_str, 
                "location_source": location_source,
                "lat": lat,
                "lon": lon
            }
        )
        raise HTTPException(status_code=429, detail="Too many failed login attempts. Please try again in 5 minutes.")

    stmt = select(models.User).where(models.User.email == payload.username)
    result = await db.execute(stmt)
    db_user = result.scalars().first()

    if not db_user or not db_user.password_hash or not dependencies.verify_password(payload.password, db_user.password_hash):
        await SecurityService.log_event(
            db, EventType.FAILED_LOGIN, client_ip, 
            user_id=db_user.id if db_user else None, 
            event_metadata={
                "attempted_email": payload.username,
                "location": location_str, 
                "location_source": location_source,
                "lat": lat,
                "lon": lon
            }
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    await SecurityService.check_suspicious_activity(db, db_user.id, client_ip)
    await SecurityService.log_event(
        db, 
        EventType.ACTIVE_SESSION, 
        client_ip, 
        user_id=db_user.id,
        event_metadata={
            "location": location_str, 
            "location_source": location_source,
            "lat": lat,
            "lon": lon
        } 
    )

    refresh_token = dependencies.create_refresh_token(db_user.email)
    
    device_info = request.headers.get("User-Agent", "Unknown Device")

    new_session = models.UserSession(
        user_id=db_user.id,
        refresh_token=refresh_token,
        device_info=device_info,
        ip_address=client_ip,
        location=location_str
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    access_token = dependencies.create_jwt_token(db_user.email, db_user.name, new_session.id)

    response.set_cookie(
        key = "refresh_token",
        value = refresh_token,
        httponly = True,
        max_age = 7*24*3600,
        samesite = "lax",
        secure = False
    )
    
    return {
        "token": access_token,
        "user": {
            "name": db_user.name,
            "email": db_user.email,
            "avatar_url": db_user.avatar_url,
            "role": db_user.role if hasattr(db_user, 'role') else "user"
        }
    }


@router.post("/google")
async def google_login(
    request: Request, 
    response: Response, 
    payload: schemas.GoogleLoginRequest, 
    db: AsyncSession = Depends(database.get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client)
):
    client_ip = request.client.host
    device_info = request.headers.get("User-Agent", "Unknown Device")
    
    # Get location data
    lat = payload.latitude
    lon = payload.longitude
    location_str = "Unknown"
    location_source = "Unknown"

    if lat and lon:
        location_str = await LocationService.get_coord_location(lat, lon, http_client)
        location_source = "GPS (Precise)"
        
    if not location_str or location_str == "Unknown":
        ip_data = await LocationService.get_ip_location_data(client_ip, http_client)
        location_str = ip_data["location"]
        lat = ip_data["lat"]
        lon = ip_data["lon"]
        location_source = "IP (Approximate)"
        
    auth_service = AuthService(db, http_client)
    access_token, refresh_token, user = await auth_service.authenticate_google(
        code=payload.code,
        client_ip=client_ip,
        location_str=location_str,
        location_source=location_source,
        lat=lat,
        lon=lon,
        device_info=device_info
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        max_age=7*24*3600,
        samesite="lax",
        secure=False
    )
    
    return {
        "token": access_token,
        "user": {
            "name": user.name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "role": user.role if hasattr(user, 'role') else "user"
        }
    }

@router.post("/refresh")
async def refresh_access_token(refresh_token: str = Cookie(None), db: AsyncSession = Depends(database.get_db)):
    """to be called when access token expires"""
    if not refresh_token:
        raise HTTPException(status_code=401, detail = "Refresh token missing")
    
    # Check if session is valid in DB
    session_stmt = select(models.UserSession).where(
        models.UserSession.refresh_token == refresh_token,
        models.UserSession.is_active == True
    )
    session_res = await db.execute(session_stmt)
    active_session = session_res.scalars().first()
    
    if not active_session:
        # Invalid or revoked session
        raise HTTPException(status_code=401, detail="Session expired or revoked")
    
    email = dependencies.verify_refresh_token(refresh_token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    stmt = select(models.User).where(models.User.email == email)
    result = await db.execute(stmt)
    db_user = result.scalars().first()
    
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")
        
    # Update last active time
    active_session.last_active = datetime.now(timezone.utc)
    await db.commit()
    
    new_access_token = dependencies.create_jwt_token(db_user.email, db_user.name, active_session.id)
    return {"token": new_access_token}

@router.post("/register")
async def register_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    profile_picture: UploadFile = File(None),
    db: AsyncSession = Depends(database.get_db)
):
    stmt = select(models.User).where(models.User.email == email)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    avatar_url = None
    if profile_picture:
        os.makedirs("static/profiles", exist_ok=True)
        
        file_extension = profile_picture.filename.split(".")[-1]
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        file_path = f"static/profiles/{unique_filename}"

        contents = await profile_picture.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        avatar_url = f"/static/profiles/{unique_filename}"

    hashed_password = dependencies.hash_password(password)
    
    new_user = models.User(
        email=email, 
        name=name, 
        avatar_url=avatar_url, 
        provider="local",
        password_hash=hashed_password
    )
    db.add(new_user)
    await db.commit()

    return {"message": "User registered successfully"}

@router.post("/logout")
async def logout(refresh_token: str = Cookie(None), response: Response = None, db: AsyncSession = Depends(database.get_db)):
    """clears http-only cookie and revokes session"""
    if refresh_token:
        session_stmt = select(models.UserSession).where(models.UserSession.refresh_token == refresh_token)
        session_res = await db.execute(session_stmt)
        active_session = session_res.scalars().first()
        
        if active_session:
            active_session.is_active = False
            await db.commit()
            
    response.delete_cookie("refresh_token")
    return {"message": "Logged out successfully"}