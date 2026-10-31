"""replace surplus generated capacity with the scarce demo profile"""

from alembic import op

revision = "20261015_0009"
down_revision = "20261015_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only unbooked capacity created by the deterministic generator is removed.
    # Held, booked, manually created, and released-slot records are preserved.
    op.execute("""
        DELETE FROM slots
        WHERE status = 'AVAILABLE'
          AND properties ->> 'source' = 'automatic_weekday_capacity'
    """)


def downgrade() -> None:
    # The scheduler safely regenerates available capacity; no patient record or
    # booking is deleted by this migration, so there is nothing durable to undo.
    pass
