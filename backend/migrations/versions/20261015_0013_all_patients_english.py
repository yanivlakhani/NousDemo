"""Set every current patient to English for the demo.

Revision ID: 20261015_0013
Revises: 20261015_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_0013"
down_revision = "20261015_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE patients SET preferred_language = 'English'")
    op.execute(
        sa.text(
            """
            UPDATE actions
            SET payload = jsonb_set(payload, '{preferred_language}', '"English"'::jsonb, true)
            WHERE status IN ('QUEUED', 'PROPOSED', 'RINGING_BROWSER', 'IN_PROGRESS')
              AND action_type IN ('CALL_PATIENT', 'EARLIER_SLOT_OFFER')
            """
        )
    )


def downgrade() -> None:
    # The previous individual preferences cannot be reconstructed safely.
    pass
