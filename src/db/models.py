import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Enums ────────────────────────────────────────────────────────────────────


class BizStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAUSED = "paused"
    BLOCKED = "blocked"


class DialogueStatus(str, enum.Enum):
    ACTIVE = "active"
    HANDED_OFF = "handed_off"  # передан менеджеру
    CLOSED = "closed"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    CONVERTED = "converted"


class Plan(str, enum.Enum):
    FREE = "free"
    START = "start"       # 2990 руб/мес
    BUSINESS = "business"  # 4990 руб/мес
    PRO = "pro"           # 7990 руб/мес


# ── Base ─────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Models ───────────────────────────────────────────────────────────────────


class Business(Base):
    """Бизнес-клиент Replly."""
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    owner_name: Mapped[str] = mapped_column(String(255))

    # Профиль бизнеса
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    working_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # База знаний (прайс, FAQ, услуги — всё в одном тексте)
    knowledge_base: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Настройки AI
    tone: Mapped[str] = mapped_column(String(50), default="friendly")  # friendly/formal/casual
    greeting: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Подписка
    plan: Mapped[Plan] = mapped_column(default=Plan.FREE)
    status: Mapped[BizStatus] = mapped_column(default=BizStatus.TRIAL)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=True
    )

    dialogues: Mapped[List["Dialogue"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    leads: Mapped[List["Lead"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Business id={self.id} name={self.name!r}>"


class Dialogue(Base):
    """Диалог между клиентом бизнеса и AI."""
    __tablename__ = "dialogues"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    client_tg_id: Mapped[int] = mapped_column(BigInteger)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[DialogueStatus] = mapped_column(default=DialogueStatus.ACTIVE)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=True
    )

    business: Mapped["Business"] = relationship(back_populates="dialogues")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="dialogue", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Dialogue id={self.id} biz={self.business_id} client={self.client_tg_id}>"


class Message(Base):
    """Сообщение в диалоге."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dialogue_id: Mapped[int] = mapped_column(ForeignKey("dialogues.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # "client", "assistant", "handoff"
    content: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    dialogue: Mapped["Dialogue"] = relationship(back_populates="messages")


class Lead(Base):
    """Лид — клиент оставивший контакты."""
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    client_tg_id: Mapped[int] = mapped_column(BigInteger)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    request: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[LeadStatus] = mapped_column(default=LeadStatus.NEW)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    business: Mapped["Business"] = relationship(back_populates="leads")

    def __repr__(self) -> str:
        return f"<Lead id={self.id} biz={self.business_id} name={self.client_name!r}>"


# ── Outreach (для привлечения клиентов Replly) ──────────────────────────


class OutreachStatus(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    FOLLOWUP_1 = "followup_1"
    FOLLOWUP_2 = "followup_2"
    REPLIED = "replied"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    CONVERTED = "converted"


class OutreachLead(Base):
    """Лид для outreach — потенциальный клиент Replly."""
    __tablename__ = "outreach_leads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    telegram: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vk: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[OutreachStatus] = mapped_column(default=OutreachStatus.NEW)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=True
    )

    outreach_logs: Mapped[List["OutreachLog"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class OutreachLog(Base):
    """Лог отправок outreach."""
    __tablename__ = "outreach_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("outreach_leads.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(50))
    phase: Mapped[int] = mapped_column()
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    delivered: Mapped[bool] = mapped_column(default=True)
    replied: Mapped[bool] = mapped_column(default=False)

    lead: Mapped["OutreachLead"] = relationship(back_populates="outreach_logs")
