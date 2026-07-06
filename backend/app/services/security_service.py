from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta, timezone
from ..models import SecurityEvent, EventType
from .websocket import security_ws_manager
from ..logger import get_logger

logger = get_logger(__name__)

class SecurityService:
    @staticmethod
    async def log_event(db: AsyncSession, 
                        event_type: EventType, 
                        ip_address: str, 
                        user_id: int = None, 
                        event_metadata: dict = None):
        """Creates a new security log entry asynchronously."""
        if event_metadata is None:
            event_metadata = {}
            
        new_event = SecurityEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=ip_address,
            event_metadata=event_metadata
        )
        db.add(new_event)
        await db.commit()
        await db.refresh(new_event)

        username = None
        user_email = None
        if new_event.user_id:
            from ..models import User
            user_stmt = select(User).where(User.id == new_event.user_id)
            user_res = await db.execute(user_stmt)
            db_user = user_res.scalars().first()
            if db_user:
                username = db_user.name
                user_email = db_user.email

        try:
            event_type_str = new_event.event_type.value if hasattr(new_event.event_type, 'value') else str(new_event.event_type)

            event_payload = {
                "id": new_event.id,
                "event_type": event_type_str,
                "user_id": new_event.user_id,
                "username": username,
                "user_email": user_email,
                "ip_address": new_event.ip_address,
                "event_metadata": new_event.event_metadata,
                "created_at": new_event.created_at.isoformat()
            }
            await security_ws_manager.broadcast(event_payload)
        
        except Exception as e:
            logger.warning("ws_broadcast_failed", extra={"error": str(e)})
        return new_event

    @staticmethod
    async def is_ip_locked_out(db: AsyncSession, ip_address: str) -> bool:
        """Rule: >5 failed attempts in the last 5 minutes from the same IP."""
        five_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        
        stmt = select(func.count(SecurityEvent.id)).where(
            SecurityEvent.ip_address == ip_address,
            SecurityEvent.event_type == EventType.FAILED_LOGIN,
            SecurityEvent.created_at >= five_mins_ago
        )
        result = await db.execute(stmt)
        failed_count = result.scalar()
        
        return failed_count >= 5

    @staticmethod
    async def check_suspicious_activity(db: AsyncSession, 
                                        user_id: int, 
                                        current_ip: str):
        """Rule: Same user_id logs in from a new IP within 15 minutes of a previous login."""
        fifteen_mins_ago = datetime.now(timezone.utc) - timedelta(minutes=15)
        
        # Get the user's last successful login within 15 mins
        stmt = select(SecurityEvent).where(
            SecurityEvent.user_id == user_id,
            SecurityEvent.event_type == EventType.ACTIVE_SESSION,
            SecurityEvent.created_at >= fifteen_mins_ago
        ).order_by(SecurityEvent.created_at.desc())
        
        result = await db.execute(stmt)
        last_login = result.scalars().first()
        # If there is a recent login AND the IP is different, log it as suspicious
        if last_login and last_login.ip_address != current_ip:
            await SecurityService.log_event(
                db=db,
                event_type=EventType.SUSPICIOUS_ACTIVITY,
                ip_address=current_ip,
                user_id=user_id,
                event_metadata={
                    "reason": "IP change within 15 minutes",
                    "previous_ip": last_login.ip_address
                }
            )