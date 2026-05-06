import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .core.database import Base

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
    
    # 2FA Settings
    totp_secret = Column(String, nullable=True)
    is_totp_enabled = Column(Boolean, default=False)

    # Optional Third-Party Integrations
    google_drive_access_token = Column(String, nullable=True)
    google_drive_refresh_token = Column(String, nullable=True)
    
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    clio_connection = relationship("ClioConnection", back_populates="user", uselist=False, cascade="all, delete-orphan")

class ClioConnection(Base):
    __tablename__ = "clio_connections"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    access_token = Column(String, nullable=True)
    refresh_token = Column(String, nullable=True)
    base_url = Column(String, nullable=True)

    user = relationship("User", back_populates="clio_connection")

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

class OTPCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    user = relationship("User", backref="otp_codes")

class QueryJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class QueryJob(Base):
    __tablename__ = "query_jobs"
    id = Column(String, primary_key=True, index=True) # UUID string
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    query = Column(String, nullable=False)
    source = Column(String, nullable=True) # "google_drive" or "local"
    status = Column(Enum(QueryJobStatus), default=QueryJobStatus.PENDING)
    
    result = Column(JSON, nullable=True) # The final AI response structure
    error = Column(String, nullable=True)
    
    # Context for the worker (serialized)
    context_data = Column(JSON, nullable=True) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True) # For 24h cleanup

    user = relationship("User", backref="query_jobs")