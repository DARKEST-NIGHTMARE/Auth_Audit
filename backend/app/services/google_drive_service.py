import os
import httplib2
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

# Essential configurations for App Folder scope
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class GoogleDriveService:
    def __init__(self):
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID", "missing")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "missing")
        # Ensure your frontend runs on 3000 and the route is set up
        self.redirect_uri = os.environ.get("GOOGLE_DRIVE_REDIRECT_URI", "http://localhost:3000/drive/callback")
        
        self.client_config = {
            "web": {
                "client_id": self.client_id,
                "project_id": "oauth-dummy-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": self.client_secret,
                "redirect_uris": [self.redirect_uri]
            }
        }

    def get_auth_url(self):
        try:
            flow = Flow.from_client_config(
                self.client_config,
                scopes=SCOPES,
                redirect_uri=self.redirect_uri
            )
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent' # Force consent to always get a refresh token
            )
            return auth_url
        except Exception as e:
            logger.error(f"Error generating Drive Auth URL: {e}")
            raise HTTPException(status_code=500, detail="Failed to initiate Google Drive linking")

    def exchange_code(self, code: str):
        try:
            flow = Flow.from_client_config(
                self.client_config,
                scopes=SCOPES,
                redirect_uri=self.redirect_uri
            )
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            return {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
            }
        except Exception as e:
            logger.error(f"Error exchanging Drive code: {e}")
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    def get_client(self, access_token: str, refresh_token: str = None):
        """Reconstruct Google Credentials object from database tokens."""
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=SCOPES
        )
        # Auto-refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        return build('drive', 'v3', credentials=creds, cache_discovery=False)

    def list_folders(self, access_token: str, refresh_token: str = None):
        try:
            service = self.get_client(access_token, refresh_token)
            
            # drive.file scope limits this query ONLY to files/folders this app created or user explicitly opened via Picker!
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
            
            # Fetch all files inside the specified folder
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
            
            # Fetch Folder metadata
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

drive_service = GoogleDriveService()
