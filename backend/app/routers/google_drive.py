from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.models import User
from app.services.google_drive_service import drive_service

# Fixed imports: get_current_user is in dependencies
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/drive", tags=["Google Drive"])

async def get_db_user(payload: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    email = payload.get("sub")
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

class DriveCodeRequest(BaseModel):
    code: str

@router.post("/create-folder")
async def create_folder(name: str = "Auth Audit Workspace", db: AsyncSession = Depends(get_db), current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    
    folder = drive_service.create_folder(
        name=name,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return folder

@router.get("/auth-url")
async def get_drive_auth_url(current_user: User = Depends(get_db_user)):
    url = drive_service.get_auth_url()
    return {"url": url}

@router.post("/callback")
async def drive_callback(
    request: DriveCodeRequest, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_db_user)
):
    """Exchanges code for tokens and saves them to the current user."""
    tokens = await drive_service.exchange_code(request.code)
    
    current_user.google_drive_access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        current_user.google_drive_refresh_token = tokens["refresh_token"]
        
    db.add(current_user)
    await db.commit()
    
    return {"status": "success", "message": "Google Drive connected successfully."}

@router.get("/status")
async def drive_status(current_user: User = Depends(get_db_user)):
    is_connected = bool(current_user.google_drive_refresh_token or current_user.google_drive_access_token)
    return {"connected": is_connected}

@router.delete("/disconnect")
async def disconnect_drive(
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_db_user)
):
    current_user.google_drive_access_token = None
    current_user.google_drive_refresh_token = None
    db.add(current_user)
    await db.commit()
    return {"status": "success", "message": "Google Drive disconnected."}

@router.get("/folders")
async def get_folders(current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    folders = drive_service.list_folders(
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return folders

@router.get("/folders/{folder_id}/analyze")
async def analyze_folder(folder_id: str, current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    analysis_data = drive_service.analyze_folder(
        folder_id=folder_id,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return analysis_data
