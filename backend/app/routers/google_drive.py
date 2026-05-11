from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.models import User
from app.services.google_drive_service import drive_service

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
    redirect_uri: str | None = None

class DriveItemCreate(BaseModel):
    name: str
    content: str | None = None
    parent_id: str | None = None

    class Config:
        extra = "ignore"
@router.post("/create-folder")
async def create_folder(item: DriveItemCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    
    folder = drive_service.create_folder(
        name=item.name,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token,
        parent_id=item.parent_id
    )
    return folder

@router.post("/create-file")
async def create_file(item: DriveItemCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    
    file = drive_service.create_file(
        name=item.name,
        content=item.content or "Empty audit report",
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token,
        parent_id=item.parent_id
    )
    return file

@router.delete("/items/{item_id}")
async def delete_item(item_id: str, current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    result = drive_service.trash_item(
        file_id=item_id,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token
    )
    return result

@router.post("/upload-file")
async def upload_file(
    parent_id: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_db_user)
):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    
    content = await file.read()
    uploaded_file = drive_service.upload_file(
        file_content=content,
        filename=file.filename,
        mime_type=file.content_type,
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token,
        parent_id=parent_id
    )
    return uploaded_file

@router.get("/auth-url")
async def get_drive_auth_url(redirect_uri: str = Query(None), current_user: User = Depends(get_db_user)):
    url = drive_service.get_auth_url(redirect_uri=redirect_uri)
    return {"url": url}

@router.post("/callback")
async def drive_callback(
    request: DriveCodeRequest, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_db_user)
):
    """Exchanges code for tokens and saves them to the current user."""
    tokens = await drive_service.exchange_code(request.code, request.redirect_uri)

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
async def get_folders(parent_id: str = Query("root"), current_user: User = Depends(get_db_user)):
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
        
    folders = drive_service.list_folders(
        access_token=current_user.google_drive_access_token,
        refresh_token=current_user.google_drive_refresh_token,
        parent_id=parent_id
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
