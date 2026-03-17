from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import User
from app.services.google_drive_service import drive_service

# We are reusing the existing security dependency to get the current user
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/drive", tags=["Google Drive"])

class DriveCodeRequest(BaseModel):
    code: str

@router.get("/auth-url")
async def get_drive_auth_url(current_user: User = Depends(get_current_user)):
    url = drive_service.get_auth_url()
    return {"url": url}

@router.post("/callback")
async def drive_callback(
    request: DriveCodeRequest, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Exchanges code for tokens and saves them to the current user."""
    tokens = drive_service.exchange_code(request.code)
    
    current_user.google_drive_access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        current_user.google_drive_refresh_token = tokens["refresh_token"]
        
    db.add(current_user)
    await db.commit()
    
    return {"status": "success", "message": "Google Drive connected successfully."}

@router.get("/status")
async def drive_status(current_user: User = Depends(get_current_user)):
    is_connected = bool(current_user.google_drive_refresh_token or current_user.google_drive_access_token)
    return {"connected": is_connected}

@router.delete("/disconnect")
async def disconnect_drive(
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    current_user.google_drive_access_token = None
    current_user.google_drive_refresh_token = None
    db.add(current_user)
    await db.commit()
    return {"status": "success", "message": "Google Drive disconnected."}

@router.get("/folders")
async def get_folders(current_user: User = Depends(get_current_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    folders = drive_service.list_folders(
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return folders

@router.get("/folders/{folder_id}/analyze")
async def analyze_folder(folder_id: str, current_user: User = Depends(get_current_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    analysis_data = drive_service.analyze_folder(
        folder_id=folder_id,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return analysis_data
