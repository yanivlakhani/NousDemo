"""Modal deployment for the nous UI and FastAPI service.

Local preview: modal serve modal_app.py
Production:    modal deploy modal_app.py
"""

from pathlib import Path

import modal


ROOT = Path(__file__).parent
DEMO_CAPACITY_ENV = {
    "DEMO_CAPACITY_SLOT_MINUTES": "120",
    "DEMO_CAPACITY_HORIZON_DAYS": "2",
}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi==0.115.12",
        "httpx==0.28.1",
        "pydantic-settings==2.8.1",
        "elevenlabs>=2.0,<3",
        "sqlalchemy>=2.0,<3",
        "psycopg[binary]>=3.2,<4",
        "alembic>=1.14,<2",
    )
    .add_local_dir(ROOT / "backend", remote_path="/root/backend")
    .add_local_dir(ROOT / "dist", remote_path="/root/frontend")
)

app = modal.App("nous")
database_secret = modal.Secret.from_name("pathway-database", required_keys=["DATABASE_URL"])
elevenlabs_secret = modal.Secret.from_name(
    "pathway-elevenlabs",
    required_keys=["ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID"],
)
anthropic_secret = modal.Secret.from_name(
    "nous-anthropic", required_keys=["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"]
)


@app.function(image=image, secrets=[database_secret], timeout=120)
def migrate():
    """Apply committed Alembic migrations before a production deployment."""
    import subprocess

    subprocess.run(["alembic", "-c", "/root/backend/alembic.ini", "upgrade", "head"], cwd="/root/backend", check=True)


@app.function(image=image, secrets=[database_secret], timeout=120)
def audit_demo():
    """Read-only inventory and invariant check for DEMO-* records."""
    import json
    import sys
    sys.path.insert(0, "/root/backend")
    from app.database import read_session_scope
    from app.demo_cleanup import audit_demo_state
    with read_session_scope() as session:
        result = audit_demo_state(session)
        print(json.dumps({
            "counts": result["counts"], "status_counts": result["status_counts"],
            "violations": result["violations"], "valid": result["valid"],
            "patients": result["patients"], "appointments": result["records"]["appointments"],
        }, indent=2, sort_keys=True))
        return result


@app.function(image=image, secrets=[database_secret], timeout=120)
def preview_demo_cleanup():
    """Exercise cleanup against live data, validate it, and always roll back."""
    import json
    import sys
    sys.path.insert(0, "/root/backend")
    from sqlalchemy.orm import Session
    from app.database import get_engine
    from app.demo_cleanup import audit_demo_state, cleanup_demo_state
    with Session(get_engine(), expire_on_commit=False) as session:
        before = audit_demo_state(session)
        changes = cleanup_demo_state(session)
        session.flush()
        after = audit_demo_state(session)
        session.rollback()
    result = {"committed": False, "before": before, "changes": changes, "after": after}
    print(json.dumps({
        "committed": False, "before_counts": before["counts"],
        "before_status_counts": before["status_counts"], "before_violations": before["violations"],
        "changes": changes, "after_counts": after["counts"],
        "after_status_counts": after["status_counts"], "after_violations": after["violations"],
        "remaining_patients": after["patients"], "remaining_appointments": after["records"]["appointments"],
    }, indent=2, sort_keys=True))
    return result


@app.function(image=image, secrets=[database_secret], timeout=120)
def cleanup_demo():
    """Idempotently reset and validate only DEMO-* records."""
    import json
    import sys
    sys.path.insert(0, "/root/backend")
    from sqlalchemy.orm import Session
    from app.database import get_engine
    from app.demo_cleanup import audit_demo_state, cleanup_demo_state
    with Session(get_engine(), expire_on_commit=False) as session:
        before = audit_demo_state(session)
        changes = cleanup_demo_state(session)
        session.flush()
        after = audit_demo_state(session)
        if not after["valid"]:
            session.rollback()
            raise RuntimeError(f"DEMO cleanup validation failed; rolled back: {after['violations']}")
        session.commit()
    result = {"committed": True, "before": before, "changes": changes, "after": after}
    print(json.dumps({
        "committed": True, "before_counts": before["counts"],
        "before_status_counts": before["status_counts"], "before_violations": before["violations"],
        "changes": changes, "after_counts": after["counts"],
        "after_status_counts": after["status_counts"], "after_violations": after["violations"],
        "remaining_patients": after["patients"], "remaining_appointments": after["records"]["appointments"],
    }, indent=2, sort_keys=True))
    return result


@app.function(image=image, secrets=[database_secret, anthropic_secret], schedule=modal.Period(minutes=5), timeout=240)
def wake_caseworkers():
    """Wake due long-horizon cases; each case takes one bounded action."""
    import sys

    sys.path.insert(0, "/root/backend")
    from app.agents import due_goals, run_goal
    from app.database import session_scope

    with session_scope() as session:
        return [run_goal(session, goal) for goal in due_goals(session, 25)]


@app.function(image=image, secrets=[database_secret], env=DEMO_CAPACITY_ENV, schedule=modal.Period(minutes=1), timeout=120)
def run_capacity_overseer():
    """Wake the global capacity overseer on a bounded polling cadence."""
    import asyncio
    import sys

    sys.path.insert(0, "/root/backend")
    from app.main import run_capacity_matcher

    return asyncio.run(run_capacity_matcher())


@app.function(image=image, secrets=[database_secret], env={"USE_FAKE_VOICE": "true"}, schedule=modal.Period(minutes=1), timeout=120)
def dispatch_patient_calls():
    """Complete durable demo call actions through the explicit simulator."""
    import sys

    sys.path.insert(0, "/root/backend")
    from app.workers import dispatch_queued_calls

    return dispatch_queued_calls()


@app.function(
    image=image,
    secrets=[elevenlabs_secret, database_secret, anthropic_secret],
    env={"USE_FAKE_VOICE": "true", **DEMO_CAPACITY_ENV},
    # Keep the demo API warm so the static UI and operational data appear
    # together instead of waiting for a Modal cold start and database connect.
    min_containers=1,
    scaledown_window=120,
    timeout=60,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    import sys

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    sys.path.insert(0, "/root/backend")
    from app.main import app as api

    @api.get("/phone", include_in_schema=False)
    async def patient_phone_page():
        """Serve the SPA entry point for direct patient-phone links."""
        return FileResponse("/root/frontend/index.html")

    # Keep API routes above this mount. StaticFiles serves index.html for `/`.
    api.mount("/", StaticFiles(directory="/root/frontend", html=True), name="frontend")
    return api
