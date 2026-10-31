from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AppointmentType(TimestampMixin, Base):
    __tablename__ = "appointment_types"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    default_duration_minutes: Mapped[int] = mapped_column(Integer)
    preparation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_ref: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_contact_method: Mapped[str] = mapped_column(String(20), default="VOICE")
    preferred_language: Mapped[str] = mapped_column(String(80), default="English")
    administrative_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    referrals: Mapped[list["Referral"]] = relationship(back_populates="patient", cascade="all, delete-orphan")


class Referral(TimestampMixin, Base):
    __tablename__ = "referrals"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    appointment_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointment_types.id", ondelete="RESTRICT"), nullable=True, index=True)
    pathway_type: Mapped[str] = mapped_column(String(40), index=True)
    procedure: Mapped[str] = mapped_column(String(160))
    referring_org: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_org: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    patient: Mapped[Patient] = relationship(back_populates="referrals")
    appointment_type: Mapped[AppointmentType | None] = relationship()
    goal: Mapped["Goal"] = relationship(back_populates="referral", cascade="all, delete-orphan", uselist=False)
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="referral", cascade="all, delete-orphan")


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    referral_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referrals.id", ondelete="CASCADE"), unique=True)
    goal_type: Mapped[str] = mapped_column(String(80), default="COMPLETE_PATHWAY")
    description: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE", index=True)
    current_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    referral: Mapped[Referral] = relationship(back_populates="goal")
    events: Mapped[list["Event"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    actions: Mapped[list["Action"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    communications: Mapped[list["Communication"]] = relationship(back_populates="goal", cascade="all, delete-orphan")
    documents: Mapped[list["CaseDocument"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class Slot(TimestampMixin, Base):
    __tablename__ = "slots"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_ref: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    appointment_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointment_types.id", ondelete="RESTRICT"), nullable=True, index=True)
    provider_org: Mapped[str] = mapped_column(String(160))
    site: Mapped[str] = mapped_column(String(160))
    procedure: Mapped[str] = mapped_column(String(160), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="AVAILABLE", index=True)
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment_type: Mapped[AppointmentType | None] = relationship()


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("slot_id", "status", name="uq_slot_active_status"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    referral_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referrals.id", ondelete="CASCADE"), index=True)
    slot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("slots.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="OFFERED", index=True)
    referral: Mapped[Referral] = relationship(back_populates="appointments")
    slot: Mapped[Slot] = relationship()


class Event(Base):
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    goal: Mapped[Goal | None] = relationship(back_populates="events")


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    goal: Mapped[Goal] = relationship(back_populates="actions")


class Communication(Base):
    __tablename__ = "communications"
    __table_args__ = (
        CheckConstraint("purpose IN ('REMINDER','RESCHEDULE','EARLIER_SLOT_OFFER','FOLLOW_UP')", name="ck_communications_purpose"),
        CheckConstraint("outcome IN ('QUEUED','ANSWERED','DECLINED','NO_ANSWER','FAILED','ESCALATED')", name="ck_communications_outcome"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    purpose: Mapped[str] = mapped_column(String(30), default="REMINDER", index=True)
    outcome: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    language: Mapped[str] = mapped_column(String(20), default="en")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    goal: Mapped[Goal] = relationship(back_populates="communications")


class GoalDecision(Base):
    __tablename__ = "goal_decisions"
    __table_args__ = (Index("ix_goal_decisions_goal_version", "goal_id", "goal_version", unique=True),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    goal_version: Mapped[int] = mapped_column(Integer)
    observation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reasoning_summary: Mapped[str] = mapped_column(Text)
    proposed_action: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    referral_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("referrals.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(40))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_note_versions.id", ondelete="RESTRICT", use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    current_version: Mapped["CaseNoteVersion | None"] = relationship(foreign_keys=[current_version_id], post_update=True)
    versions: Mapped[list["CaseNoteVersion"]] = relationship(back_populates="note", foreign_keys="CaseNoteVersion.note_id")


class CaseNoteVersion(Base):
    """Immutable revision belonging to one stable case-note identity."""

    __tablename__ = "case_note_versions"
    __table_args__ = (UniqueConstraint("note_id", "version", name="uq_case_note_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_notes.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(40))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_note_versions.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    note: Mapped[CaseNote] = relationship(back_populates="versions", foreign_keys=[note_id])
    supersedes: Mapped["CaseNoteVersion | None"] = relationship(remote_side=[id])


class AgentDefinition(Base):
    """Stable identity for an agent; its selected version may change."""

    __tablename__ = "agent_definitions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_spec_versions.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active_version: Mapped["AgentSpecVersion | None"] = relationship(
        foreign_keys=[active_version_id], post_update=True
    )
    versions: Mapped[list["AgentSpecVersion"]] = relationship(
        back_populates="definition", foreign_keys="AgentSpecVersion.definition_id"
    )


class AgentSpecVersion(Base):
    """Immutable executable configuration for a long-horizon agent."""

    __tablename__ = "agent_spec_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version", name="uq_agent_spec_definition_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_definitions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80), index=True)
    instructions: Mapped[str] = mapped_column(Text)
    tool_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="PUBLISHED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    definition: Mapped[AgentDefinition] = relationship(back_populates="versions", foreign_keys=[definition_id])


class CaseDocument(Base):
    """Stable identity for a durable case document."""

    __tablename__ = "case_documents"
    __table_args__ = (UniqueConstraint("goal_id", "document_type", "title", name="uq_case_document_identity"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(200))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("case_document_versions.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    goal: Mapped[Goal] = relationship(back_populates="documents")
    current_version: Mapped["CaseDocumentVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )
    versions: Mapped[list["CaseDocumentVersion"]] = relationship(
        back_populates="document", foreign_keys="CaseDocumentVersion.document_id"
    )


class CaseDocumentVersion(Base):
    """Immutable content revision with explicit provenance."""

    __tablename__ = "case_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_case_document_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_documents.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("case_document_versions.id", ondelete="RESTRICT"), nullable=True)
    document_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document: Mapped[CaseDocument] = relationship(back_populates="versions", foreign_keys=[document_id])
    supersedes: Mapped["CaseDocumentVersion | None"] = relationship(remote_side=[id])


class AgentStep(Base):
    __tablename__ = "agent_steps"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    agent_spec_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_spec_versions.id", ondelete="RESTRICT"), nullable=True, index=True)
    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    retry_attempt: Mapped[int] = mapped_column(Integer, default=0)
    wake_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    scheduled_next_wake: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(24))
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_step: Mapped["AgentStep | None"] = relationship(remote_side=[id])


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_steps.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(80))
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
