"""agent step causality and repeat metadata"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0004"
down_revision = "20261015_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_steps", sa.Column("parent_step_id", sa.Uuid(), nullable=True))
    op.add_column("agent_steps", sa.Column("sequence", sa.Integer(), server_default="1", nullable=False))
    op.add_column("agent_steps", sa.Column("retry_attempt", sa.Integer(), server_default="0", nullable=False))
    op.add_column("agent_steps", sa.Column("wake_reason", sa.String(300), nullable=True))
    op.add_column("agent_steps", sa.Column("scheduled_next_wake", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_steps", sa.Column("outcome", sa.String(30), server_default="COMPLETED", nullable=False))
    op.add_column("agent_steps", sa.Column("tool_call_count", sa.Integer(), server_default="0", nullable=False))
    op.create_foreign_key("fk_agent_steps_parent_step", "agent_steps", "agent_steps", ["parent_step_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_agent_steps_parent_step_id", "agent_steps", ["parent_step_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_steps_parent_step_id", table_name="agent_steps")
    op.drop_constraint("fk_agent_steps_parent_step", "agent_steps", type_="foreignkey")
    for column in ("tool_call_count", "outcome", "scheduled_next_wake", "wake_reason", "retry_attempt", "sequence", "parent_step_id"):
        op.drop_column("agent_steps", column)
