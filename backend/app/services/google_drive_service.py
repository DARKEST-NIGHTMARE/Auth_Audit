import os
from typing import List, Optional
import httplib2
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from app.core.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

class GoogleDriveService:
    @property
    def client_config(self):
        """Build config dynamically to ensure we always use latest settings."""
        return {
            "web": {
                "client_id": settings.google_client_id,
                "project_id": "oauth-test-486206",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_drive_redirect_uri.strip()]
            }
        }

    def get_auth_url(self, redirect_uri: str = None):
        """Generates Google Auth URL manually to avoid PKCE 'code_verifier' issues."""
        try:
            from urllib.parse import urlencode
            
            final_redirect_uri = redirect_uri or settings.google_drive_redirect_uri
            
            params = {
                "client_id": settings.google_client_id,
                "redirect_uri": final_redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": "security_token_drive" 
            }
            
            auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
            print(f"DEBUG: Manually Generated Auth URL: {auth_url}")
            return auth_url
        except Exception as e:
            logger.error(f"Error generating Drive Auth URL: {e}")
            raise HTTPException(status_code=500, detail="Failed to initiate Google Drive linking")

    async def exchange_code(self, code: str, redirect_uri: str = None):
        """Exchanges authorization code for access and refresh tokens manually."""
        try:
            import httpx

            final_redirect_uri = redirect_uri or settings.google_drive_redirect_uri

            data = {
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": final_redirect_uri,
                "grant_type": "authorization_code",
            }
            async with httpx.AsyncClient() as client:
                response = await client.post("https://oauth2.googleapis.com/token", data=data)
                
            if response.status_code != 200:
                logger.error(f"Google Token Exchange Error: {response.text}")
                raise HTTPException(status_code=400, detail=f"Google rejected code: {response.text}")
                
            tokens = response.json()
            return {
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"), 
            }
        except Exception as e:
            logger.error(f"Error in manual Drive code exchange: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    def get_client(self, access_token: str, refresh_token: Optional[str] = None):
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=SCOPES
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        return build('drive', 'v3', credentials=creds, cache_discovery=False)

    def list_folders(self, access_token: str, refresh_token: Optional[str] = None, parent_id: str = "root"):
        try:
            service = self.get_client(access_token, refresh_token)
            results = service.files().list(
                q=f"'{parent_id}' in parents and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, parents)",
                orderBy="folder, name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            return results.get('files', [])
        except Exception as e:
            logger.error(f"Google Drive List Folders Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def list_all_files(self, access_token: str, refresh_token: Optional[str] = None):
        try:
            service = self.get_client(access_token, refresh_token)
            results = service.files().list(
                q="trashed=false",
                pageSize=200,
                fields="nextPageToken, files(id, name, mimeType)",
                orderBy="name",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            return results.get('files', [])
        except Exception as e:
            logger.error(f"Google Drive List All Files Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def analyze_folder(self, folder_id: str, access_token: str, refresh_token: Optional[str] = None):
        try:
            service = self.get_client(access_token, refresh_token)
            query = f"'{folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name, mimeType, size, modifiedTime)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            files = results.get('files', [])
            total_size_bytes = 0
            file_types = {}
            for f in files:
                size = int(f.get('size', 0))
                total_size_bytes += size
                mtype = f.get('mimeType', 'unknown')
                file_types[mtype] = file_types.get(mtype, 0) + 1
            
            folder_meta = service.files().get(
                fileId=folder_id,
                fields="id, name, createdTime, modifiedTime"
            ).execute()

            return {
                "folder": folder_meta,
                "stats": {
                    "total_files": len(files),
                    "total_size_bytes": total_size_bytes,
                    "file_types_breakdown": file_types
                },
                "files": files
            }
        except Exception as e:
            logger.error(f"Google Drive Analyze Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_folder(self, name: str, access_token: str, refresh_token: Optional[str] = None, parent_id: Optional[str] = None):
        """Creates a new folder in the user's Drive."""
        try:
            service = self.get_client(access_token, refresh_token)
            file_metadata: dict = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
                
            folder = service.files().create(body=file_metadata, fields='id, name').execute()
            logger.info(f"Created folder: {folder.get('name')} (ID: {folder.get('id')})")
            return folder
        except Exception as e:
            logger.error(f"Google Drive Create Folder Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_file(self, name: str, content: str, access_token: str, refresh_token: Optional[str] = None, parent_id: Optional[str] = None):
        """Creates a new text file in the user's Drive."""
        try:
            from googleapiclient.http import MediaInMemoryUpload
            service = self.get_client(access_token, refresh_token)
            
            file_metadata: dict = {
                'name': name,
                'mimeType': 'text/plain'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
                
            media = MediaInMemoryUpload(content.encode('utf-8'), mimetype='text/plain', resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id, name').execute()
            logger.info(f"Created file: {file.get('name')} (ID: {file.get('id')})")
            return file
        except Exception as e:
            logger.error(f"Google Drive Create File Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def trash_item(self, file_id: str, access_token: str, refresh_token: Optional[str] = None):
        """Moves a file or folder to the trash."""
        try:
            service = self.get_client(access_token, refresh_token)
            service.files().update(fileId=file_id, body={'trashed': True}).execute()
            logger.info(f"Trashed item: {file_id}")
            return {"status": "success", "message": "Item moved to trash"}
        except Exception as e:
            logger.error(f"Google Drive Trash Item Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def get_file_metadata(self, file_id: str, access_token: str, refresh_token: str = None):
        """Fetches metadata for a single file/folder."""
        try:
            service = self.get_client(access_token, refresh_token)
            return service.files().get(fileId=file_id, fields="id, name, mimeType, size, modifiedTime").execute()
        except Exception as e:
            logger.error(f"Google Drive Get Metadata Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def download_file_bytes(self, file_id: str, access_token: str, refresh_token: str = None) -> bytes:
        """Downloads a file and returns its raw bytes."""
        try:
            import io
            from googleapiclient.http import MediaIoBaseDownload
            
            service = self.get_client(access_token, refresh_token)
            
            # Special handling for Google Docs (must be exported)
            meta = self.get_file_metadata(file_id, access_token, refresh_token)
            mime = meta.get('mimeType', '')
            
            if 'google-apps' in mime:
                # Export Google Docs as PDF or TXT
                export_mime = 'application/pdf' if 'document' in mime else 'text/plain'
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
            else:
                request = service.files().get_media(fileId=file_id)
                
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            return fh.getvalue()
        except Exception as e:
            logger.error(f"Google Drive Download Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def upload_file(self, file_content: bytes, filename: str, mime_type: str, access_token: str, refresh_token: Optional[str] = None, parent_id: Optional[str] = None):
        """Uploads a file to the user's Drive."""
        try:
            from googleapiclient.http import MediaIoBaseUpload
            import io
            service = self.get_client(access_token, refresh_token)
            
            file_metadata: dict = {
                'name': filename
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]
                
            fh = io.BytesIO(file_content)
            media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id, name').execute()
            logger.info(f"Uploaded file: {file.get('name')} (ID: {file.get('id')})")
            return file
        except Exception as e:
            logger.error(f"Google Drive Upload File Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

drive_service = GoogleDriveService()
