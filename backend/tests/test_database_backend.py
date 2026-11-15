"""Guard: when CI asks for PostgreSQL, the API fixture really runs on PostgreSQL (no silent SQLite fallback), and
the behaviour most likely to differ between dialects is the same on both: JSON round-trip, unique and foreign-key
constraints, migrations at head."""
import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

SPEC = {"variables": ["a", "b", "c"], "sense": "max",
        "objective": {"linear": {"a": 5, "b": 4.25, "c": 3}},
        "constraints": [{"label": "cap", "lhs": {"linear": {"a": 4, "b": 3, "c": 2}}, "sense": "<=", "rhs": 5}]}


def test_fixture_uses_requested_database(api):
    from qopt.db.session import engine
    assert engine().dialect.name == ("postgresql" if os.environ.get("QOPT_TEST_POSTGRES_URL") else "sqlite")
    with engine().connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar_one() == "0001"
    assert {"users", "experiments", "jobs", "audit_log"} <= set(inspect(engine()).get_table_names())


def test_json_round_trip_and_constraints(admin_client):
    r = admin_client.post("/api/experiments", json={"name": "JSON round-trip ünïcødé", "spec": SPEC,
                                                    "tags": ["x", "ünï"], "description": "δ ≤ 5"})
    assert r.status_code == 200, r.text
    exp = admin_client.get(f"/api/experiments/{r.json()['id']}").json()
    assert exp["model_spec"] == SPEC and exp["tags"] == ["x", "ünï"] and exp["description"] == "δ ≤ 5"
    assert exp["name"] == "JSON round-trip ünïcødé" and exp["qubo"]

    from qopt.db import SessionLocal
    from qopt.db.models import Experiment, User
    with SessionLocal() as db:                       # unique e-mail
        db.add(User(email="admin@example.com", password_hash="x", name="dup", role="viewer"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    with SessionLocal() as db:                       # foreign key to a missing user
        db.add(Experiment(owner_id=987654, name="orphan"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
