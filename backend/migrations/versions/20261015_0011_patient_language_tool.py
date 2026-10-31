"""publish caseworker profile-language tool"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_0011"
down_revision = "20261015_0010"
branch_labels = None
depends_on = None

CASEWORKER_V3 = "10000000-0000-0000-0000-000000000103"
CASEWORKER_V2 = "10000000-0000-0000-0000-000000000102"


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO agent_spec_versions
          (id, definition_id, version, name, role, instructions, tool_policy, model, status)
        SELECT CAST(:version_id AS uuid), definition_id, 3, name, role,
               instructions || ' When a patient states or corrects their preferred language, use set_preferred_language so future calls use it.',
               jsonb_set(tool_policy, '{allowed}', (tool_policy->'allowed') || '["set_preferred_language"]'::jsonb),
               model, 'PUBLISHED'
        FROM agent_spec_versions WHERE id = CAST(:previous_id AS uuid)
        ON CONFLICT (definition_id, version) DO NOTHING
    """).bindparams(version_id=CASEWORKER_V3, previous_id=CASEWORKER_V2))
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'caseworker'").bindparams(version=CASEWORKER_V3))


def downgrade() -> None:
    op.execute(sa.text("UPDATE agent_definitions SET active_version_id = CAST(:version AS uuid) WHERE key = 'caseworker'").bindparams(version=CASEWORKER_V2))
