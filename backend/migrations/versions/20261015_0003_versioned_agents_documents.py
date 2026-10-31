"""versioned agent specifications and case documents"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261015_0003"
down_revision = "20261015_0002"
branch_labels = None
depends_on = None

CASEWORKER_DEFINITION = "10000000-0000-0000-0000-000000000001"
CASEWORKER_VERSION = "10000000-0000-0000-0000-000000000101"
OVERSEER_DEFINITION = "10000000-0000-0000-0000-000000000002"
OVERSEER_VERSION = "10000000-0000-0000-0000-000000000201"


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False, unique=True),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_definitions_key", "agent_definitions", ["key"], unique=True)
    op.create_table(
        "agent_spec_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("definition_id", sa.Uuid(), sa.ForeignKey("agent_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("tool_policy", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("definition_id", "version", name="uq_agent_spec_definition_version"),
    )
    op.create_index("ix_agent_spec_versions_definition_id", "agent_spec_versions", ["definition_id"])
    op.create_index("ix_agent_spec_versions_role", "agent_spec_versions", ["role"])
    op.create_index("ix_agent_spec_versions_status", "agent_spec_versions", ["status"])
    op.create_foreign_key("fk_agent_definitions_active_version", "agent_definitions", "agent_spec_versions", ["active_version_id"], ["id"], ondelete="RESTRICT")

    op.execute(sa.text("""
        INSERT INTO agent_definitions (id, key) VALUES
          (CAST(:caseworker_definition AS uuid), 'caseworker'), (CAST(:overseer_definition AS uuid), 'overseer')
        ON CONFLICT (key) DO NOTHING
    """).bindparams(caseworker_definition=CASEWORKER_DEFINITION, overseer_definition=OVERSEER_DEFINITION))
    op.execute(sa.text("""
        INSERT INTO agent_spec_versions
          (id, definition_id, version, name, role, instructions, tool_policy, model, status)
        VALUES
          (CAST(:caseworker_version AS uuid), CAST(:caseworker_definition AS uuid), 1, 'Nous Caseworker', 'CASEWORKER',
           'Manage one patient pathway over time. Read durable case context before acting; take one bounded administrative step; never provide clinical advice or alter clinical priority; never release an existing booking until its replacement is accepted; record the outcome and arrange the next wake.',
           CAST(:caseworker_tools AS jsonb), 'claude-haiku-4-5-20251001', 'PUBLISHED'),
          (CAST(:overseer_version AS uuid), CAST(:overseer_definition AS uuid), 1, 'Nous Overseer', 'OVERSEER',
           'Monitor pathway workload, stalled goals and capacity. Prioritise deterministic policy checks, surface exceptions to operators, and delegate patient-specific work to caseworkers. Do not provide clinical advice or alter clinical priority.',
           CAST(:overseer_tools AS jsonb), 'claude-haiku-4-5-20251001', 'PUBLISHED')
        ON CONFLICT (definition_id, version) DO NOTHING
    """).bindparams(
        caseworker_version=CASEWORKER_VERSION, caseworker_definition=CASEWORKER_DEFINITION,
        overseer_version=OVERSEER_VERSION, overseer_definition=OVERSEER_DEFINITION,
        caseworker_tools='{"allowed":["read_case_notes","read_case_documents","write_case_note","write_case_document","search_slots","offer_slot","queue_patient_call","wait_until","request_human","complete_goal","end_step"],"max_turns":6,"max_tool_calls":8}',
        overseer_tools='{"allowed":["inspect_goals","inspect_capacity","wake_caseworker","request_human","end_step"],"max_turns":6,"max_tool_calls":8}',
    ))
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'caseworker'").bindparams(version=CASEWORKER_VERSION))
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'overseer'").bindparams(version=OVERSEER_VERSION))

    op.execute("""
      CREATE FUNCTION reject_agent_spec_mutation() RETURNS trigger AS $$
      BEGIN RAISE EXCEPTION 'agent specification versions are immutable'; END;
      $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER agent_spec_versions_immutable BEFORE UPDATE OR DELETE ON agent_spec_versions FOR EACH ROW EXECUTE FUNCTION reject_agent_spec_mutation()")

    op.add_column("agent_steps", sa.Column("agent_spec_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_agent_steps_spec_version", "agent_steps", "agent_spec_versions", ["agent_spec_version_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_agent_steps_agent_spec_version_id", "agent_steps", ["agent_spec_version_id"])

    op.create_table(
        "case_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("goal_id", sa.Uuid(), sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("goal_id", "document_type", "title", name="uq_case_document_identity"),
    )
    op.create_index("ix_case_documents_goal_id", "case_documents", ["goal_id"])
    op.create_index("ix_case_documents_document_type", "case_documents", ["document_type"])
    op.create_index("ix_case_documents_created_at", "case_documents", ["created_at"])
    op.create_table(
        "case_document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("case_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("case_document_versions.id", ondelete="RESTRICT")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("document_id", "version", name="uq_case_document_version"),
    )
    op.create_index("ix_case_document_versions_document_id", "case_document_versions", ["document_id"])
    op.create_index("ix_case_document_versions_created_at", "case_document_versions", ["created_at"])
    op.create_foreign_key("fk_case_documents_current_version", "case_documents", "case_document_versions", ["current_version_id"], ["id"], ondelete="RESTRICT")
    op.execute("""
      CREATE TRIGGER case_document_versions_immutable BEFORE UPDATE OR DELETE ON case_document_versions
      FOR EACH ROW EXECUTE FUNCTION reject_agent_spec_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER case_document_versions_immutable ON case_document_versions")
    op.drop_constraint("fk_case_documents_current_version", "case_documents", type_="foreignkey")
    op.drop_table("case_document_versions")
    op.drop_table("case_documents")
    op.drop_index("ix_agent_steps_agent_spec_version_id", table_name="agent_steps")
    op.drop_constraint("fk_agent_steps_spec_version", "agent_steps", type_="foreignkey")
    op.drop_column("agent_steps", "agent_spec_version_id")
    op.execute("DROP TRIGGER agent_spec_versions_immutable ON agent_spec_versions")
    op.execute("DROP FUNCTION reject_agent_spec_mutation")
    op.drop_constraint("fk_agent_definitions_active_version", "agent_definitions", type_="foreignkey")
    op.drop_table("agent_spec_versions")
    op.drop_table("agent_definitions")
