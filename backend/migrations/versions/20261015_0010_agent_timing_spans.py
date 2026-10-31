"""record real agent and tool-call timings"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0010"
down_revision = "20261015_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_steps", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_steps", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("agent_tool_calls", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_tool_calls", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_tool_calls", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_tool_calls", "duration_ms")
    op.drop_column("agent_tool_calls", "completed_at")
    op.drop_column("agent_tool_calls", "started_at")
    op.drop_column("agent_steps", "duration_ms")
    op.drop_column("agent_steps", "completed_at")
