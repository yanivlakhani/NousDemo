"""backfill and require patient dates of birth"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0012"
down_revision = "20261015_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Stable, varied demo-safe values keep identity verification demonstrable.
    # The final fallback covers any externally created legacy row as well.
    op.execute("""
        UPDATE patients SET date_of_birth = CASE external_ref
          WHEN 'NOU-1001' THEN TIMESTAMPTZ '1984-02-14 00:00:00+00'
          WHEN 'NOU-1002' THEN TIMESTAMPTZ '1978-07-23 00:00:00+00'
          WHEN 'NOU-1003' THEN TIMESTAMPTZ '1991-11-05 00:00:00+00'
          WHEN 'NOU-1004' THEN TIMESTAMPTZ '1969-03-18 00:00:00+00'
          WHEN 'NOU-1005' THEN TIMESTAMPTZ '1987-09-30 00:00:00+00'
          WHEN 'NOU-1006' THEN TIMESTAMPTZ '1975-12-08 00:00:00+00'
          WHEN 'NOU-1007' THEN TIMESTAMPTZ '1982-06-21 00:00:00+00'
          WHEN 'NOU-1008' THEN TIMESTAMPTZ '1990-01-27 00:00:00+00'
          WHEN 'NOU-1009' THEN TIMESTAMPTZ '1972-10-12 00:00:00+00'
          WHEN 'NOU-1010' THEN TIMESTAMPTZ '1986-04-03 00:00:00+00'
          WHEN 'NOU-1011' THEN TIMESTAMPTZ '1993-08-16 00:00:00+00'
          WHEN 'NOU-1012' THEN TIMESTAMPTZ '1966-05-29 00:00:00+00'
          ELSE TIMESTAMPTZ '1975-04-17 00:00:00+00'
        END
        WHERE date_of_birth IS NULL
    """)
    op.alter_column("patients", "date_of_birth", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    op.alter_column("patients", "date_of_birth", existing_type=sa.DateTime(timezone=True), nullable=True)
