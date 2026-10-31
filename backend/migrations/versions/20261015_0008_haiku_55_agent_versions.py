"""publish Haiku 5.5 agent specification versions"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0008"
down_revision = "20261015_0007"
branch_labels = None
depends_on = None

CASEWORKER_V2 = "10000000-0000-0000-0000-000000000102"
OVERSEER_V2 = "10000000-0000-0000-0000-000000000202"


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO agent_spec_versions
          (id, definition_id, version, name, role, instructions, tool_policy, model, status)
        SELECT CAST(:version_id AS uuid), definition_id, 2, name, role, instructions,
               tool_policy, 'claude-haiku-5-5', 'PUBLISHED'
        FROM agent_spec_versions
        WHERE id = CAST(:previous_id AS uuid)
        ON CONFLICT (definition_id, version) DO NOTHING
    """).bindparams(version_id=CASEWORKER_V2, previous_id="10000000-0000-0000-0000-000000000101"))
    op.execute(sa.text("""
        INSERT INTO agent_spec_versions
          (id, definition_id, version, name, role, instructions, tool_policy, model, status)
        SELECT CAST(:version_id AS uuid), definition_id, 2, name, role, instructions,
               tool_policy, 'claude-haiku-5-5', 'PUBLISHED'
        FROM agent_spec_versions
        WHERE id = CAST(:previous_id AS uuid)
        ON CONFLICT (definition_id, version) DO NOTHING
    """).bindparams(version_id=OVERSEER_V2, previous_id="10000000-0000-0000-0000-000000000201"))
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'caseworker'").bindparams(version=CASEWORKER_V2))
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'overseer'").bindparams(version=OVERSEER_V2))


def downgrade() -> None:
    # Agent specification history is deliberately immutable. Rollback reactivates
    # v1 but retains v2 so existing traces always retain their referenced spec.
    op.execute("UPDATE agent_definitions SET active_version_id = '10000000-0000-0000-0000-000000000101' WHERE key = 'caseworker'")
    op.execute("UPDATE agent_definitions SET active_version_id = '10000000-0000-0000-0000-000000000201' WHERE key = 'overseer'")
