from pydantic import BaseModel ,EmailStr
from typing import Optional, Dict, Any
from datetime import datetime
from .models import EventType, UserRole

class GoogleLoginRequest(BaseModel):
    code: Optional[str] = None
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class ClioLoginRequest(BaseModel):
    code: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class LoginRequest(BaseModel):
    username: str
    password: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class EmployeeCreate(BaseModel):
    name: str
    role: str
    department: str
    salary: int

class RoleChangeRequest(BaseModel):
    role: UserRole

class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: UserRole
    avatar_url: Optional[str] = None  


class SecurityEventOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    event_type: EventType
    ip_address: Optional[str] = None
    event_metadata: Dict[str, Any] = {}
    created_at: datetime

    username: Optional[str] = None 

class UserActivityOut(BaseModel):
    user_id: int
    name: str
    email: str
    last_seen: datetime
    last_ip: Optional[str] = None
    total_logins: int

    class Config:
        from_attributes = True

class BookSlotRequest(BaseModel):
    date: str       # YYYY-MM-DD
    start_time: str # HH:MM (24h)
    end_time: str   # HH:MM (24h)
    summary: str
    timezone_offset: str = "+00:00"

class UserSessionOut(BaseModel):
    id: int
    user_id: int
    refresh_token: str
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    location: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_active: datetime
    user_name: Optional[str] = None
    user_email: Optional[str] = None

    class Config:
        from_attributes = True

class Verify2FARequest(BaseModel):
    user_id: int
    code: str

class ResendOTPRequest(BaseModel):
    user_id: int

class TOTPSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str

class TOTPVerifySetupRequest(BaseModel):
    secret: str
    code: str

class TOTPLoginRequest(BaseModel):
    user_id: int
    code: str

class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None

class TOTPDisableRequest(BaseModel):
    code: str