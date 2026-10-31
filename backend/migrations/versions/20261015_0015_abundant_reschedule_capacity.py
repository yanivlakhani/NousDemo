"""Add four months of weekday MRI rescheduling capacity.

Revision ID: 20261015_0015
Revises: 20261015_0014
"""

from alembic import op


revision = "20261015_0015"
down_revision = "20261015_0014"
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
          gen_random_uuid(),
          'demo-reschedule:' || to_char(day_at, 'YYYYMMDD') || ':' || hour_value::text,
          appointment_types.id,
          'nous scheduling',
          CASE WHEN hour_value = 13 THEN 'Main site' ELSE 'North Imaging Centre' END,
          appointment_types.name,
          day_at + make_interval(hours => hour_value),
          120,
          jsonb_build_object(
            'source', 'abundant_demo_reschedule_capacity',
            'reschedule_only', true
          ),
          'AVAILABLE'
        FROM appointment_types
        CROSS JOIN generate_series(
          date_trunc('day', now()) + interval '1 day',
          date_trunc('day', now()) + interval '120 days',
          interval '1 day'
        ) AS day_at
        CROSS JOIN (VALUES (10), (13), (15)) AS hours(hour_value)
        WHERE appointment_types.code = 'MRI'
          AND extract(isodow FROM day_at) BETWEEN 1 AND 5
          AND NOT EXISTS (
            SELECT 1 FROM slots
            WHERE slots.external_ref = 'demo-reschedule:' || to_char(day_at, 'YYYYMMDD') || ':' || hour_value::text
          )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM slots WHERE properties->>'source' = 'abundant_demo_reschedule_capacity'")
