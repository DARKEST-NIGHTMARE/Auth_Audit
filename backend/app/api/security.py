from fastapi import APIRouter, Depends, HTTPException, status, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import joinedload
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer

from .. import models, schemas
from ..core import database, dependencies
from ..services.websocket import security_ws_manager
from ..logger import get_logger

logger = get_logger(__name__)

token_auth_scheme = HTTPBearer()

router = APIRouter(
    prefix="/api/admin/security",
    tags=['Security Dashboard']
)

async def require_admin(
    current_user: models.User = Depends(dependencies.get_current_db_user),
):
    """
    Enforces admin role check by relying on get_current_db_user dependency.
    """
    if current_user.role != models.UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges required."
        )
    return current_user

@router.get("/events", response_model=List[schemas.SecurityEventOut])
async def get_security_events(
    skip: int = 0, 
    limit: int = 20,
    event_type: Optional[models.EventType] = None,
    user_id: Optional[int] = None,
    db: AsyncSession = Depends(database.get_db),
    admin = Depends(require_admin) 
):
    # Use joinedload to fetch user details in the same query
    stmt = select(models.SecurityEvent).options(
        joinedload(models.SecurityEvent.user)
    )

    if event_type:
        stmt = stmt.where(models.SecurityEvent.event_type == event_type)
    if user_id:
        stmt = stmt.where(models.SecurityEvent.user_id == user_id)

    stmt = stmt.order_by(desc(models.SecurityEvent.created_at)).offset(skip).limit(limit)
    
    result = await db.execute(stmt)
    events = result.scalars().all()

    for event in events:
        event.username = event.user.name if event.user else "Unknown"

    return events

@router.get("/active-users")
async def get_active_users(
    days: int = Query(7, description="Number of days to look back"),
    db: AsyncSession = Depends(database.get_db),
    admin = Depends(require_admin)
):
    time_threshold = datetime.now(timezone.utc) - timedelta(days=days)

    # Perform a single database select joining SecurityEvent and User
    stmt = select(
        models.SecurityEvent,
        models.User
    ).join(
        models.User, models.SecurityEvent.user_id == models.User.id
    ).where(
        models.SecurityEvent.event_type == models.EventType.ACTIVE_SESSION,
        models.SecurityEvent.created_at >= time_threshold
    ).order_by(desc(models.SecurityEvent.created_at))

    result = await db.execute(stmt)
    rows = result.all()

    # Group the active users in Python
    user_data = {}
    for event, user in rows:
        uid = user.id
        if uid not in user_data:
            user_data[uid] = {
                "user_id": uid,
                "name": user.name,
                "email": user.email,
                "last_seen": event.created_at,
                "last_ip": event.ip_address,
                "total_logins": 0
            }
        user_data[uid]["total_logins"] += 1

    activity_list = list(user_data.values())
    activity_list.sort(key=lambda x: x["last_seen"], reverse=True)
    return activity_list

@router.get("/sessions", response_model=List[schemas.UserSessionOut])
async def get_all_sessions(
    db: AsyncSession = Depends(database.get_db),
    admin = Depends(require_admin)
):
    # Eager load user relationship in one SQL statement
    stmt = select(models.UserSession).options(
        joinedload(models.UserSession.user)
    ).where(
        models.UserSession.is_active == True
    ).order_by(desc(models.UserSession.last_active))

    result = await db.execute(stmt)
    sessions = result.scalars().all()
    
    for session in sessions:
        if session.user:
            session.user_name = session.user.name
            session.user_email = session.user.email

    return sessions

@router.delete("/sessions/{session_id}")
async def revoke_user_session(
    session_id: int,
    db: AsyncSession = Depends(database.get_db),
    admin = Depends(require_admin)
):
    stmt = select(models.UserSession).where(models.UserSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session.is_active = False
    await db.commit()
    return {"message": "Session revoked successfully"}

@router.websocket("/ws")
async def websocket_security_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(database.get_db)
):
    # Accept and authenticate the WebSocket connection using query parameter token
    if not token:
        await websocket.accept()
        await websocket.send_json({"error": "Unauthorized: Missing token"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        import jwt as _jwt
        payload = _jwt.decode(token, dependencies.JWT_SECRET, algorithms=[dependencies.ALGORITHM])
        email = payload.get("sub")
        
        # Verify admin privilege status of the user
        stmt = select(models.User).where(models.User.email == email)
        result = await db.execute(stmt)
        db_user = result.scalars().first()
        if not db_user or db_user.role != models.UserRole.ADMIN:
            await websocket.accept()
            await websocket.send_json({"error": "Forbidden: Admin access required"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except Exception as e:
        await websocket.accept()
        await websocket.send_json({"error": f"Unauthorized: {str(e)}"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await security_ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        security_ws_manager.disconnect(websocket)