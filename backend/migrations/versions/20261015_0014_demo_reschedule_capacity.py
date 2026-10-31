"""Add explicit next-week MRI capacity for the voice reschedule demo.

Revision ID: 20261015_0014
Revises: 20261015_0013
"""

from alembic import op


revision = "20261015_0014"
down_revision = "20261015_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO slots (
          id, external_ref, appointment_type_id, provider_org, site, procedure,
          starts_at, duration_minutes, properties, status
        )
        SELECT
          gen_random_uuid(), candidate.external_ref, appointment_types.id,
          'nous scheduling', 'Main site', appointment_types.name,
          candidate.starts_at, 120,
          '{"source":"demo_voice_reschedule"}'::jsonb, 'AVAILABLE'
        FROM appointment_types
        CROSS JOIN (VALUES
          ('demo-asha-next-week-tuesday', TIMESTAMPTZ '2026-10-20 13:00:00+00'),
          ('demo-asha-next-week-thursday', TIMESTAMPTZ '2026-10-22 15:00:00+00')
        ) AS candidate(external_ref, starts_at)
        WHERE appointment_types.code = 'MRI'
          AND NOT EXISTS (SELECT 1 FROM slots WHERE slots.external_ref = candidate.external_ref)
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM slots WHERE external_ref IN ('demo-asha-next-week-tuesday', 'demo-asha-next-week-thursday')")
