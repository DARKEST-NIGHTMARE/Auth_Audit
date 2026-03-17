import os
import httplib2
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from app.core.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

# Essential configurations for App Folder scope
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

    def get_auth_url(self):
        """Generates Google Auth URL manually to avoid PKCE 'code_verifier' issues."""
        try:
            from urllib.parse import urlencode
            
            params = {
                "client_id": settings.google_client_id,
                "redirect_uri": settings.google_drive_redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": "security_token_drive" # Simple state for tracking
            }
            
            auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
            print(f"DEBUG: Manually Generated Auth URL: {auth_url}")
            return auth_url
        except Exception as e:
            logger.error(f"Error generating Drive Auth URL: {e}")
            raise HTTPException(status_code=500, detail="Failed to initiate Google Drive linking")

    async def exchange_code(self, code: str):
        """Exchanges authorization code for access and refresh tokens manually."""
        try:
            # Using httpx for manual exchange to avoid PKCE 'Missing code verifier' issues with Google Flow objects
            import httpx
            
            data = {
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_drive_redirect_uri,
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
                "refresh_token": tokens.get("refresh_token"), # Usually only present on first consent
            }
        except Exception as e:
            logger.error(f"Error in manual Drive code exchange: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    def get_client(self, access_token: str, refresh_token: str = None):
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

    def list_folders(self, access_token: str, refresh_token: str = None):
        try:
            service = self.get_client(access_token, refresh_token)
            results = service.files().list(
                q="mimeType='application/vnd.google-apps.folder' and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, createdTime, modifiedTime)",
                orderBy="name"
            ).execute()
            
            return results.get('files', [])
        except Exception as e:
            logger.error(f"Google Drive List Folders Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def analyze_folder(self, folder_id: str, access_token: str, refresh_token: str = None):
        try:
            service = self.get_client(access_token, refresh_token)
            query = f"'{folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name, mimeType, size, modifiedTime)",
                pageSize=1000
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

    def create_folder(self, name: str, access_token: str, refresh_token: str = None):
        """Creates a new folder in the user's Drive."""
        try:
            service = self.get_client(access_token, refresh_token)
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=file_metadata, fields='id, name').execute()
            logger.info(f"Created folder: {folder.get('name')} (ID: {folder.get('id')})")
            return folder
        except Exception as e:
            logger.error(f"Google Drive Create Folder Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

drive_service = GoogleDriveService()
