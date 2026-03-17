import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    avatar_url = Column(String, nullable=True)
    provider = Column(String, default="local")
    password_hash = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER)
    
    # Optional Third-Party Integrations
    google_drive_access_token = Column(String, nullable=True)
    google_drive_refresh_token = Column(String, nullable=True)
    
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    refresh_token = Column(String, unique=True, index=True, nullable=False)
    device_info = Column(String, nullable=True) # e.g., "Windows PC - Chrome"
    ip_address = Column(String, nullable=True)
    location = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="sessions")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    role = Column(String)
    department = Column(String)
    salary = Column(Integer)
    is_active = Column(Boolean, default=True)

class EventType(str, enum.Enum):
    FAILED_LOGIN = "FAILED_LOGIN"
    REFRESH_USED = "REFRESH_USED"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    ACTIVE_SESSION = "ACTIVE_SESSION"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"

class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),nullable=True)

    event_type = Column(Enum(EventType), nullable=False)
    ip_address = Column(String, nullable=True)
    event_metadata = Column(JSON, default={})

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", backref="security_logs")