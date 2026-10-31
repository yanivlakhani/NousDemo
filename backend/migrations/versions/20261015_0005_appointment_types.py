"""minimal appointment type configuration"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0005"
down_revision = "20261015_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointment_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("preparation_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_appointment_types_code", "appointment_types", ["code"], unique=True)
    op.create_index("ix_appointment_types_is_active", "appointment_types", ["is_active"])
    op.execute("""
      INSERT INTO appointment_types (id, code, name, default_duration_minutes, preparation_note, is_active)
      VALUES ('20000000-0000-0000-0000-000000000001'::uuid, 'MRI', 'MRI', 30, NULL, true)
      ON CONFLICT (code) DO NOTHING
    """)
    for table in ("referrals", "slots"):
        op.add_column(table, sa.Column("appointment_type_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(f"fk_{table}_appointment_type", table, "appointment_types", ["appointment_type_id"], ["id"], ondelete="RESTRICT")
        op.create_index(f"ix_{table}_appointment_type_id", table, ["appointment_type_id"])


def downgrade() -> None:
    for table in ("slots", "referrals"):
        op.drop_index(f"ix_{table}_appointment_type_id", table_name=table)
        op.drop_constraint(f"fk_{table}_appointment_type", table, type_="foreignkey")
        op.drop_column(table, "appointment_type_id")
    op.drop_table("appointment_types")
