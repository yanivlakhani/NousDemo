"""version case notes and type call records"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0007"
down_revision = "20261015_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("communications", sa.Column("purpose", sa.String(30), server_default="REMINDER", nullable=False))
    op.add_column("communications", sa.Column("outcome", sa.String(30), server_default="QUEUED", nullable=False))
    op.add_column("communications", sa.Column("language", sa.String(20), server_default="en", nullable=False))
    op.create_index("ix_communications_purpose", "communications", ["purpose"])
    op.create_index("ix_communications_outcome", "communications", ["outcome"])
    op.create_check_constraint("ck_communications_purpose", "communications", "purpose IN ('REMINDER','RESCHEDULE','EARLIER_SLOT_OFFER','FOLLOW_UP')")
    op.create_check_constraint("ck_communications_outcome", "communications", "outcome IN ('QUEUED','ANSWERED','DECLINED','NO_ANSWER','FAILED','ESCALATED')")

    op.create_table("case_note_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("case_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("category", sa.String(40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("language", sa.String(80), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("case_note_versions.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("note_id", "version", name="uq_case_note_version"))
    op.create_index("ix_case_note_versions_note_id", "case_note_versions", ["note_id"])
    op.create_index("ix_case_note_versions_created_at", "case_note_versions", ["created_at"])
    op.execute("""INSERT INTO case_note_versions (id, note_id, version, category, text, language, source, created_at)
                  SELECT id, id, 1, category, text, language, source, created_at FROM case_notes""")
    op.add_column("case_notes", sa.Column("current_version_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE case_notes SET current_version_id = id")
    op.create_foreign_key("fk_case_notes_current_version", "case_notes", "case_note_versions", ["current_version_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint("fk_case_notes_current_version", "case_notes", type_="foreignkey")
    op.drop_column("case_notes", "current_version_id")
    op.drop_table("case_note_versions")
    op.drop_constraint("ck_communications_outcome", "communications", type_="check")
    op.drop_constraint("ck_communications_purpose", "communications", type_="check")
    op.drop_index("ix_communications_outcome", table_name="communications")
    op.drop_index("ix_communications_purpose", table_name="communications")
    op.drop_column("communications", "language")
    op.drop_column("communications", "outcome")
    op.drop_column("communications", "purpose")
