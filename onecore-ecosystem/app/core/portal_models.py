from datetime import datetime,timezone
from sqlalchemy import String,Boolean,DateTime,ForeignKey,Text,Index
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base

def now():return datetime.now(timezone.utc)

class EmailVerification(Base):
    __tablename__="email_verifications"
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id",ondelete="CASCADE"),index=True)
    token_hash:Mapped[str]=mapped_column(String(64),unique=True,index=True)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    used_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class SupportTicket(Base):
    __tablename__="support_tickets"
    id:Mapped[int]=mapped_column(primary_key=True)
    reference:Mapped[str]=mapped_column(String(32),unique=True,index=True)
    organization_id:Mapped[int|None]=mapped_column(ForeignKey("organizations.id"),nullable=True,index=True)
    requester_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True,index=True)
    requester_name:Mapped[str]=mapped_column(String(180),nullable=False)
    requester_email:Mapped[str]=mapped_column(String(320),nullable=False,index=True)
    subject:Mapped[str]=mapped_column(String(180),nullable=False)
    category:Mapped[str]=mapped_column(String(30),nullable=False,default="general")
    priority:Mapped[str]=mapped_column(String(20),nullable=False,default="normal")
    status:Mapped[str]=mapped_column(String(30),nullable=False,default="open")
    public_access_hash:Mapped[str|None]=mapped_column(String(64),nullable=True,unique=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    __table_args__=(Index("ix_support_ticket_org_status","organization_id","status"),)

class SupportMessage(Base):
    __tablename__="support_messages"
    id:Mapped[int]=mapped_column(primary_key=True)
    ticket_id:Mapped[int]=mapped_column(ForeignKey("support_tickets.id",ondelete="CASCADE"),index=True)
    author_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    author_type:Mapped[str]=mapped_column(String(20),nullable=False)
    body:Mapped[str]=mapped_column(Text,nullable=False)
    is_internal:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
