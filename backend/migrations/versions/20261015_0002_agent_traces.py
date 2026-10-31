"""case notes and agent execution traces"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261015_0002"
down_revision = "20261015_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("case_notes", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False), sa.Column("referral_id", sa.Uuid(), sa.ForeignKey("referrals.id", ondelete="CASCADE"), nullable=False), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE")), sa.Column("category", sa.String(40), nullable=False), sa.Column("text", sa.Text(), nullable=False), sa.Column("source", sa.String(40), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    for column in ("patient_id", "referral_id", "goal_id", "created_at"): op.create_index(f"ix_case_notes_{column}", "case_notes", [column])
    op.create_table("agent_steps", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False), sa.Column("mode", sa.String(24), nullable=False), sa.Column("model", sa.String(100)), sa.Column("fallback", sa.Boolean(), nullable=False), sa.Column("stop_reason", sa.String(40)), sa.Column("decision", sa.String(500)), sa.Column("error", sa.Text()), sa.Column("context", postgresql.JSONB(), nullable=False), sa.Column("input_tokens", sa.Integer(), nullable=False), sa.Column("output_tokens", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_agent_steps_goal_id", "agent_steps", ["goal_id"]); op.create_index("ix_agent_steps_created_at", "agent_steps", ["created_at"])
    op.create_table("agent_tool_calls", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("step_id", sa.Uuid(), sa.ForeignKey("agent_steps.id", ondelete="CASCADE"), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("tool_name", sa.String(80), nullable=False), sa.Column("tool_input", postgresql.JSONB(), nullable=False), sa.Column("result_text", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False))
    op.create_index("ix_agent_tool_calls_step_id", "agent_tool_calls", ["step_id"])


def downgrade() -> None:
    op.drop_table("agent_tool_calls"); op.drop_table("agent_steps"); op.drop_table("case_notes")
