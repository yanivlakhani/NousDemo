"""persist case-note language and seed physiotherapy appointment type"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_0006"
down_revision = "20261015_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable first so existing notes can be backfilled from their patient.
    op.add_column("case_notes", sa.Column("language", sa.String(80), nullable=True))
    op.execute("""
      UPDATE case_notes AS note
      SET language = patient.preferred_language
      FROM patients AS patient
      WHERE patient.id = note.patient_id
    """)
    # Patient language is already required. English is only a defensive fallback
    # for legacy rows whose patient may have been imported outside the domain schema.
    op.execute("UPDATE case_notes SET language = 'English' WHERE language IS NULL")
    op.alter_column("case_notes", "language", existing_type=sa.String(80), nullable=False)

    op.execute("""
      INSERT INTO appointment_types
        (id, code, name, default_duration_minutes, preparation_note, is_active)
      VALUES
        ('20000000-0000-0000-0000-000000000002'::uuid, 'PHYSIO', 'Physiotherapy', 45, NULL, true)
      ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
      DELETE FROM appointment_types
      WHERE id = '20000000-0000-0000-0000-000000000002'::uuid
        AND code = 'PHYSIO'
    """)
    op.drop_column("case_notes", "language")
