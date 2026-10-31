from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from copy import deepcopy
from functools import wraps
import re
from threading import Lock
from time import monotonic
from typing import Literal, Protocol
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.database import read_session_scope, session_scope
from app.demo_cleanup import audit_demo_state, cleanup_demo_state
from app.agents import due_goals, run_goal
from app.capacity import ensure_weekday_capacity, match_available_slots
from app.elevenlabs_metadata import fetch_elevenlabs_metadata, unavailable_metadata
from app.models import Action, AgentDefinition, AgentSpecVersion, AgentStep, AgentToolCall, Appointment, AppointmentType, CaseDocument, CaseDocumentVersion, CaseNote, CaseNoteVersion, Communication, Event, Goal, GoalDecision, Patient, Referral, Slot
from app.records import CALL_OUTCOMES, CALL_PURPOSES, REMINDER_LEAD_HOURS, create_note, elevenlabs_call_payload, language_code, reminder_wake_at, revise_note
from app.settings import settings


class CallRequest(BaseModel):
    goal_id: UUID
    patient_first_name: str
    phone_number: str
    reason: str
    purpose: Literal["REMINDER", "RESCHEDULE", "EARLIER_SLOT_OFFER", "FOLLOW_UP"] = "REMINDER"
    preferred_language: str | None = None
    proposed_slot_id: UUID | None = None
    simulated_outcome: Literal["ANSWERED", "DECLINED", "NO_ANSWER", "FAILED", "ESCALATED"] = "ANSWERED"


class GoalRequest(BaseModel):
    goal_id: UUID


class BrowserConversationRequest(GoalRequest):
    proposed_slot_id: UUID | None = None
    action_id: UUID
    receiver_token: str = Field(min_length=16, max_length=100)


class DemoPhoneDeclineRequest(BaseModel):
    claim_code: str = Field(min_length=3, max_length=64)
    action_id: UUID | None = None


class DemoPhoneAnswerRequest(DemoPhoneDeclineRequest):
    pass


class DemoPhoneQueueRequest(GoalRequest):
    purpose: Literal["REMINDER", "RESCHEDULE", "EARLIER_SLOT_OFFER", "FOLLOW_UP"] = "REMINDER"
    reason: str | None = None


class DemoPhoneCancelRequest(GoalRequest):
    action_id: UUID


class DemoPhoneEndRequest(BrowserConversationRequest):
    outcome: Literal["COMPLETED", "FAILED", "TIMED_OUT"] = "COMPLETED"


class SlotRequest(GoalRequest):
    slot_id: UUID
    reason: str | None = None


class ConstraintRequest(GoalRequest):
    constraint: str


class IdentityVerificationRequest(GoalRequest):
    date_of_birth: date


class ReferralCreate(BaseModel):
    external_ref: str
    first_name: str
    last_name: str
    date_of_birth: date
    phone: str
    email: str | None = None
    preferred_contact_method: str = "VOICE"
    preferred_language: str = "English"
    pathway_type: str
    procedure: str | None = None
    appointment_type_id: UUID | None = None
    appointment_type_code: str | None = None
    referring_org: str | None = None
    provider_org: str

    @field_validator("date_of_birth")
    @classmethod
    def date_of_birth_must_be_in_the_past(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("Date of birth must be in the past")
        return value

    @field_validator("phone")
    @classmethod
    def phone_must_be_e164(cls, value: str) -> str:
        normalized = re.sub(r"[\s()-]", "", value.strip())
        if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
            raise ValueError("Phone number must use international format, for example +447700900123")
        return normalized


class PatientUpdate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    phone: str
    email: str | None = None
    preferred_language: str = Field(min_length=1, max_length=80)
    preferred_contact_method: str = Field(min_length=1, max_length=30)

    @field_validator("date_of_birth")
    @classmethod
    def update_dob_must_be_in_past(cls, value: date) -> date:
        if value >= date.today(): raise ValueError("Date of birth must be in the past")
        return value

    @field_validator("phone")
    @classmethod
    def update_phone_must_be_e164(cls, value: str) -> str:
        normalized = re.sub(r"[\s()-]", "", value.strip())
        if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
            raise ValueError("Phone number must use international format, for example +447700900123")
        return normalized


class SlotCreate(BaseModel):
    external_ref: str | None = None
    provider_org: str
    site: str
    procedure: str | None = None
    appointment_type_id: UUID | None = None
    appointment_type_code: str | None = None
    starts_at: datetime
    duration_minutes: int | None = None


class RunAgentsRequest(BaseModel):
    limit: int = 10


class DemoResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    scope: Literal["DEMO-*"]
    confirmation: Literal["RESET DEMO-* RECORDS"]


class CaseNoteCreate(BaseModel):
    category: str = "GENERAL"
    text: str


class CaseNoteUpdate(CaseNoteCreate):
    source: str = "OPERATOR"


class AgentVersionCreate(BaseModel):
    name: str
    role: str
    instructions: str
    tool_policy: dict
    model: str
    status: str = "PUBLISHED"
    activate: bool = False


class AgentRunRequest(BaseModel):
    goal_id: UUID | None = None


class CaseDocumentVersionCreate(BaseModel):
    document_type: str
    title: str
    content: str
    metadata: dict = Field(default_factory=dict)
    created_by: str = "OPERATOR"


class RescheduleRequest(SlotRequest):
    pass


class VoiceProvider(Protocol):
    async def call_patient(self, request: CallRequest) -> dict: ...


class FakeVoiceProvider:
    async def call_patient(self, request: CallRequest) -> dict:
        return {"provider": "simulated", "transport": "none", "simulated": True, "status": "completed", "outcome": request.simulated_outcome, "conversation_id": f"simulated-api-{uuid4()}"}


class ElevenLabsVoiceProvider:
    async def call_patient(self, request: CallRequest) -> dict:
        if not all((settings.elevenlabs_api_key, settings.elevenlabs_agent_id, settings.elevenlabs_phone_number_id)):
            raise HTTPException(503, "ElevenLabs is not configured")
        payload = elevenlabs_call_payload(agent_id=settings.elevenlabs_agent_id, phone_number_id=settings.elevenlabs_phone_number_id, to_number=request.phone_number, patient_first_name=request.patient_first_name, goal_id=request.goal_id, reason=request.reason, purpose=request.purpose, preferred_language=request.preferred_language, proposed_slot_id=request.proposed_slot_id)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://api.elevenlabs.io/v1/convai/twilio/outbound-call", headers={"xi-api-key": settings.elevenlabs_api_key}, json=payload)
            response.raise_for_status()
            return response.json()


app = FastAPI(title="nous API", version="0.2.0")
_demo_reset_lock = Lock()
_demo_reset_last_at = 0.0
_demo_reset_results: dict[str, dict] = {}
DEMO_RESET_COOLDOWN_SECONDS = 5.0
READ_CACHE_SECONDS = 2.0
_read_cache_lock = Lock()
_read_cache: dict[str, tuple[float, object]] = {}
_read_cache_key_locks: dict[str, Lock] = {}


def _cached_read(key: str, loader, ttl: float = READ_CACHE_SECONDS):
    """Collapse dashboard refresh bursts without allowing stale demo state to linger."""
    now = monotonic()
    cached = _read_cache.get(key)
    if cached and now - cached[0] < ttl:
        return deepcopy(cached[1])
    with _read_cache_lock:
        key_lock = _read_cache_key_locks.setdefault(key, Lock())
    # Collapse duplicate requests for one resource without serialising the
    # independent patients/slots/dashboard queries issued at page startup.
    with key_lock:
        cached = _read_cache.get(key)
        if cached and monotonic() - cached[0] < ttl:
            return deepcopy(cached[1])
        value = loader()
        _read_cache[key] = (monotonic(), value)
        return deepcopy(value)


def _cache_read_endpoint(key: str):
    def decorate(endpoint):
        @wraps(endpoint)
        def cached_endpoint(*args, **kwargs):
            return _cached_read(key, lambda: endpoint(*args, **kwargs))
        return cached_endpoint
    return decorate


@app.middleware("http")
async def request_timing(request: Request, call_next):
    """Expose application time separately from Modal routing and browser transfer."""
    started = monotonic()
    response = await call_next(request)
    duration_ms = (monotonic() - started) * 1000
    response.headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
        with _read_cache_lock:
            _read_cache.clear()
    return response


def require_database() -> None:
    if not settings.database_url:
        raise HTTPException(503, "Database is not configured")


def case_json(goal: Goal) -> dict:
    referral, patient = goal.referral, goal.referral.patient
    appointment = next((a for a in referral.appointments if a.status in {"OFFERED", "HELD", "BOOKED"}), None)
    slot = appointment.slot if appointment else None
    offered = next((appointment for appointment in referral.appointments if appointment.status == "OFFERED"), None)
    live_action = next((action for action in sorted(getattr(goal, "actions", []), key=lambda row: row.created_at or datetime.min.replace(tzinfo=UTC), reverse=True) if action.action_type in {"CALL_PATIENT", "EARLIER_SLOT_OFFER"} and action.status in LIVE_BROWSER_CALL_STATUSES), None)
    dob = getattr(patient, "date_of_birth", None)
    return {"id": str(goal.id), "patient_id": str(patient.id), "referral_id": str(referral.id), "external_ref": patient.external_ref, "first_name": patient.first_name, "last_name": patient.last_name, "name": f"{patient.first_name} {patient.last_name}", "initials": f"{patient.first_name[:1]}{patient.last_name[:1]}".upper(), "pathway": referral.pathway_type, "procedure": referral.procedure, "appointment": slot.starts_at.isoformat() if slot else None, "site": slot.site if slot else None, "status": goal.status, "blocker": goal.current_blocker, "offer_status": offered.status if offered else None, "next_wake_at": goal.next_wake_at.isoformat() if goal.next_wake_at else None, "phone": patient.phone, "email": patient.email, "date_of_birth": dob.date().isoformat() if dob else None, "language": patient.preferred_language, "preference": patient.preferred_contact_method, "note": patient.administrative_notes, "constraints": patient.constraints, "active_call_action_id": str(live_action.id) if live_action else None, "active_call_status": live_action.status if live_action else None}


def case_note_json(note: CaseNote, versions: list[CaseNoteVersion] | None = None) -> dict:
    versions = versions or []
    current_version_id = getattr(note, "current_version_id", None)
    return {"id": str(note.id), "category": note.category, "text": note.text, "language": note.language, "source": note.source, "current_version_id": str(current_version_id) if current_version_id else None, "current_version": next((v.version for v in versions if v.id == current_version_id), 1), "provenance": note.source, "created_at": note.created_at.isoformat(), "versions": [{"id": str(v.id), "version": v.version, "category": v.category, "text": v.text, "language": v.language, "source": v.source, "provenance": v.source, "supersedes_id": str(v.supersedes_id) if v.supersedes_id else None, "created_at": v.created_at.isoformat(), "current": v.id == current_version_id} for v in versions]}


def goal_query():
    return select(Goal).options(joinedload(Goal.referral).joinedload(Referral.patient), joinedload(Goal.referral).joinedload(Referral.appointments).joinedload(Appointment.slot), joinedload(Goal.actions))


def load_goal(session, goal_id: UUID) -> Goal:
    goal = session.scalar(goal_query().where(Goal.id == goal_id))
    if not goal:
        raise HTTPException(404, "Case not found")
    return goal


def resolve_appointment_type(session, appointment_type_id: UUID | None, appointment_type_code: str | None) -> AppointmentType | None:
    if not appointment_type_id and not appointment_type_code:
        return None
    conditions = []
    if appointment_type_id:
        conditions.append(AppointmentType.id == appointment_type_id)
    if appointment_type_code:
        conditions.append(AppointmentType.code == appointment_type_code.strip().upper())
    appointment_type = session.scalar(select(AppointmentType).where(*conditions))
    if not appointment_type:
        raise HTTPException(422, "Appointment type not found or identifiers do not match")
    if not appointment_type.is_active:
        raise HTTPException(409, "Appointment type is inactive")
    return appointment_type


@app.get("/health")
async def health() -> dict:
    connected = False
    if settings.database_url:
        try:
            with session_scope() as session:
                session.execute(select(1))
            connected = True
        except Exception:
            pass
    return {"ok": True, "database": connected, "voice_provider": "fake" if settings.use_fake_voice else "elevenlabs", "agent_provider": "anthropic" if settings.anthropic_api_key and not settings.anthropic_api_key.startswith("PLACEHOLDER") else "not_configured"}


@app.get("/api/integrations/elevenlabs")
async def elevenlabs_integration_metadata(refresh: bool = False) -> dict:
    if not settings.elevenlabs_api_key or settings.elevenlabs_api_key.startswith("PLACEHOLDER"):
        return {
            **unavailable_metadata("API key is not configured"),
            "browser_available": False,
            "browser_authentication": "not_configured",
            "telephone_transport": "simulated" if settings.use_fake_voice else "not_configured",
            "simulated_outcomes": settings.use_fake_voice,
        }
    if not settings.elevenlabs_agent_id or settings.elevenlabs_agent_id.startswith("PLACEHOLDER"):
        return {
            **unavailable_metadata("Agent ID is not configured"),
            "browser_available": False,
            "browser_authentication": "not_configured",
            "telephone_transport": "simulated" if settings.use_fake_voice else "not_configured",
            "simulated_outcomes": settings.use_fake_voice,
        }

    # Browser conversations and telephone dispatch are independent transports.  The
    # hackathon deployment deliberately simulates queued telephone outcomes, but it
    # still has a real ElevenLabs browser agent.  Always fetch that agent's metadata
    # so the operator UI can report its version, tools and webhook health.
    metadata = await fetch_elevenlabs_metadata(
        settings.elevenlabs_api_key,
        settings.elevenlabs_agent_id,
        settings.elevenlabs_phone_number_id,
        refresh=refresh,
    )
    return {
        **metadata,
        "provider": "elevenlabs_browser",
        "browser_available": metadata.get("available", False),
        "browser_authentication": "signed_url",
        "browser_session_endpoint": "/api/voice/browser-session",
        "telephone_transport": "simulated" if settings.use_fake_voice else "elevenlabs_phone",
        "simulated_outcomes": settings.use_fake_voice,
        "message": (
            "Browser conversations use short-lived signed sessions. Telephone outcomes are simulated; no phone call will be placed."
            if settings.use_fake_voice
            else "Browser and telephone conversations use the configured ElevenLabs agent."
        ),
    }


@app.post("/api/voice/browser-session")
async def browser_voice_session(request: BrowserConversationRequest) -> dict:
    """Mint a short-lived browser-agent URL without exposing the ElevenLabs API key."""
    require_database()
    if not settings.elevenlabs_api_key or not settings.elevenlabs_agent_id or settings.elevenlabs_api_key.startswith("PLACEHOLDER") or settings.elevenlabs_agent_id.startswith("PLACEHOLDER"):
        raise HTTPException(503, "ElevenLabs browser agent is not configured")
    with session_scope() as session:
        goal = load_goal(session, request.goal_id)
        receiver_action = session.get(Action, request.action_id)
        if (
            not receiver_action
            or receiver_action.goal_id != goal.id
            or receiver_action.status != "RINGING_BROWSER"
            or (receiver_action.payload or {}).get("receiver_token") != request.receiver_token
        ):
            raise HTTPException(403, "This browser phone is not authorised to answer the call")
        patient = goal.referral.patient
        offered_appointments = sorted(
            (appointment for appointment in goal.referral.appointments if appointment.status in {"OFFERED", "HELD"}),
            key=lambda appointment: appointment.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        proposed_slot_id = request.proposed_slot_id or (offered_appointments[0].slot_id if offered_appointments else None)
        preferred_language = language_code(patient.preferred_language)
        dynamic_variables = {
            "goal_id": str(goal.id),
            "patient_first_name": patient.first_name,
            "preferred_language": preferred_language,
            "proposed_slot_id": str(proposed_slot_id or ""),
            "purpose": (receiver_action.payload or {}).get("purpose") or "FOLLOW_UP",
            "reason": (receiver_action.payload or {}).get("reason") or "Progress appointment scheduling",
        }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": settings.elevenlabs_agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
    if response.status_code >= 400:
        raise HTTPException(502, "ElevenLabs could not create a browser session")
    signed_url = response.json().get("signed_url")
    if not signed_url:
        raise HTTPException(502, "ElevenLabs returned no signed browser URL")
    with session_scope() as session:
        answered_action = session.get(Action, request.action_id)
        if answered_action and answered_action.status == "RINGING_BROWSER":
            answered_action.status = "IN_PROGRESS"
    return {"signed_url": signed_url, "dynamic_variables": dynamic_variables, "language_code": preferred_language, "agent_id": settings.elevenlabs_agent_id, "transport": "browser_websocket", "expires_in_seconds": 900}


def _demo_phone_goal(session, claim_code: str) -> Goal:
    """Resolve an intentionally short-lived hackathon receiver code.

    The external reference is used as a possession-style demo code. Responses from
    these endpoints are deliberately minimal and never include DOB, contact details,
    notes, or constraints.
    """
    code = claim_code.strip()
    goal = session.scalar(
        goal_query()
        .join(Goal.referral)
        .join(Referral.patient)
        .where(func.lower(Patient.external_ref) == code.lower())
    )
    if not goal:
        raise HTTPException(404, "This demo phone code was not recognised")
    _heal_recoverable_blocker(goal)
    return goal


RECOVERABLE_BLOCKER_TERMS = ("phone number", "elevenlabs", "could not queue", "telephone", "offer is already open")
LIVE_BROWSER_CALL_STATUSES = {"QUEUED", "PROPOSED", "RINGING_BROWSER", "IN_PROGRESS"}
RECEIVABLE_BROWSER_CALL_STATUSES = {"QUEUED", "PROPOSED", "RINGING_BROWSER"}
TERMINAL_BROWSER_CALL_STATUSES = {"COMPLETED", "DECLINED", "CANCELLED", "FAILED", "TIMED_OUT", "EXPIRED"}
DEMO_BROWSER_CALL_TTL = timedelta(minutes=15)


def _terminalize_browser_action(action: Action, outcome: str, *, transport: str = "demo_browser_receiver") -> bool:
    """End a browser-call action once; retries preserve its original outcome/time."""
    if action.status in TERMINAL_BROWSER_CALL_STATUSES:
        return False
    action.status = outcome
    action.completed_at = datetime.now(UTC)
    action.result = {**(action.result or {}), "outcome": outcome, "transport": transport}
    return True


def _release_unaccepted_offers_on_call_end(session, goal: Goal, action: Action, outcome: str) -> list[str]:
    """Atomically withdraw every still-open offer unless it was explicitly booked."""
    offers = session.scalars(
        select(Appointment)
        .where(Appointment.referral_id == goal.referral_id, Appointment.status == "OFFERED")
        .with_for_update()
    ).all()
    released_slot_ids: list[str] = []
    for offer in offers:
        offer.status = "EXPIRED"
        slot = session.get(Slot, offer.slot_id)
        if slot and slot.status == "HELD":
            slot.status = "AVAILABLE"
            slot.held_until = None
            slot.properties = {**(slot.properties or {}), "released_gap": True, "release_reason": "call_ended_without_acceptance"}
            released_slot_ids.append(str(slot.id))
    goal.current_blocker = None
    if goal.status == "HUMAN_REVIEW_REQUIRED" or offers:
        goal.status = "WAITING"
    goal.next_wake_at = datetime.now(UTC)
    session.add(Event(
        goal_id=goal.id,
        event_type="OFFER_RELEASED_ON_CALL_END",
        source="demo_browser_receiver",
        payload={"action_id": str(action.id), "outcome": outcome, "released_slot_ids": released_slot_ids, "offer_count": len(offers)},
        idempotency_key=f"offer-release-on-call-end:{action.id}",
    ))
    return released_slot_ids


def _expire_browser_action(action: Action, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    if action.status in LIVE_BROWSER_CALL_STATUSES and action.created_at and action.created_at < now - DEMO_BROWSER_CALL_TTL:
        return _terminalize_browser_action(action, "TIMED_OUT")
    return False


def _has_recoverable_blocker(goal: Goal) -> bool:
    blocker = (getattr(goal, "current_blocker", None) or "").lower()
    return any(term in blocker for term in RECOVERABLE_BLOCKER_TERMS)


def _heal_recoverable_blocker(goal: Goal) -> bool:
    """Clear legacy exceptions now handled safely by browser calls/offer reuse."""
    if _has_recoverable_blocker(goal):
        goal.status = "WAITING"
        goal.current_blocker = None
        goal.next_wake_at = datetime.now(UTC)
        return True
    return False


@app.get("/api/demo-phone/incoming")
async def demo_phone_incoming(claim_code: str = Query(min_length=3, max_length=64)) -> dict:
    """Return the latest queued voice action for one claimed demo patient."""
    require_database()
    with session_scope() as session:
        goal = _demo_phone_goal(session, claim_code)
        action = session.scalar(
            select(Action)
            .where(
                Action.goal_id == goal.id,
                Action.action_type.in_(("CALL_PATIENT", "EARLIER_SLOT_OFFER")),
                Action.status.in_(RECEIVABLE_BROWSER_CALL_STATUSES),
            )
            .order_by(Action.created_at.desc())
        )
        if action and not (action.payload or {}).get("receiver_ready"):
            action = None
        if action and _expire_browser_action(action):
            _release_unaccepted_offers_on_call_end(session, goal, action, "TIMED_OUT")
            action = None
        # Claim the queued action for this open browser phone before the simulated
        # telephone dispatcher consumes it. Repeated polls keep returning the same
        # ringing action.
        if action and action.status in {"QUEUED", "PROPOSED"}:
            action.status = "RINGING_BROWSER"
        patient = goal.referral.patient
        payload = action.payload if action else {}
        return {
            "waiting": action is None,
            "goal_id": str(goal.id),
            "action_id": str(action.id) if action else None,
            "receiver_token": (action.payload or {}).get("receiver_token") if action else None,
            "patient_first_name": patient.first_name,
            "procedure": goal.referral.procedure,
            "purpose": payload.get("purpose") or ("EARLIER_SLOT_OFFER" if action and action.action_type == "EARLIER_SLOT_OFFER" else "FOLLOW_UP"),
            "reason": payload.get("reason") or "Your caseworker would like to speak with you about your appointment.",
            "preferred_language": patient.preferred_language,
        }


@app.post("/api/demo-phone/answer")
async def demo_phone_answer(request: DemoPhoneAnswerRequest) -> dict:
    """Claim or create exactly one browser call for this patient phone."""
    require_database()
    with session_scope() as session:
        goal = _demo_phone_goal(session, request.claim_code)
        action = session.get(Action, request.action_id) if request.action_id else None
        if action and action.goal_id != goal.id:
            raise HTTPException(404, "Incoming call not found")
        if not action:
            action = session.scalar(
                select(Action)
                .where(
                    Action.goal_id == goal.id,
                    Action.action_type.in_(("CALL_PATIENT", "EARLIER_SLOT_OFFER")),
                    Action.status.in_(RECEIVABLE_BROWSER_CALL_STATUSES),
                )
                .order_by(Action.created_at.desc())
            )
        now = datetime.now(UTC)
        if action and _expire_browser_action(action, now):
            _release_unaccepted_offers_on_call_end(session, goal, action, "TIMED_OUT")
            action = None
        if not action or not (action.payload or {}).get("receiver_ready"):
            raise HTTPException(409, "No incoming call is waiting on this phone")
        action.status = "RINGING_BROWSER"
        if not (action.payload or {}).get("receiver_token"):
            action.payload = {**(action.payload or {}), "receiver_token": uuid4().hex}
        return {
            "goal_id": str(goal.id),
            "action_id": str(action.id),
            "receiver_token": (action.payload or {}).get("receiver_token"),
        }


@app.post("/api/demo-phone/queue", status_code=201)
async def demo_phone_queue(request: DemoPhoneQueueRequest) -> dict:
    """Queue a call for the patient receiver; this never starts browser audio."""
    require_database()
    with session_scope() as session:
        goal = load_goal(session, request.goal_id)
        purpose = request.purpose
        reason = request.reason
        if purpose == "REMINDER":
            booked = session.scalar(
                select(Appointment)
                .where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED")
                .order_by(Appointment.created_at.desc())
            )
            if not booked:
                raise HTTPException(409, "This patient has no current appointment to confirm")
            appointment_at = booked.slot.starts_at.strftime("%A %-d %B at %H:%M UTC")
            reason = (
                f"Confirm that the patient's current {goal.referral.procedure} appointment "
                f"on {appointment_at} at {booked.slot.site} is still suitable. "
                "Do not offer or search for another appointment unless the patient asks to change it."
            )
        reason = reason or "Speak with the patient about their appointment."
        current = session.scalar(
            select(Action)
            .where(
                Action.goal_id == goal.id,
                Action.action_type.in_(("CALL_PATIENT", "EARLIER_SLOT_OFFER")),
                Action.status.in_(LIVE_BROWSER_CALL_STATUSES),
            )
            .order_by(Action.created_at.desc())
        )
        if current:
            current_purpose = (current.payload or {}).get("purpose")
            if current_purpose and current_purpose != purpose:
                raise HTTPException(409, f"A {current_purpose.lower().replace('_', ' ')} call is already active for this patient")
            current.payload = {**(current.payload or {}), "receiver_token": (current.payload or {}).get("receiver_token") or uuid4().hex, "receiver_ready": True}
            return {"queued": True, "action_id": str(current.id), "status": current.status, "expires_in_seconds": 900}
        action = Action(
            goal_id=goal.id,
            action_type="CALL_PATIENT",
            status="QUEUED",
            payload={"purpose": purpose, "reason": reason, "transport": "demo_browser_receiver", "receiver_token": uuid4().hex, "receiver_ready": True},
            idempotency_key=f"demo-browser-call:{goal.id}:{uuid4()}",
            requires_human_approval=False,
        )
        session.add(action)
        session.flush()
        session.add(Event(
            goal_id=goal.id,
            event_type="BROWSER_CALL_QUEUED",
            source="operator",
            payload={"action_id": str(action.id), "purpose": purpose},
            idempotency_key=f"demo-browser-call-event:{action.id}",
        ))
        return {"queued": True, "action_id": str(action.id), "status": "QUEUED", "expires_in_seconds": 900}


@app.post("/api/demo-phone/cancel")
async def demo_phone_cancel(request: DemoPhoneCancelRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, request.goal_id)
        action = session.get(Action, request.action_id)
        if not action or action.goal_id != goal.id:
            raise HTTPException(404, "Queued call not found")
        if _terminalize_browser_action(action, "CANCELLED"):
            _release_unaccepted_offers_on_call_end(session, goal, action, "CANCELLED")
        return {"ok": True, "status": action.status}


@app.get("/api/demo-phone/action-status")
async def demo_phone_action_status(goal_id: UUID, action_id: UUID) -> dict:
    """Small polling projection used to remove the operator banner promptly."""
    require_database()
    with session_scope() as session:
        action = session.get(Action, action_id)
        if not action or action.goal_id != goal_id:
            raise HTTPException(404, "Browser call not found")
        if _expire_browser_action(action):
            goal = load_goal(session, goal_id)
            _release_unaccepted_offers_on_call_end(session, goal, action, "TIMED_OUT")
        return {"action_id": str(action.id), "status": action.status, "live": action.status in LIVE_BROWSER_CALL_STATUSES, "outcome": (action.result or {}).get("outcome")}


@app.post("/api/demo-phone/complete")
async def demo_phone_complete(request: DemoPhoneEndRequest) -> dict:
    """Idempotently close an accepted browser conversation."""
    require_database()
    with session_scope() as session:
        goal = load_goal(session, request.goal_id)
        action = session.get(Action, request.action_id)
        if (
            not action
            or action.goal_id != goal.id
            or (action.payload or {}).get("receiver_token") != request.receiver_token
        ):
            raise HTTPException(403, "This browser phone is not authorised to end the call")
        requested_outcome = getattr(request, "outcome", "COMPLETED")
        changed = _terminalize_browser_action(action, requested_outcome, transport="browser_websocket")
        if changed:
            _release_unaccepted_offers_on_call_end(session, goal, action, requested_outcome)
            purpose = (action.payload or {}).get("purpose") or "FOLLOW_UP"
            session.add(Communication(
                goal_id=goal.id,
                channel="BROWSER_VOICE",
                direction="OUTBOUND",
                external_id=f"browser:{action.id}",
                purpose=purpose,
                outcome="ANSWERED" if requested_outcome == "COMPLETED" else "FAILED" if requested_outcome == "FAILED" else "NO_ANSWER",
                language=language_code(goal.referral.patient.preferred_language),
                summary="Patient completed a browser voice conversation with the caseworker.",
            ))
            session.add(Event(
                goal_id=goal.id,
                event_type="VOICE_CALL_COMPLETED" if requested_outcome == "COMPLETED" else "VOICE_CALL_FAILED" if requested_outcome == "FAILED" else "VOICE_CALL_TIMED_OUT",
                source="demo_browser_receiver",
                payload={"action_id": str(action.id), "purpose": purpose, "transport": "browser_websocket"},
                idempotency_key=f"demo-phone-completed:{action.id}",
            ))
            session.flush()
            if requested_outcome == "COMPLETED":
                # Finishing any caseworker call hands control back to the global
                # overseer. It advances one capacity opportunity, wakes that
                # patient's caseworker, then returns to its loop.
                match_available_slots(session, limit=1)
        return {"ok": True, "status": action.status, "outcome": (action.result or {}).get("outcome")}


@app.post("/api/demo-phone/decline")
async def demo_phone_decline(request: DemoPhoneDeclineRequest) -> dict:
    """Record that the receiver declined the current browser demo call."""
    require_database()
    with session_scope() as session:
        goal = _demo_phone_goal(session, request.claim_code)
        action = session.get(Action, request.action_id) if request.action_id else None
        if action and action.goal_id != goal.id:
            raise HTTPException(404, "Incoming call not found")
        if action and _terminalize_browser_action(action, "DECLINED"):
            _release_unaccepted_offers_on_call_end(session, goal, action, "DECLINED")
            session.add(Event(
                goal_id=goal.id,
                event_type="VOICE_CALL_DECLINED",
                source="demo_browser_receiver",
                payload={"action_id": str(action.id), "purpose": (action.payload or {}).get("purpose")},
                idempotency_key=f"demo-phone-declined:{action.id}",
            ))
        elif not action:
            action = Action(
                goal_id=goal.id,
                action_type="CALL_PATIENT",
                status="DECLINED",
                payload={"purpose": "FOLLOW_UP", "transport": "demo_browser_receiver"},
                result={"outcome": "DECLINED", "transport": "demo_browser_receiver"},
                completed_at=datetime.now(UTC),
                idempotency_key=f"demo-browser-decline:{goal.id}:{uuid4()}",
                requires_human_approval=False,
            )
            session.add(action)
            session.flush()
            _release_unaccepted_offers_on_call_end(session, goal, action, "DECLINED")
            session.add(Event(
                goal_id=goal.id,
                event_type="VOICE_CALL_DECLINED",
                source="demo_browser_receiver",
                payload={"action_id": str(action.id), "purpose": "FOLLOW_UP"},
                idempotency_key=f"demo-phone-declined:{action.id}",
            ))
        return {"ok": True, "outcome": "DECLINED"}


@app.get("/api/patients")
def patients() -> list[dict]:
    require_database()
    def load():
        with read_session_scope() as session:
            goals = session.scalars(goal_query().order_by(Goal.updated_at.desc())).unique().all()
            if not any(_has_recoverable_blocker(goal) for goal in goals):
                return [case_json(goal) for goal in goals]
        return None
    result = _cached_read("patients", load)
    if result is not None:
        return result
    # Legacy demo blockers are rare, but healing them is intentionally a write.
    # Re-open a transactional session only for that exceptional path.
    with session_scope() as session:
        goals = session.scalars(goal_query().order_by(Goal.updated_at.desc())).unique().all()
        for goal in goals:
            _heal_recoverable_blocker(goal)
        return [case_json(goal) for goal in goals]


@app.get("/api/appointment-types")
async def appointment_types(active_only: bool = True) -> list[dict]:
    require_database()
    with session_scope() as session:
        query = select(AppointmentType).order_by(AppointmentType.name)
        if active_only:
            query = query.where(AppointmentType.is_active.is_(True))
        rows = session.scalars(query).all()
        return [{"id": str(row.id), "code": row.code, "name": row.name, "default_duration_minutes": row.default_duration_minutes, "preparation_requirements": row.preparation_note, "preparation_note": row.preparation_note, "is_active": row.is_active, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()} for row in rows]


@app.get("/api/patients/{goal_id}")
async def patient_detail(goal_id: UUID) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, goal_id); result = case_json(goal)
        result["date_of_birth"] = goal.referral.patient.date_of_birth.date().isoformat() if goal.referral.patient.date_of_birth else None
        events = session.scalars(select(Event).where(Event.goal_id == goal_id).order_by(Event.created_at.desc())).all()
        result["timeline"] = [{"id": str(e.id), "type": e.event_type, "source": e.source, "payload": e.payload, "created_at": e.created_at.isoformat()} for e in events]
        notes = session.scalars(select(CaseNote).where(CaseNote.patient_id == goal.referral.patient_id).order_by(CaseNote.created_at.desc())).all()
        note_ids = [note.id for note in notes]
        revisions = session.scalars(select(CaseNoteVersion).where(CaseNoteVersion.note_id.in_(note_ids)).order_by(CaseNoteVersion.version.desc())).all() if note_ids else []
        revisions_by_note: dict[UUID, list[CaseNoteVersion]] = {}
        for revision in revisions:
            revisions_by_note.setdefault(revision.note_id, []).append(revision)
        result["case_notes"] = [case_note_json(note, revisions_by_note.get(note.id, [])) for note in notes]
        steps = session.scalars(select(AgentStep).where(AgentStep.goal_id == goal_id).order_by(AgentStep.created_at.desc())).all()
        step_ids = [step.id for step in steps]
        calls = session.scalars(select(AgentToolCall).where(AgentToolCall.step_id.in_(step_ids)).order_by(AgentToolCall.step_id, AgentToolCall.sequence)).all() if step_ids else []
        calls_by_step: dict[UUID, list[dict]] = {}
        for call in calls:
            calls_by_step.setdefault(call.step_id, []).append(tool_call_json(call))
        result["agent_steps"] = [agent_step_json(step, calls_by_step.get(step.id, [])) for step in steps]
        documents = ensure_case_files(session, goal)
        document_ids = [document.id for document in documents]
        versions = session.scalars(select(CaseDocumentVersion).where(CaseDocumentVersion.document_id.in_(document_ids)).order_by(CaseDocumentVersion.document_id, CaseDocumentVersion.version.desc())).all() if document_ids else []
        versions_by_document: dict[UUID, list[CaseDocumentVersion]] = {}
        for version in versions:
            versions_by_document.setdefault(version.document_id, []).append(version)
        result["case_documents"] = [case_document_json(document, versions_by_document.get(document.id, [])) for document in documents]
        return result


@app.patch("/api/patients/{goal_id}")
async def update_patient(goal_id: UUID, body: PatientUpdate) -> dict:
    """Update the shared patient profile used by operators and caseworkers."""
    require_database()
    with session_scope() as session:
        goal = load_goal(session, goal_id)
        patient = goal.referral.patient
        before_language = patient.preferred_language
        patient.first_name = body.first_name.strip()
        patient.last_name = body.last_name.strip()
        patient.date_of_birth = datetime.combine(body.date_of_birth, time.min, tzinfo=UTC)
        patient.phone = body.phone
        patient.email = body.email.strip() if body.email else None
        patient.preferred_language = body.preferred_language.strip()
        patient.preferred_contact_method = body.preferred_contact_method.strip().upper()
        session.add(Event(
            goal_id=goal.id,
            event_type="PATIENT_DETAILS_UPDATED",
            source="operator",
            payload={"fields": ["name", "date_of_birth", "phone", "email", "preferred_language", "preferred_contact_method"], "previous_language": before_language, "preferred_language": patient.preferred_language},
            idempotency_key=f"patient-update:{goal.id}:{uuid4()}",
        ))
        session.flush()
        return case_json(goal)


@app.get("/api/patients/{goal_id}/agent-history")
@app.get("/api/goals/{goal_id}/agent-history", operation_id="goal_agent_history")
@app.get("/api/patients/{goal_id}/agent-history", operation_id="patient_agent_history")
async def agent_history(goal_id: UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = None) -> dict:
    """Paginated, causal execution history for one long-running caseworker."""
    require_database()
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError as exc:
            raise HTTPException(422, "Invalid history cursor") from exc
    with session_scope() as session:
        load_goal(session, goal_id)
        total = session.scalar(select(func.count()).select_from(AgentStep).where(AgentStep.goal_id == goal_id)) or 0
        steps = list(session.scalars(select(AgentStep).where(AgentStep.goal_id == goal_id).order_by(AgentStep.created_at.desc(), AgentStep.id.desc()).offset(offset).limit(limit)).all())
        step_ids = [step.id for step in steps]
        calls = session.scalars(select(AgentToolCall).where(AgentToolCall.step_id.in_(step_ids)).order_by(AgentToolCall.step_id, AgentToolCall.sequence)).all() if step_ids else []
        calls_by_step: dict[UUID, list[dict]] = {}
        for call in calls:
            calls_by_step.setdefault(call.step_id, []).append(tool_call_json(call))
        events = list(session.scalars(select(Event).where(Event.goal_id == goal_id).order_by(Event.created_at.desc())).all())
        records = []
        for step in steps:
            upper = session.scalar(select(AgentStep.created_at).where(AgentStep.goal_id == goal_id, AgentStep.created_at > step.created_at).order_by(AgentStep.created_at.asc()).limit(1))
            related = [event for event in events if event.created_at >= step.created_at and (upper is None or event.created_at < upper)]
            record = agent_step_json(step, calls_by_step.get(step.id, []))
            record["related_events"] = [{"id": str(event.id), "type": event.event_type, "source": event.source, "payload": event.payload, "created_at": event.created_at.isoformat()} for event in related]
            records.append(record)
        next_offset = offset + len(records) if offset + len(records) < total else None
        event_rows = {event["id"]: event for record in records for event in record["related_events"]}
        documents = []
        if offset == 0:
            for document in session.scalars(select(CaseDocument).where(CaseDocument.goal_id == goal_id).order_by(CaseDocument.created_at)).all():
                versions = session.scalars(select(CaseDocumentVersion).where(CaseDocumentVersion.document_id == document.id).order_by(CaseDocumentVersion.version.desc())).all()
                documents.append(case_document_json(document, list(versions)))
        return {"goal_id": str(goal_id), "total": total, "limit": limit, "offset": offset, "has_more": next_offset is not None, "next_offset": next_offset, "next_cursor": str(next_offset) if next_offset is not None else None, "steps": records, "events": list(event_rows.values()), "documents": documents}


@app.post("/api/patients/{goal_id}/notes", status_code=201)
async def add_case_note(goal_id: UUID, body: CaseNoteCreate) -> dict:
    require_database()
    category, text = body.category.strip().upper(), body.text.strip()
    if not category or len(category) > 40:
        raise HTTPException(422, "Category must be between 1 and 40 characters")
    if not text:
        raise HTTPException(422, "Note text is required")
    with session_scope() as session:
        goal = load_goal(session, goal_id)
        note = create_note(session, patient_id=goal.referral.patient_id, referral_id=goal.referral_id, goal_id=goal.id, category=category, text=text, language=goal.referral.patient.preferred_language, source="OPERATOR")
        revision = session.get(CaseNoteVersion, note.current_version_id)
        session.add(Event(goal_id=goal.id, event_type="CASE_NOTE_VERSION_CREATED", source="operator", payload={"category": category, "note_id": str(note.id), "version_id": str(revision.id), "version": 1}, idempotency_key=f"operator-note:{revision.id}"))
        return case_note_json(note, [revision])


@app.put("/api/patients/{goal_id}/notes/{note_id}")
async def update_case_note(goal_id: UUID, note_id: UUID, body: CaseNoteUpdate) -> dict:
    require_database()
    category, text = body.category.strip().upper(), body.text.strip()
    if not category or len(category) > 40 or not text:
        raise HTTPException(422, "A valid category and note text are required")
    with session_scope() as session:
        goal = load_goal(session, goal_id)
        note = session.scalar(select(CaseNote).where(CaseNote.id == note_id, CaseNote.patient_id == goal.referral.patient_id).with_for_update())
        if not note:
            raise HTTPException(404, "Case note not found")
        revision = revise_note(session, note, category=category, text=text, language=goal.referral.patient.preferred_language, source=body.source.strip().upper() or "OPERATOR")
        session.add(Event(goal_id=goal.id, event_type="CASE_NOTE_VERSION_CREATED", source=revision.source.lower(), payload={"note_id": str(note.id), "version_id": str(revision.id), "version": revision.version}, idempotency_key=f"case-note-version:{revision.id}"))
        versions = list(session.scalars(select(CaseNoteVersion).where(CaseNoteVersion.note_id == note.id).order_by(CaseNoteVersion.version.desc())).all())
        return case_note_json(note, versions)


@app.post("/api/referrals", status_code=201)
async def create_referral(body: ReferralCreate) -> dict:
    require_database()
    with session_scope() as session:
        appointment_type = resolve_appointment_type(session, body.appointment_type_id, body.appointment_type_code)
        procedure = appointment_type.name if appointment_type else (body.procedure or "").strip()
        if not procedure:
            raise HTTPException(422, "Procedure or appointment type is required")
        patient = Patient(external_ref=body.external_ref, first_name=body.first_name, last_name=body.last_name, date_of_birth=datetime.combine(body.date_of_birth, time.min, tzinfo=UTC), phone=body.phone, email=body.email, preferred_contact_method=body.preferred_contact_method, preferred_language=body.preferred_language, constraints={})
        referral = Referral(patient=patient, appointment_type_id=appointment_type.id if appointment_type else None, pathway_type=body.pathway_type, procedure=procedure, referring_org=body.referring_org, provider_org=body.provider_org, status="ACTIVE")
        goal = Goal(referral=referral, description=f"Get {body.first_name} from referral to completed {body.pathway_type}", success_criteria={"appointment_status": "COMPLETED"}, status="ACTIVE")
        session.add(goal); session.flush()
        session.add(Event(goal_id=goal.id, event_type="REFERRAL_RECEIVED", source="api", payload={}, idempotency_key=f"referral:{referral.id}"))
        return {"goal_id": str(goal.id), "referral_id": str(referral.id), "patient_id": str(patient.id), "appointment_type_id": str(appointment_type.id) if appointment_type else None, "procedure": procedure}


@app.get("/api/slots")
def slots() -> list[dict]:
    require_database()
    def load():
        with read_session_scope() as session:
            rows = session.scalars(select(Slot).where(Slot.starts_at >= datetime.now(UTC)).order_by(Slot.starts_at).limit(100)).all()
            return [{"id": str(s.id), "appointment_type_id": str(s.appointment_type_id) if s.appointment_type_id else None, "time": s.starts_at.isoformat(), "site": s.site, "procedure": s.procedure, "state": s.status, "duration_minutes": s.duration_minutes} for s in rows]
    return _cached_read("slots", load)


@app.post("/api/slots", status_code=201)
async def create_slot(body: SlotCreate) -> dict:
    require_database()
    with session_scope() as session:
        appointment_type = resolve_appointment_type(session, body.appointment_type_id, body.appointment_type_code)
        procedure = appointment_type.name if appointment_type else (body.procedure or "").strip()
        if not procedure:
            raise HTTPException(422, "Procedure or appointment type is required")
        duration = body.duration_minutes or (appointment_type.default_duration_minutes if appointment_type else 30)
        slot = Slot(external_ref=body.external_ref, appointment_type_id=appointment_type.id if appointment_type else None, provider_org=body.provider_org, site=body.site, procedure=procedure, starts_at=body.starts_at, duration_minutes=duration, properties={}, status="AVAILABLE")
        session.add(slot); session.flush()
        waiting_goals = session.scalars(select(Goal).join(Referral).where(Referral.procedure == procedure, Goal.status.in_(["ACTIVE", "WAITING"]))).all()
        now = datetime.now(UTC)
        for goal in waiting_goals:
            goal.next_wake_at = now
            session.add(Event(goal_id=goal.id, event_type="CAPACITY_CHANGED", source="api", payload={"slot_id": str(slot.id)}, idempotency_key=f"capacity:{slot.id}:{goal.id}"))
        return {"id": str(slot.id), "appointment_type_id": str(slot.appointment_type_id) if slot.appointment_type_id else None, "time": slot.starts_at.isoformat(), "site": slot.site, "procedure": slot.procedure, "state": slot.status, "duration_minutes": slot.duration_minutes}


@app.get("/api/dashboard")
def dashboard() -> dict:
    require_database()
    def load():
        with read_session_scope() as session:
            counts = dict(session.execute(select(Goal.status, func.count()).group_by(Goal.status)).all())
            return {"active": counts.get("ACTIVE", 0) + counts.get("WAITING", 0), "needs_attention": counts.get("HUMAN_REVIEW_REQUIRED", 0), "completed": counts.get("COMPLETED", 0), "open_slots": session.scalar(select(func.count()).select_from(Slot).where(Slot.status == "AVAILABLE")) or 0, "reminder_lead_hours": REMINDER_LEAD_HOURS, "reminder_policy": f"Reminder scheduled {REMINDER_LEAD_HOURS} hours before the appointment"}
    return _cached_read("dashboard", load)


@app.get("/api/policies/reminders")
async def reminder_policy() -> dict:
    return {"lead_hours": REMINDER_LEAD_HOURS, "purpose": "REMINDER", "label": f"Reminder scheduled {REMINDER_LEAD_HOURS} hours before the appointment"}


@app.post("/api/voice/call")
async def call_patient(request: CallRequest) -> dict:
    if settings.database_url and not request.preferred_language:
        with session_scope() as session:
            request.preferred_language = load_goal(session, request.goal_id).referral.patient.preferred_language
    provider: VoiceProvider = FakeVoiceProvider() if settings.use_fake_voice else ElevenLabsVoiceProvider()
    result = await provider.call_patient(request)
    if settings.database_url:
        with session_scope() as session:
            goal = load_goal(session, request.goal_id)
            external_id = result.get("conversation_id") or result.get("conversation_id", f"call-{uuid4()}")
            code = language_code(request.preferred_language or goal.referral.patient.preferred_language)
            simulated = bool(result.get("simulated"))
            outcome = result.get("outcome", "QUEUED")
            metadata = {"conversation_id": external_id, "purpose": request.purpose, "outcome": outcome, "language": code, "simulated": simulated, "provider": result.get("provider"), "transport": result.get("transport")}
            session.add_all([Communication(goal_id=goal.id, channel="SIMULATED_VOICE" if simulated else "VOICE", direction="OUTBOUND", external_id=external_id, purpose=request.purpose, outcome=outcome, language=code, summary=("[SIMULATED — no telephone call placed] " if simulated else "") + request.reason), Event(goal_id=goal.id, event_type="VOICE_CALL_SIMULATED" if simulated else "VOICE_CALL_REQUESTED", source="simulated_voice" if simulated else "api", payload=metadata, idempotency_key=f"call:{external_id}")])
    return result


@app.post("/api/agents/run-due")
async def run_due_agents(body: RunAgentsRequest) -> dict:
    require_database()
    with session_scope() as session:
        goals = due_goals(session, max(1, min(body.limit, 25)))
        results = []
        for goal in goals:
            try:
                results.append(run_goal(session, goal))
            except RuntimeError as exc:
                raise HTTPException(503, str(exc)) from exc
        return {"processed": len(results), "results": results}


@app.post("/api/capacity/run")
async def run_capacity_matcher() -> dict:
    require_database()
    pass_id = uuid4().hex
    with session_scope() as session:
        session.add(Event(
            goal_id=None,
            event_type="OVERSEER_PASS_STARTED",
            source="capacity_overseer",
            payload={"pass_id": pass_id, "iteration_status": "RUNNING"},
            idempotency_key=f"overseer-pass-started:{pass_id}",
        ))
    with session_scope() as session:
        capacity = ensure_weekday_capacity(
            session,
            horizon_days=settings.demo_capacity_horizon_days,
            duration_override_minutes=settings.demo_capacity_slot_minutes,
        )
        result = match_available_slots(session, pass_id=pass_id)
        result["started_pass_id"] = pass_id
        result["capacity"] = capacity
        return result


@app.post("/api/demo/reset")
async def reset_demo_data(
    body: DemoResetRequest,
    x_nous_demo: str | None = Header(default=None),
) -> dict:
    """Transactionally restore the fixed DEMO-* presenter cohort."""
    global _demo_reset_last_at
    if x_nous_demo != "1":
        raise HTTPException(404, "Not found")
    cached = _demo_reset_results.get(body.operation_id)
    if cached is not None:
        return cached
    if not _demo_reset_lock.acquire(blocking=False):
        raise HTTPException(409, "A demo reset is already running")
    try:
        cached = _demo_reset_results.get(body.operation_id)
        if cached is not None:
            return cached
        elapsed = monotonic() - _demo_reset_last_at
        if _demo_reset_last_at and elapsed < DEMO_RESET_COOLDOWN_SECONDS:
            retry_after = max(1, int(DEMO_RESET_COOLDOWN_SECONDS - elapsed) + 1)
            raise HTTPException(
                429,
                f"Demo reset was run recently; retry in {retry_after} seconds",
                headers={"Retry-After": str(retry_after)},
            )
        require_database()
        with session_scope() as session:
            before = audit_demo_state(session)
            changes = cleanup_demo_state(session)
            session.flush()
            after = audit_demo_state(session)
            if not after["valid"]:
                raise HTTPException(
                    409,
                    {"message": "Demo reset validation failed; no changes were committed", "violations": after["violations"]},
                )
        result = {
            "operation_id": body.operation_id,
            "scope": "DEMO-*",
            "changes": changes,
            "before_counts": before["counts"],
            "after_counts": after["counts"],
            "status_counts": after["status_counts"],
            "validation": {"valid": after["valid"], "violations": after["violations"]},
            "retained_patients": [row["external_ref"] for row in after["patients"]],
        }
        _demo_reset_last_at = monotonic()
        _demo_reset_results[body.operation_id] = result
        while len(_demo_reset_results) > 20:
            _demo_reset_results.pop(next(iter(_demo_reset_results)))
        return result
    finally:
        _demo_reset_lock.release()


@app.post("/api/demo/trigger-released-slot")
async def trigger_released_slot_demo(x_nous_demo: str | None = Header(default=None)) -> dict:
    """Synchronously prepare the fixed DEMO-OVERSEER cohort only."""
    if x_nous_demo != "1":
        raise HTTPException(404, "Not found")
    require_database()
    with session_scope() as session:
        demo_goals = session.scalars(
            goal_query().join(Goal.referral).join(Referral.patient)
            .where(Patient.external_ref.like("DEMO-OVERSEER-%"))
        ).unique().all()
        goals_by_ref = {goal.referral.patient.external_ref: goal for goal in demo_goals}
        source = goals_by_ref.get("DEMO-OVERSEER-SOURCE")
        if not source:
            raise HTTPException(409, "The overseer demo cohort has not been seeded")

        demo_ids = [goal.id for goal in demo_goals]
        existing = session.scalar(
            select(Action)
            .where(Action.goal_id.in_(demo_ids), Action.action_type == "EARLIER_SLOT_OFFER")
            .order_by(Action.created_at.desc())
        )
        if existing:
            selected = next((goal for goal in demo_goals if goal.id == existing.goal_id), None)
            existing.status = "QUEUED"
            existing.completed_at = None
            existing.result = None
            existing.payload = {**(existing.payload or {}), "receiver_token": uuid4().hex, "transport": "demo_browser_receiver"}
            return {"ready": True, "reused": True, "selected_patient": selected.referral.patient.external_ref if selected else None, "phone_url": f"/phone?claim={selected.referral.patient.external_ref}" if selected else None}

        appointment = session.scalar(
            select(Appointment)
            .where(Appointment.referral_id == source.referral_id, Appointment.status == "BOOKED")
            .order_by(Appointment.created_at.asc())
        )
        if not appointment:
            raise HTTPException(409, "The demo source appointment is not booked")
        appointment.status = "CANCELLED"
        appointment.slot.status = "AVAILABLE"
        appointment.slot.held_until = None
        appointment.slot.properties = {**(appointment.slot.properties or {}), "released_gap": True, "release_reason": "presenter_demo"}
        session.add(Event(
            goal_id=source.id,
            event_type="SLOT_RELEASED",
            source="presenter_demo",
            payload={"slot_id": str(appointment.slot_id), "appointment_id": str(appointment.id), "capacity_gap": True},
            idempotency_key=f"presenter-demo-release:{appointment.id}",
        ))
        session.flush()
        result = match_available_slots(session, limit=1, released_only=True)
        offer = (result.get("offers") or [None])[0]
        selected = next((goal for goal in demo_goals if offer and str(goal.id) == offer.get("goal_id")), None)
        return {"ready": bool(selected), "reused": False, "selected_patient": selected.referral.patient.external_ref if selected else None, "phone_url": f"/phone?claim={selected.referral.patient.external_ref}" if selected else None, "overseer": result}


def _caseworker_phone_status(action: Action) -> str:
    status = action.status.upper()
    if status in {"QUEUED", "PROPOSED"}:
        return "Ready to call"
    if status in {"INCOMING", "RINGING", "RINGING_BROWSER", "CONNECTING"}:
        return "Calling patient"
    if status in {"CONNECTED", "IN_PROGRESS"}:
        return "On call"
    if status == "COMPLETED":
        result = action.result or {}
        return str(result.get("outcome") or result.get("status") or "Call completed")
    return status.replace("_", " ").title()


@app.get("/api/overseer/workflow")
def overseer_workflow() -> dict:
    """Return the latest released-slot cascade from persisted audit records.

    This deliberately does not invent progress from current capacity. Every stage
    shown by the UI is backed by a GoalDecision, Event, Action or Communication.
    """
    require_database()
    with read_session_scope() as session:
        now = datetime.now(UTC)
        latest_pass = session.scalar(
            select(Event)
            .where(Event.event_type == "OVERSEER_PASS_COMPLETED")
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        latest_started = session.scalar(
            select(Event)
            .where(Event.event_type == "OVERSEER_PASS_STARTED")
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        pass_payload = (latest_pass.payload or {}) if latest_pass else {}
        cycle_updated_at = latest_pass.created_at.isoformat() if latest_pass else now.isoformat()
        cycle_next_wake_at = pass_payload.get("next_wake_at") or (now + timedelta(seconds=60)).isoformat()
        started_pass_id = str(((latest_started.payload or {}) if latest_started else {}).get("pass_id") or "")
        completed_pass_id = str(pass_payload.get("pass_id") or "")
        if latest_started and started_pass_id != completed_pass_id:
            slots_checked = session.scalar(select(func.count()).select_from(Slot).where(Slot.status == "AVAILABLE", Slot.starts_at >= now, Slot.starts_at < now + timedelta(days=7))) or 0
            compatible_patients = session.scalar(select(func.count()).select_from(Goal).where(Goal.status.in_(("ACTIVE", "WAITING")))) or 0
            return {
                "active": True,
                "run_state": "RUNNING",
                "updated_at": latest_started.created_at.isoformat(),
                "iteration_started_at": latest_started.created_at.isoformat(),
                "next_wake_seconds": 60,
                "last_iteration_summary": "Scanning available appointments",
                "scan_stats": {"slots_checked": slots_checked, "compatible_patients": compatible_patients},
                "stages": [
                    {"key": "scan", "label": "Scan available slots", "complete": False, "active": True},
                    {"key": "evaluate", "label": "Evaluate candidates", "complete": False},
                    {"key": "rank", "label": "Rank and select", "complete": False},
                    {"key": "wake", "label": "Wake caseworker", "complete": False},
                ],
                "candidates": [],
            }
        recent_decisions = session.scalars(select(GoalDecision).order_by(GoalDecision.created_at.desc()).limit(100)).all()
        overseer_decisions = [row for row in recent_decisions if (row.observation or {}).get("overseer_run") == "released_slot_ranking"]
        decision = overseer_decisions[0] if overseer_decisions else None
        if not decision:
            slots_checked = session.scalar(select(func.count()).select_from(Slot).where(Slot.status == "AVAILABLE", Slot.starts_at >= now, Slot.starts_at < now + timedelta(days=7))) or 0
            compatible_patients = session.scalar(select(func.count()).select_from(Goal).where(Goal.status.in_(("ACTIVE", "WAITING")))) or 0
            return {"active": True, "run_state": "NEXT_SCAN_SCHEDULED", "iteration": 1, "updated_at": cycle_updated_at, "iteration_started_at": cycle_updated_at, "next_wake_at": cycle_next_wake_at, "next_wake_seconds": 60, "total_delegations": 0, "last_iteration_summary": pass_payload.get("summary") or "No actionable release this pass", "scan_stats": {"slots_checked": slots_checked, "compatible_patients": compatible_patients}, "stages": [{"key": "scan", "label": "Next scan scheduled", "complete": False, "active": False}], "candidates": []}

        observation = decision.observation or {}
        proposed = decision.proposed_action or {}
        slot_id = str(observation.get("slot_id") or proposed.get("slot_id") or "")
        slot = session.get(Slot, UUID(slot_id)) if slot_id else None
        ranked = observation.get("ranked_choices") or []
        goal_ids = []
        for choice in ranked:
            try:
                goal_ids.append(UUID(str(choice.get("goal_id"))))
            except (TypeError, ValueError):
                continue
        goals = session.scalars(goal_query().where(Goal.id.in_(goal_ids))).unique().all() if goal_ids else []
        goals_by_id = {str(goal.id): goal for goal in goals}
        candidates = []
        for choice in ranked:
            candidate = goals_by_id.get(str(choice.get("goal_id")))
            candidates.append({
                "rank": choice.get("rank"),
                "goal_id": str(choice.get("goal_id")),
                "patient_name": f"{candidate.referral.patient.first_name} {candidate.referral.patient.last_name}" if candidate else "Patient record",
                "patient_external_ref": candidate.referral.patient.external_ref if candidate else None,
                "score": choice.get("score"),
                "reasons": choice.get("reasons") or [],
                "selected": str(choice.get("goal_id")) == str(decision.goal_id),
            })

        relevant_events = session.scalars(
            select(Event)
            .where(or_(Event.goal_id == decision.goal_id, Event.payload["slot_id"].as_string() == slot_id))
            .order_by(Event.created_at.asc())
        ).all()
        release = next((event for event in relevant_events if event.event_type == "SLOT_RELEASED"), None)
        delegated = next((event for event in relevant_events if event.event_type == "OVERSEER_DELEGATED"), None)
        actions = session.scalars(select(Action).where(Action.goal_id == decision.goal_id).order_by(Action.created_at.desc())).all()
        action = next((row for row in actions if row.action_type in {"CALL_PATIENT", "EARLIER_SLOT_OFFER"} and str((row.payload or {}).get("proposed_slot_id", "")) == slot_id), None)
        selected = goals_by_id.get(str(decision.goal_id))
        handoff_label = f"Woke caseworker for {selected.referral.patient.first_name}" if selected else "Caseworker delegated"
        if delegated:
            slots_checked = session.scalar(select(func.count()).select_from(Slot).where(Slot.status == "AVAILABLE", Slot.starts_at >= now, Slot.starts_at < now + timedelta(days=7))) or 0
            compatible_patients = session.scalar(select(func.count()).select_from(Goal).where(Goal.status.in_(("ACTIVE", "WAITING")))) or 0
            return {
                "active": True,
                "run_state": "NEXT_SCAN_SCHEDULED",
                "iteration": len(overseer_decisions) + 1,
                "updated_at": cycle_updated_at,
                "iteration_started_at": cycle_updated_at,
                "next_wake_at": cycle_next_wake_at,
                "next_wake_seconds": 60,
                "total_delegations": len(overseer_decisions),
                "last_iteration_summary": handoff_label,
                "last_delegation": {"decision_id": str(decision.id), "goal_id": str(decision.goal_id), "action_id": str(action.id) if action else None, "delegation_key": (delegated.payload or {}).get("delegation_key")},
                "scan_stats": {"slots_checked": slots_checked, "compatible_patients": compatible_patients},
                "stages": [{"key": "scan", "label": "Next scan scheduled", "complete": False, "active": False}],
                "candidates": [],
                "action": None,
            }
        if action and action.status in {"DECLINED", "FAILED", "EXPIRED", "CANCELLED", "COMPLETED"}:
            now = datetime.now(UTC)
            slots_checked = session.scalar(select(func.count()).select_from(Slot).where(Slot.status == "AVAILABLE", Slot.starts_at >= now, Slot.starts_at < now + timedelta(days=7))) or 0
            compatible_patients = session.scalar(select(func.count()).select_from(Goal).where(Goal.status.in_(("ACTIVE", "WAITING")))) or 0
            outcome = "Caseworker call declined; retry remains with the caseworker" if action.status == "DECLINED" else "Previous caseworker handoff completed"
            return {"active": True, "iteration": len(overseer_decisions) + 1, "updated_at": now.isoformat(), "iteration_started_at": now.isoformat(), "next_wake_seconds": 60, "total_delegations": len(overseer_decisions), "last_iteration_summary": outcome, "scan_stats": {"slots_checked": slots_checked, "compatible_patients": compatible_patients}, "stages": [{"key": "scan", "label": "Scan available slots", "complete": False, "active": True}, {"key": "evaluate", "label": "Evaluate candidates", "complete": False}, {"key": "rank", "label": "Rank and select", "complete": False}, {"key": "wake", "label": "Wake caseworker", "complete": False}], "candidates": []}
        handed_off = delegated is not None
        stages = [
            {"key": "scan", "label": "Scan available slots", "complete": False if handed_off else release is not None, "active": handed_off, "at": release.created_at.isoformat() if release else None},
            {"key": "evaluate", "label": "Evaluate candidates", "complete": False if handed_off else bool(ranked), "at": decision.created_at.isoformat()},
            {"key": "rank", "label": "Rank and select", "complete": False if handed_off else selected is not None, "at": decision.created_at.isoformat()},
            {"key": "wake", "label": "Wake caseworker", "complete": False if handed_off else delegated is not None, "at": delegated.created_at.isoformat() if delegated else None},
        ]
        return {
            "active": True,
            "decision_id": str(decision.id),
            "updated_at": max([row.created_at for row in relevant_events] + [decision.created_at] + ([action.created_at] if action else [])).isoformat(),
            "slot": {"id": slot_id, "starts_at": slot.starts_at.isoformat() if slot else None, "procedure": slot.procedure if slot else None, "site": slot.site if slot else None},
            "policy": observation.get("ranking_policy"),
            "rationale": decision.reasoning_summary,
            "candidates": candidates,
            "selected_patient": {"goal_id": str(decision.goal_id), "name": f"{selected.referral.patient.first_name} {selected.referral.patient.last_name}" if selected else "Patient record", "external_ref": selected.referral.patient.external_ref if selected else None},
            "action": {"id": str(action.id), "status": action.status, "phone_status": _caseworker_phone_status(action)} if action else None,
            "stages": stages,
            "iteration": len(overseer_decisions) + (1 if handed_off else 0),
            "total_delegations": len(overseer_decisions),
            "iteration_started_at": (delegated.created_at if handed_off else decision.created_at).isoformat(),
            "next_wake_seconds": 60,
            "last_iteration_summary": handoff_label if handed_off else "No eligible match this pass",
            "event_count": len(relevant_events),
        }


@app.post("/api/appointments/reschedule")
async def reschedule(body: RescheduleRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id)
        slot = session.scalar(select(Slot).where(Slot.id == body.slot_id).with_for_update())
        event_key = f"reschedule:{goal.id}:{body.slot_id}"
        existing_event = session.scalar(select(Event).where(Event.idempotency_key == event_key))
        existing = session.scalar(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.slot_id == body.slot_id, Appointment.status == "BOOKED"))
        if existing_event and existing:
            return {"booked": True, "appointment_id": str(existing.id), "slot_id": str(body.slot_id), "reminder_at": goal.next_wake_at.isoformat() if goal.next_wake_at else None}
        if not slot or slot.status != "AVAILABLE" or slot.procedure != goal.referral.procedure or slot.starts_at <= datetime.now(UTC):
            raise HTTPException(409, "Slot is no longer eligible")
        previous = session.scalars(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED").with_for_update()).all()
        replacement = Appointment(referral_id=goal.referral_id, slot_id=slot.id, status="BOOKED")
        slot.status = "BOOKED"
        session.add(replacement); session.flush()
        for appointment in previous:
            appointment.status = "RESCHEDULED"
            appointment.slot.status = "AVAILABLE"
            appointment.slot.properties = {**(appointment.slot.properties or {}), "released_gap": True, "release_reason": "rescheduled", "released_by_goal_id": str(goal.id)}
            session.add(Event(goal_id=goal.id, event_type="SLOT_RELEASED", source="operator", payload={"slot_id": str(appointment.slot_id), "appointment_id": str(appointment.id)}, idempotency_key=f"slot-released:{appointment.id}"))
        reminder_at = reminder_wake_at(slot.starts_at)
        goal.status = "WAITING"; goal.current_blocker = None; goal.next_wake_at = reminder_at
        session.add(Event(goal_id=goal.id, event_type="APPOINTMENT_RESCHEDULED", source="operator", payload={"slot_id": str(slot.id), "previous_appointment_ids": [str(a.id) for a in previous]}, idempotency_key=event_key))
        session.add(Event(goal_id=goal.id, event_type="REMINDER_SCHEDULED", source="system", payload={"appointment_id": str(replacement.id), "appointment_at": slot.starts_at.isoformat(), "reminder_at": reminder_at.isoformat(), "lead_hours": REMINDER_LEAD_HOURS}, idempotency_key=f"reminder:{replacement.id}"))
        # A released appointment is an immediate overseer trigger. The periodic
        # Modal job remains a recovery path, but the demo and production UI do not
        # require an operator to press a matcher button or wait for the next tick.
        overseer = match_available_slots(session, released_only=True)
        return {"booked": True, "appointment_id": str(replacement.id), "slot_id": str(slot.id), "reminder_at": reminder_at.isoformat(), "overseer": overseer}


@app.get("/api/calls")
async def calls() -> list[dict]:
    require_database()
    with session_scope() as session:
        rows = session.scalars(select(Communication).order_by(Communication.created_at.desc()).limit(100)).all()
        return [{"id": str(c.id), "goal_id": str(c.goal_id), "channel": c.channel, "direction": c.direction, "provider_id": c.external_id, "purpose": c.purpose, "outcome": c.outcome, "language": c.language, "summary": c.summary, "created_at": c.created_at.isoformat()} for c in rows]


@app.get("/api/activity")
async def activity() -> list[dict]:
    require_database()
    with session_scope() as session:
        decisions = session.scalars(select(GoalDecision).order_by(GoalDecision.created_at.desc()).limit(100)).all()
        actions = session.scalars(select(Action).order_by(Action.created_at.desc()).limit(100)).all()
        steps = session.scalars(select(AgentStep).order_by(AgentStep.created_at.desc()).limit(100)).all()
        step_ids = [step.id for step in steps]
        calls = session.scalars(select(AgentToolCall).where(AgentToolCall.step_id.in_(step_ids)).order_by(AgentToolCall.step_id, AgentToolCall.sequence)).all() if step_ids else []
        calls_by_step: dict[UUID, list[dict]] = {}
        for call in calls:
            calls_by_step.setdefault(call.step_id, []).append(tool_call_json(call))
        overseer_runs = [overseer_decision_json(decision) for decision in decisions]
        rows = (overseer_runs + [{"id": str(a.id), "goal_id": str(a.goal_id), "kind": "ACTION", "label": a.action_type, "summary": a.status, "created_at": a.created_at.isoformat()} for a in actions] + [agent_step_json(step, calls_by_step.get(step.id, [])) for step in steps])
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)[:100]


def tool_call_json(call: AgentToolCall) -> dict:
    return {"id": str(call.id), "sequence": call.sequence, "tool_name": call.tool_name, "tool_input": call.tool_input, "result_text": call.result_text, "status": call.status, "started_at": call.started_at.isoformat() if call.started_at else None, "completed_at": call.completed_at.isoformat() if call.completed_at else None, "duration_ms": call.duration_ms}


def overseer_decision_json(decision: GoalDecision) -> dict:
    """Expose one persisted deterministic decision through the common run contract."""
    return {
        "id": str(decision.id),
        "goal_id": str(decision.goal_id),
        "kind": "AGENT_STEP",
        "label": decision.proposed_action.get("action", "Capacity decision"),
        "summary": decision.reasoning_summary,
        "mode": "DETERMINISTIC_POLICY",
        "model": "nous-capacity-policy",
        "agent_role": "OVERSEER",
        "agent_version": 1,
        "agent_spec_version_id": None,
        "fallback": False,
        "stop_reason": "delegated",
        "decision": decision.reasoning_summary,
        "error": None,
        "context": {"observation": decision.observation, "proposed_action": decision.proposed_action, "agent_spec": {"role": "OVERSEER", "version": 1}},
        "input_tokens": 0,
        "output_tokens": 0,
        "tool_calls": [{
            "id": f"{decision.id}:rank",
            "sequence": 1,
            "tool_name": "rank_released_slot",
            "tool_input": decision.observation,
            "result_text": str(decision.proposed_action),
            "status": "OK",
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
        }],
        "created_at": decision.created_at.isoformat(),
        "completed_at": None,
        "duration_ms": None,
    }


def agent_step_json(step: AgentStep, tool_calls: list[dict]) -> dict:
    agent_spec = (step.context or {}).get("agent_spec", {})
    completed_at = getattr(step, "completed_at", None)
    return {"id": str(step.id), "goal_id": str(step.goal_id), "agent_spec_version_id": str(step.agent_spec_version_id) if step.agent_spec_version_id else None, "agent_version": agent_spec.get("version"), "agent_role": agent_spec.get("role") or "caseworker", "parent_step_id": str(step.parent_step_id) if step.parent_step_id else None, "sequence": step.sequence, "retry_attempt": step.retry_attempt, "wake_reason": step.wake_reason, "scheduled_next_wake": step.scheduled_next_wake.isoformat() if step.scheduled_next_wake else None, "outcome": step.outcome, "tool_call_count": step.tool_call_count, "kind": "AGENT_STEP", "label": step.decision or "Agent step", "summary": step.error or step.stop_reason or step.mode, "mode": step.mode, "model": step.model, "fallback": step.fallback, "stop_reason": step.stop_reason, "decision": step.decision, "error": step.error, "context": step.context, "input_tokens": step.input_tokens, "output_tokens": step.output_tokens, "tool_calls": tool_calls, "created_at": step.created_at.isoformat(), "completed_at": completed_at.isoformat() if completed_at else None, "duration_ms": getattr(step, "duration_ms", None)}


def agent_version_json(version: AgentSpecVersion, active_version_id: UUID | None = None) -> dict:
    return {"id": str(version.id), "definition_id": str(version.definition_id), "version": version.version, "name": version.name, "role": version.role, "instructions": version.instructions, "tool_policy": version.tool_policy, "model": version.model, "status": version.status, "active": version.id == active_version_id, "created_at": version.created_at.isoformat()}


def agent_definition_json(session, definition: AgentDefinition) -> dict:
    versions = list(session.scalars(select(AgentSpecVersion).where(AgentSpecVersion.definition_id == definition.id).order_by(AgentSpecVersion.version.desc())).all())
    active = next((version for version in versions if version.id == definition.active_version_id), None)
    version_ids = [version.id for version in versions]
    steps = list(session.scalars(select(AgentStep).where(AgentStep.agent_spec_version_id.in_(version_ids)).order_by(AgentStep.created_at.desc()).limit(20)).all()) if version_ids else []
    step_ids = [step.id for step in steps]
    calls = session.scalars(select(AgentToolCall).where(AgentToolCall.step_id.in_(step_ids)).order_by(AgentToolCall.step_id, AgentToolCall.sequence)).all() if step_ids else []
    calls_by_step: dict[UUID, list[dict]] = {}
    for call in calls:
        calls_by_step.setdefault(call.step_id, []).append(tool_call_json(call))
    return {
        "id": str(definition.id), "key": definition.key,
        "active_version_id": str(definition.active_version_id) if definition.active_version_id else None,
        "active_version": active.version if active else None,
        "name": active.name if active else definition.key,
        "role": active.role if active else None,
        "instructions": active.instructions if active else None,
        "allowed_tools": active.tool_policy.get("allowed", []) if active else [],
        "model": active.model if active else None,
        "status": active.status if active else "UNCONFIGURED",
        "versions": [agent_version_json(version, definition.active_version_id) for version in versions],
        "recent_executions": [agent_step_json(step, calls_by_step.get(step.id, [])) for step in steps],
        "last_run_at": steps[0].created_at.isoformat() if steps else None,
    }


@app.get("/api/agent-definitions")
@app.get("/api/agents")
async def agent_definitions() -> list[dict]:
    require_database()
    with session_scope() as session:
        definitions = session.scalars(select(AgentDefinition).order_by(AgentDefinition.key)).all()
        return [agent_definition_json(session, definition) for definition in definitions]


@app.get("/api/agents/{key}")
async def agent_definition(key: str) -> dict:
    require_database()
    with session_scope() as session:
        definition = session.scalar(select(AgentDefinition).where(AgentDefinition.key == key))
        if not definition:
            raise HTTPException(404, "Agent definition not found")
        return agent_definition_json(session, definition)


@app.post("/api/agents/{key}/run")
async def run_agent_operation(key: str, body: AgentRunRequest) -> dict:
    """Explicit operations endpoint; normal execution is driven by durable wakes."""
    require_database()
    if key != "caseworker":
        raise HTTPException(409, "This agent does not support patient-goal execution")
    with session_scope() as session:
        if body.goal_id:
            goals = [load_goal(session, body.goal_id)]
        else:
            goals = due_goals(session, 10)
        return {"agent": key, "processed": len(goals), "results": [run_goal(session, goal) for goal in goals]}


@app.post("/api/agent-definitions/{key}/versions", status_code=201)
async def create_agent_version(key: str, body: AgentVersionCreate) -> dict:
    require_database()
    if not all((body.name.strip(), body.role.strip(), body.instructions.strip(), body.model.strip())):
        raise HTTPException(422, "Name, role, instructions and model are required")
    if body.status not in {"DRAFT", "PUBLISHED", "RETIRED"}:
        raise HTTPException(422, "Invalid agent version status")
    with session_scope() as session:
        definition = session.scalar(select(AgentDefinition).where(AgentDefinition.key == key).with_for_update())
        if not definition:
            definition = AgentDefinition(key=key); session.add(definition); session.flush()
        latest = session.scalar(select(func.max(AgentSpecVersion.version)).where(AgentSpecVersion.definition_id == definition.id)) or 0
        version = AgentSpecVersion(definition_id=definition.id, version=latest + 1, name=body.name.strip(), role=body.role.strip().upper(), instructions=body.instructions.strip(), tool_policy=body.tool_policy, model=body.model.strip(), status=body.status)
        session.add(version); session.flush()
        if body.activate:
            if version.status != "PUBLISHED":
                raise HTTPException(409, "Only a published version can be activated")
            definition.active_version_id = version.id
        return agent_version_json(version, definition.active_version_id)


@app.post("/api/agent-definitions/{key}/versions/{version_number}/activate")
async def activate_agent_version(key: str, version_number: int) -> dict:
    require_database()
    with session_scope() as session:
        definition = session.scalar(select(AgentDefinition).where(AgentDefinition.key == key).with_for_update())
        if not definition:
            raise HTTPException(404, "Agent definition not found")
        version = session.scalar(select(AgentSpecVersion).where(AgentSpecVersion.definition_id == definition.id, AgentSpecVersion.version == version_number))
        if not version:
            raise HTTPException(404, "Agent version not found")
        if version.status != "PUBLISHED":
            raise HTTPException(409, "Only a published version can be activated")
        definition.active_version_id = version.id
        return agent_version_json(version, version.id)


def case_document_json(document: CaseDocument, versions: list[CaseDocumentVersion]) -> dict:
    current = next((version for version in versions if version.id == document.current_version_id), None)
    return {"id": str(document.id), "goal_id": str(document.goal_id), "document_type": document.document_type, "title": document.title, "current_version_id": str(document.current_version_id) if document.current_version_id else None, "current_version": current.version if current else None, "content": current.content if current else None, "provenance": current.created_by if current else None, "created_at": document.created_at.isoformat(), "updated_at": current.created_at.isoformat() if current else document.created_at.isoformat(), "versions": [{"id": str(version.id), "version": version.version, "content": version.content, "supersedes_id": str(version.supersedes_id) if version.supersedes_id else None, "metadata": version.document_metadata, "provenance": version.created_by, "created_by": version.created_by, "created_at": version.created_at.isoformat(), "archived_at": version.archived_at.isoformat() if version.archived_at else None, "current": version.id == document.current_version_id} for version in versions]}


CASE_FILE_DEFINITIONS = (
    ("OVERVIEW", "overview.md", "# Overview\n\nNo overview has been recorded yet."),
    ("PREFERENCES", "preferences.md", "# Preferences\n\nNo preferences have been recorded yet."),
    ("CALL_NOTES", "call-notes.md", "# Call notes\n\nNo calls have been recorded yet."),
)


def ensure_case_files(session, goal: Goal) -> list[CaseDocument]:
    """Create the three shared Markdown case files, carrying legacy notes forward."""
    documents = list(session.scalars(select(CaseDocument).where(CaseDocument.goal_id == goal.id).order_by(CaseDocument.created_at)).all())
    by_title = {document.title.lower(): document for document in documents}
    legacy_notes: list[CaseNote] | None = None
    for document_type, title, empty_content in CASE_FILE_DEFINITIONS:
        if title in by_title:
            continue
        if legacy_notes is None:
            legacy_notes = list(session.scalars(select(CaseNote).where(CaseNote.patient_id == goal.referral.patient_id).order_by(CaseNote.created_at)).all())
        relevant = legacy_notes if document_type == "OVERVIEW" else [
            note for note in legacy_notes
            if (document_type == "PREFERENCES" and note.category in {"PREFERENCE", "CONSTRAINT", "CONTACT"})
            or (document_type == "CALL_NOTES" and note.category not in {"PREFERENCE", "CONSTRAINT", "CONTACT"})
        ]
        content = empty_content
        if relevant:
            heading = "# " + title.removesuffix(".md").replace("-", " ").title()
            content = heading + "\n\n" + "\n".join(
                f"- {note.created_at.date().isoformat()} · {note.category.replace('_', ' ').title()}: {note.text}"
                for note in relevant
            )
        document = CaseDocument(goal_id=goal.id, document_type=document_type, title=title)
        session.add(document); session.flush()
        version = CaseDocumentVersion(document_id=document.id, content=content, version=1, document_metadata={"format": "markdown", "provenance": "legacy_note_migration" if relevant else "system_initialisation"}, created_by="MIGRATION" if relevant else "SYSTEM")
        session.add(version); session.flush(); document.current_version_id = version.id
        documents.append(document); by_title[title] = document
    return [by_title[title] for _, title, _ in CASE_FILE_DEFINITIONS]


@app.get("/api/goals/{goal_id}/documents")
async def case_documents(goal_id: UUID) -> list[dict]:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, goal_id)
        documents = ensure_case_files(session, goal)
        result = []
        for document in documents:
            versions = session.scalars(select(CaseDocumentVersion).where(CaseDocumentVersion.document_id == document.id).order_by(CaseDocumentVersion.version.desc())).all()
            result.append(case_document_json(document, list(versions)))
        return result


@app.post("/api/goals/{goal_id}/documents", status_code=201)
async def create_case_document_version(goal_id: UUID, body: CaseDocumentVersionCreate) -> dict:
    require_database()
    document_type, title, content = body.document_type.strip().upper(), body.title.strip().lower(), body.content.strip()
    if not document_type or not title or not content:
        raise HTTPException(422, "Document type, title and content are required")
    allowed = {(kind, filename) for kind, filename, _ in CASE_FILE_DEFINITIONS}
    if (document_type, title) not in allowed:
        raise HTTPException(422, "Case files must be overview.md, preferences.md or call-notes.md")
    with session_scope() as session:
        goal = load_goal(session, goal_id)
        ensure_case_files(session, goal)
        document = session.scalar(select(CaseDocument).where(CaseDocument.goal_id == goal_id, CaseDocument.document_type == document_type, CaseDocument.title == title).with_for_update())
        if not document:
            document = CaseDocument(goal_id=goal_id, document_type=document_type, title=title); session.add(document); session.flush()
        latest = session.scalar(select(func.max(CaseDocumentVersion.version)).where(CaseDocumentVersion.document_id == document.id)) or 0
        version = CaseDocumentVersion(document_id=document.id, content=content, version=latest + 1, supersedes_id=document.current_version_id, document_metadata=body.metadata, created_by=body.created_by.strip() or "OPERATOR")
        session.add(version); session.flush(); document.current_version_id = version.id
        session.add(Event(goal_id=goal_id, event_type="CASE_DOCUMENT_VERSION_CREATED", source=body.created_by.strip().lower() or "operator", payload={"document_id": str(document.id), "version_id": str(version.id), "version": version.version, "document_type": document_type}, idempotency_key=f"case-document:{version.id}"))
        return case_document_json(document, [version])


@app.post("/elevenlabs/tools/get-case")
async def get_case(body: GoalRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id)
        booked = session.scalar(
            select(Appointment)
            .where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED")
            .order_by(Appointment.created_at.desc())
        )
        current_appointment = None if not booked else {
            "status": "BOOKED",
            "when": booked.slot.starts_at.isoformat(),
            "site": booked.slot.site,
            "appointment_type": booked.slot.procedure,
        }
        return {"goal_id": str(goal.id), "goal": goal.description, "status": goal.status, "blocker": goal.current_blocker, "patient_first_name": goal.referral.patient.first_name, "current_appointment": current_appointment, "allowed_topics": ["appointment", "site", "availability"]}


@app.post("/elevenlabs/tools/verify-identity")
async def verify_identity(body: IdentityVerificationRequest) -> dict:
    """Compare DOB without disclosing the value stored on the patient record."""
    require_database()
    with session_scope() as session:
        patient = load_goal(session, body.goal_id).referral.patient
        stored_date = patient.date_of_birth.date() if patient.date_of_birth else None
        return {"verified": stored_date is not None and stored_date == body.date_of_birth}


@app.post("/elevenlabs/tools/list-offered-slots")
async def offered_slots(body: GoalRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id)
        offers = session.scalars(
            select(Appointment)
            .where(Appointment.referral_id == goal.referral_id, Appointment.status == "OFFERED")
            .order_by(Appointment.created_at.desc())
        ).all()
        booked = session.scalar(
            select(Appointment)
            .where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED")
            .order_by(Appointment.created_at.desc())
        )
        slots = [{"slot_id": str(offer.slot_id), "when": offer.slot.starts_at.isoformat(), "site": offer.slot.site, "status": "OFFERED"} for offer in offers]
        current = None if not booked else {"slot_id": str(booked.slot_id), "when": booked.slot.starts_at.isoformat(), "site": booked.slot.site, "status": "BOOKED"}
        return {"goal_id": str(goal.id), "slots": slots, "current_appointment": current, "message": "One offered appointment is ready for a decision." if slots else "There is no open appointment offer for this patient."}


@app.post("/elevenlabs/tools/list-reschedule-slots")
async def reschedule_slots(body: GoalRequest) -> dict:
    """Return compatible free replacements without changing the current booking."""
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id)
        current = session.scalar(
            select(Appointment)
            .where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED")
            .order_by(Appointment.created_at.desc())
        )
        rows = session.scalars(
            select(Slot)
            .where(
                Slot.procedure == goal.referral.procedure,
                Slot.status == "AVAILABLE",
                Slot.starts_at >= datetime.now(UTC),
            )
            .order_by(Slot.starts_at)
            .limit(10)
        ).all()
        slots = [{"slot_id": str(slot.id), "when": slot.starts_at.isoformat(), "site": slot.site, "status": "AVAILABLE"} for slot in rows]
        return {
            "goal_id": str(goal.id),
            "current_appointment": None if not current else {"when": current.slot.starts_at.isoformat(), "site": current.slot.site, "status": "BOOKED"},
            "slots": slots,
            "message": f"{len(slots)} compatible replacement appointment{'s' if len(slots) != 1 else ''} available. The current booking remains in place until one is accepted.",
        }


@app.post("/elevenlabs/tools/accept-slot")
async def accept_slot(body: SlotRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id); slot = session.scalar(select(Slot).where(Slot.id == body.slot_id).with_for_update())
        event_key = f"accept:{goal.id}:{body.slot_id}"
        existing = session.scalar(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.slot_id == body.slot_id, Appointment.status == "BOOKED"))
        if existing:
            return {"accepted": True, "already_booked": True, "slot_id": str(body.slot_id), "reminder_at": goal.next_wake_at.isoformat() if goal.next_wake_at else None, "message": "Success: this appointment is booked for the patient. Do not call this tool again."}
        if not slot or slot.status not in {"AVAILABLE", "HELD"} or slot.procedure != goal.referral.procedure or slot.starts_at <= datetime.now(UTC):
            raise HTTPException(409, "Slot is no longer eligible")
        offered = session.scalar(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.slot_id == slot.id, Appointment.status == "OFFERED").with_for_update())
        previous = session.scalars(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.status == "BOOKED").with_for_update()).all()
        reminder_at = reminder_wake_at(slot.starts_at)
        slot.status = "BOOKED"; slot.held_until = None; goal.status = "WAITING"; goal.current_blocker = None; goal.next_wake_at = reminder_at
        if offered:
            offered.status = "BOOKED"
            booked_appointment = offered
        else:
            booked_appointment = Appointment(referral_id=goal.referral_id, slot_id=slot.id, status="BOOKED")
            session.add(booked_appointment)
        session.flush()
        for appointment in previous:
            if appointment.slot_id != slot.id:
                appointment.status = "RESCHEDULED"; appointment.slot.status = "AVAILABLE"
                appointment.slot.properties = {**(appointment.slot.properties or {}), "released_gap": True, "release_reason": "replacement_accepted"}
        session.add(Event(goal_id=goal.id, event_type="SLOT_ACCEPTED", source="elevenlabs", payload={"slot_id": str(slot.id), "released_slot_ids": [str(a.slot_id) for a in previous if a.slot_id != slot.id]}, idempotency_key=event_key))
        session.add(Event(goal_id=goal.id, event_type="REMINDER_SCHEDULED", source="system", payload={"appointment_id": str(booked_appointment.id), "appointment_at": slot.starts_at.isoformat(), "reminder_at": reminder_at.isoformat(), "lead_hours": REMINDER_LEAD_HOURS}, idempotency_key=f"reminder:{booked_appointment.id}"))
        session.flush()
        match_available_slots(session, released_only=True)
        return {"accepted": True, "already_booked": False, "slot_id": str(slot.id), "reminder_at": reminder_at.isoformat(), "message": "Success: the appointment is now booked for the patient. Do not call this tool again."}


@app.post("/elevenlabs/tools/reject-slot")
async def reject_slot(body: SlotRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id)
        offer = session.scalar(select(Appointment).where(Appointment.referral_id == goal.referral_id, Appointment.slot_id == body.slot_id, Appointment.status == "OFFERED").with_for_update())
        slot = session.scalar(select(Slot).where(Slot.id == body.slot_id).with_for_update())
        if offer:
            offer.status = "DECLINED"
        released = bool(slot and slot.status == "HELD")
        if released:
            slot.status, slot.held_until = "AVAILABLE", None
            slot.properties = {**(slot.properties or {}), "released_gap": True, "release_reason": "offer_declined"}
        goal.status, goal.next_wake_at = "WAITING", datetime.now(UTC)
        session.add(Event(goal_id=goal.id, event_type="SLOT_REJECTED", source="elevenlabs", payload={"slot_id": str(body.slot_id), "reason": body.reason, "offer_released": released}, idempotency_key=f"reject:{goal.id}:{body.slot_id}:{uuid4()}"))
        if released:
            session.add(Event(goal_id=goal.id, event_type="SLOT_RELEASED", source="elevenlabs", payload={"slot_id": str(body.slot_id), "reason": "earlier slot offer declined", "capacity_gap": True}, idempotency_key=f"reject-release:{offer.id if offer else uuid4()}"))
            session.flush()
            match_available_slots(session, released_only=True)
        return {"recorded": True, "offer_status": "DECLINED" if offer else "NOT_FOUND", "slot_released": released}


@app.post("/elevenlabs/tools/patient-constraint")
async def patient_constraint(body: ConstraintRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id); patient = goal.referral.patient
        patient.constraints = {**patient.constraints, body.constraint: True}
        session.add(Event(goal_id=goal.id, event_type="PATIENT_CONSTRAINT_RECORDED", source="elevenlabs", payload={"constraint": body.constraint}, idempotency_key=f"constraint:{goal.id}:{body.constraint}:{uuid4()}"))
        return {"recorded": True}


@app.post("/elevenlabs/tools/request-human")
async def request_human(body: ConstraintRequest) -> dict:
    require_database()
    with session_scope() as session:
        goal = load_goal(session, body.goal_id); goal.status = "HUMAN_REVIEW_REQUIRED"; goal.current_blocker = body.constraint
        session.add(Event(goal_id=goal.id, event_type="HUMAN_REVIEW_REQUESTED", source="elevenlabs", payload={"reason": body.constraint}, idempotency_key=f"human:{goal.id}:{uuid4()}"))
        return {"escalated": True, "state": goal.status}


@app.post("/webhooks/elevenlabs")
async def elevenlabs_webhook(request: Request, elevenlabs_signature: str | None = Header(default=None)):
    if not settings.elevenlabs_webhook_secret or not elevenlabs_signature:
        raise HTTPException(401, "Missing webhook authentication")
    from elevenlabs.client import ElevenLabs
    from elevenlabs.errors import BadRequestError
    try:
        event = ElevenLabs(api_key=settings.elevenlabs_api_key).webhooks.construct_event(rawBody=(await request.body()).decode(), sig_header=elevenlabs_signature, secret=settings.elevenlabs_webhook_secret)
    except BadRequestError:
        return JSONResponse({"error": "Invalid signature"}, status_code=401)
    if settings.database_url and event.get("type") == "post_call_transcription":
        data = event.get("data", {}); variables = data.get("conversation_initiation_client_data", {}).get("dynamic_variables", {}); goal_id = variables.get("goal_id")
        if goal_id:
            with session_scope() as session:
                goal = load_goal(session, UUID(goal_id)); conversation_id = data.get("conversation_id")
                communication = session.scalar(select(Communication).where(Communication.external_id == conversation_id))
                already_completed = communication is not None and communication.outcome != "QUEUED"
                if not already_completed:
                    analysis = data.get("analysis", {})
                    summary = analysis.get("transcript_summary") or "Patient call completed"
                    success_value = analysis.get("call_successful")
                    raw_outcome = str(analysis.get("call_outcome") or success_value or data.get("status") or "").lower()
                    outcome = ("ESCALATED" if "escalat" in raw_outcome or "human" in raw_outcome else "DECLINED" if "declin" in raw_outcome or "reject" in raw_outcome else "NO_ANSWER" if "no_answer" in raw_outcome or "unanswered" in raw_outcome else "FAILED" if success_value is False or "fail" in raw_outcome or "error" in raw_outcome else "ANSWERED")
                    purpose = str(variables.get("purpose") or (communication.purpose if communication else "FOLLOW_UP")).upper()
                    if purpose not in CALL_PURPOSES: purpose = "FOLLOW_UP"
                    code = str(variables.get("preferred_language") or (communication.language if communication else language_code(goal.referral.patient.preferred_language)))
                    goal.current_summary = summary
                    if goal.status not in {"COMPLETED", "HUMAN_REVIEW_REQUIRED"}:
                        goal.status = "WAITING"
                        goal.next_wake_at = datetime.now(UTC)
                    if communication:
                        communication.summary, communication.transcript, communication.purpose, communication.outcome, communication.language = summary, str(data.get("transcript", "")), purpose, outcome, code
                    else:
                        communication = Communication(goal_id=goal.id, channel="VOICE", direction="OUTBOUND", external_id=conversation_id, purpose=purpose, outcome=outcome, language=code, summary=summary, transcript=str(data.get("transcript", "")))
                        session.add(communication)
                    browser_action = session.scalar(
                        select(Action)
                        .where(Action.goal_id == goal.id, Action.status == "IN_PROGRESS", Action.action_type.in_(("CALL_PATIENT", "EARLIER_SLOT_OFFER")))
                        .order_by(Action.created_at.desc())
                    )
                    if browser_action and (browser_action.payload or {}).get("transport") == "demo_browser_receiver":
                        action_outcome = "COMPLETED" if outcome == "ANSWERED" else "DECLINED" if outcome == "DECLINED" else "TIMED_OUT" if outcome == "NO_ANSWER" else "FAILED"
                        if _terminalize_browser_action(browser_action, action_outcome):
                            _release_unaccepted_offers_on_call_end(session, goal, browser_action, action_outcome)
                        browser_action.result = {**(browser_action.result or {}), "provider_outcome": outcome, "conversation_id": conversation_id}
                    note = create_note(session, patient_id=goal.referral.patient_id, referral_id=goal.referral_id, goal_id=goal.id, category="CALL_SUMMARY", text=summary, language=goal.referral.patient.preferred_language, source="ELEVENLABS")
                    session.add_all([
                        Event(goal_id=goal.id, event_type="VOICE_CALL_COMPLETED", source="elevenlabs", payload={"conversation_id": conversation_id, "purpose": purpose, "outcome": outcome, "summary": summary, "language": code}, idempotency_key=f"elevenlabs:{conversation_id}"),
                        Event(goal_id=goal.id, event_type="CASE_NOTE_VERSION_CREATED", source="elevenlabs", payload={"category": "CALL_SUMMARY", "note_id": str(note.id), "version": 1, "conversation_id": conversation_id}, idempotency_key=f"elevenlabs-note:{conversation_id}"),
                    ])
                    # Reconcile released capacity immediately after the durable
                    # call outcome is stored. Webhook retries skip this block via
                    # the conversation-id guard above; the periodic matcher is
                    # only a recovery path.
                    session.flush()
                    match_available_slots(session, limit=1)
    return {"accepted": True, "event": event.get("type", "unknown")}
