"""initial pathway domain schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261015_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A Lovable prototype used a different schema with overlapping table names.
    # Preserve it under explicit legacy names before creating the nous domain.
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    patient_columns = {column["name"] for column in inspector.get_columns("patients")} if "patients" in existing else set()
    if "patients" in existing and "external_ref" not in patient_columns:
        for table in ("patients", "appointments", "calls", "slot_offers", "waitlist"):
            if table in existing and f"legacy_{table}" not in existing:
                op.rename_table(table, f"legacy_{table}")

    op.create_table("patients",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("external_ref", sa.String(64), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False), sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("date_of_birth", sa.DateTime(timezone=True)), sa.Column("phone", sa.String(32)), sa.Column("email", sa.String(255)),
        sa.Column("preferred_contact_method", sa.String(20), nullable=False), sa.Column("preferred_language", sa.String(80), nullable=False),
        sa.Column("administrative_notes", sa.Text()), sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("external_ref"))
    op.create_index("ix_patients_external_ref", "patients", ["external_ref"])
    op.create_table("slots",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("external_ref", sa.String(100), unique=True),
        sa.Column("provider_org", sa.String(160), nullable=False), sa.Column("site", sa.String(160), nullable=False),
        sa.Column("procedure", sa.String(160), nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False), sa.Column("properties", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("held_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_slots_procedure", "slots", ["procedure"]); op.create_index("ix_slots_starts_at", "slots", ["starts_at"]); op.create_index("ix_slots_status", "slots", ["status"])
    op.create_table("referrals",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pathway_type", sa.String(40), nullable=False), sa.Column("procedure", sa.String(160), nullable=False),
        sa.Column("referring_org", sa.String(160)), sa.Column("provider_org", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False), sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_referrals_patient_id", "referrals", ["patient_id"]); op.create_index("ix_referrals_pathway_type", "referrals", ["pathway_type"]); op.create_index("ix_referrals_status", "referrals", ["status"])
    op.create_table("goals",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("referral_id", sa.Uuid(), sa.ForeignKey("referrals.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("goal_type", sa.String(80), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("success_criteria", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False), sa.Column("current_summary", sa.Text()), sa.Column("current_blocker", sa.Text()),
        sa.Column("next_wake_at", sa.DateTime(timezone=True)), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_goals_status", "goals", ["status"]); op.create_index("ix_goals_next_wake_at", "goals", ["next_wake_at"])
    op.create_table("appointments",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("referral_id", sa.Uuid(), sa.ForeignKey("referrals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slot_id", sa.Uuid(), sa.ForeignKey("slots.id", ondelete="RESTRICT"), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slot_id", "status", name="uq_slot_active_status"))
    op.create_index("ix_appointments_referral_id", "appointments", ["referral_id"]); op.create_index("ix_appointments_slot_id", "appointments", ["slot_id"]); op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_table("events",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE")),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("source", sa.String(80), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_events_goal_id", "events", ["goal_id"]); op.create_index("ix_events_event_type", "events", ["event_type"]); op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_table("actions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False), sa.Column("result", postgresql.JSONB()),
        sa.Column("idempotency_key", sa.String(200), unique=True, nullable=False), sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_actions_goal_id", "actions", ["goal_id"]); op.create_index("ix_actions_action_type", "actions", ["action_type"]); op.create_index("ix_actions_status", "actions", ["status"])
    op.create_table("communications",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False), sa.Column("direction", sa.String(20), nullable=False), sa.Column("external_id", sa.String(200), unique=True),
        sa.Column("summary", sa.Text()), sa.Column("transcript", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_communications_goal_id", "communications", ["goal_id"]); op.create_index("ix_communications_created_at", "communications", ["created_at"])
    op.create_table("goal_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_version", sa.Integer(), nullable=False), sa.Column("observation", postgresql.JSONB(), nullable=False), sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("proposed_action", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_goal_decisions_goal_id", "goal_decisions", ["goal_id"]); op.create_index("ix_goal_decisions_goal_version", "goal_decisions", ["goal_id", "goal_version"], unique=True)


def downgrade() -> None:
    for table in ("goal_decisions", "communications", "actions", "events", "appointments", "goals", "referrals", "slots", "patients"):
        op.drop_table(table)
