"""Integration tests for the FastAPI backend."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create a TestClient with isolated runs_root."""
    with patch("praxis.web.api.RUNS_ROOT", tmp_path), \
         patch("praxis.web.api.ws") as mock_ws, \
         patch("praxis.web.api.TEMPLATES_DIR", Path(__file__).parent.parent.parent / "praxis/web/templates"):

        from praxis.protocol.workspace import WorkspaceManager
        real_ws = WorkspaceManager(tmp_path)

        # patch the module-level ws instance
        import praxis.web.api as api_module
        api_module.ws = real_ws
        api_module.RUNS_ROOT = tmp_path

        from praxis.web.api import app
        yield TestClient(app)


def test_list_hs_empty(client) -> None:
    r = client.get("/api/hs")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_hs(client) -> None:
    payload = {
        "name": "test_hs",
        "domain": "ticket_routing",
        "description": "Integration test HS",
        "requirement_doc": "## Background\nTest.",
        "tags": ["test"],
    }
    r = client.post("/api/hs", json=payload)
    assert r.status_code == 201
    assert r.json()["hs_id"] == "test_hs"

    r = client.get("/api/hs/test_hs")
    assert r.status_code == 200
    data = r.json()
    assert data["config"]["hs_id"] == "test_hs"
    assert "## Background" in data["requirement_doc"]
    assert data["summary"]["phase"] == "idle"
    assert data["promotion_blockers"]  # empty regression set blocks


def test_add_and_list_feedback(client) -> None:
    client.post("/api/hs", json={"name": "fb_hs", "domain": "test"})

    r = client.post("/api/hs/fb_hs/feedback", json={
        "source": "manual",
        "title": "Wrong queue for VIP",
        "body": "Enterprise tickets going to general queue",
    })
    assert r.status_code == 201

    r = client.get("/api/hs/fb_hs/feedback")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["title"] == "Wrong queue for VIP"


def test_add_regression_requires_algo_role(client) -> None:
    client.post("/api/hs", json={"name": "reg_hs", "domain": "test"})

    # PM role should be rejected
    r = client.post(
        "/api/hs/reg_hs/regression",
        json={"name": "case1", "input_data": {"x": 1}, "expected_output": {"y": 2}, "note": ""},
        headers={"X-Role": "pm"},
    )
    assert r.status_code == 403

    # Algo role should succeed
    r = client.post(
        "/api/hs/reg_hs/regression",
        json={"name": "case1", "input_data": {"x": 1}, "expected_output": {"y": 2}, "note": ""},
        headers={"X-Role": "algo"},
    )
    assert r.status_code == 201


def test_new_hs_writes_agent_briefs(client, tmp_path) -> None:
    client.post("/api/hs", json={"name": "brief_hs", "domain": "ticket_routing"})
    assert (tmp_path / "brief_hs" / "AGENTS.md").exists()
    assert (tmp_path / "brief_hs" / "CLAUDE.md").exists()


def test_brief_endpoint(client) -> None:
    client.post("/api/hs", json={"name": "b2", "domain": "ticket_routing", "description": "d"})
    r = client.get("/api/hs/b2/brief")
    assert r.status_code == 200
    data = r.json()
    # the brief tells the agent to self-drive the whole loop
    assert "You drive the" in data["brief"]
    assert data["agent"] in ("codex", "claude")
    assert "&&" in data["launch_interactive"]
    assert data["praxis_command"] == "praxis run --hs b2"


def test_review_queue_empty(client) -> None:
    r = client.get("/api/review")
    assert r.status_code == 200
    assert r.json() == []


def test_page_routes(client) -> None:
    for path in ["/", "/hs/anything", "/review"]:
        r = client.get(path)
        assert r.status_code == 200
        assert "Praxis" in r.text
