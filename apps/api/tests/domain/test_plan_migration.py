from uuid import uuid4

from sqlalchemy import text

from alembic import command
from grounded_tutor.alembic_config import get_alembic_config
from grounded_tutor.config import Settings
from grounded_tutor.db import create_database_engine


def test_plan_migration_preserves_existing_concept_children_and_roundtrips(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'migration.db'}")
    config = get_alembic_config(settings)
    command.upgrade(config, "0009_diagnostics")
    engine = create_database_engine(settings)
    ids = {name: uuid4().hex for name in ("w", "p", "c", "a", "attempt")}
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO workspaces(id,title,dataset_id) VALUES(:w,'Legacy','legacy')"), ids
        )
        conn.execute(
            text("INSERT INTO learning_plans(id,workspace_id,goal) VALUES(:p,:w,'Learn')"), ids
        )
        conn.execute(
            text(
                "INSERT INTO concepts(id,workspace_id,plan_id,\"order\",title,objective,evidence_refs) VALUES(:c,:w,:p,1,'Mean','Explain','[]')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO activity_states(workspace_id,active_mode,active_concept_id) VALUES(:w,'LEARN',:c)"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO assessments(id,workspace_id,concept_id,kind,purpose,prompt,options,answer_key,evidence_refs,feedback_blocks,citations) VALUES(:a,:w,:c,'structured_short','immediate_check','Mean?','[]','[\"sum\"]','[]','[]','[]')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO attempts(id,assessment_id,response,result,status) VALUES(:attempt,:a,'sum','understood','completed')"
            ),
            ids,
        )
    try:
        for target in ("head", "0009_diagnostics", "head"):
            if target == "head":
                command.upgrade(config, target)
                command.check(config)
            else:
                command.downgrade(config, target)
            with engine.connect() as conn:
                assert not conn.execute(text("PRAGMA foreign_key_check")).fetchall()
                assert (
                    conn.execute(text("SELECT result FROM attempts")).scalar_one() == "understood"
                )
                assert (
                    conn.execute(text("SELECT active_concept_id FROM activity_states")).scalar_one()
                    == ids["c"]
                )
                if target == "head":
                    assert (
                        conn.execute(text("SELECT check_kind FROM concepts")).scalar_one()
                        == "single_choice"
                    )
    finally:
        engine.dispose()
