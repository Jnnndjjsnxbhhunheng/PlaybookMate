"""
FastAPI backend for Praxis.

Two roles, one app:
  - Product Manager  → submits HS requests, adds feedback, reads dashboards
  - Algorithm Eng    → reviews trials, approves/rejects promotions, adds regression cases

Role is passed as X-Role header ("pm" | "algo") — replace with real auth in prod.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..protocol.lifecycle import LifecycleFSM, Phase
from ..protocol.trial_schema import (
    FeedbackSource,
    TrialLog,
    TrialOutcome,
    TrialRecord,
    ResourceUsage,
    ScoreSnapshot,
    PolicyDiff,
)
from ..protocol.workspace import HSConfig, WorkspaceManager
from ..knowledge.meta_prompt import MetaPrompt

RUNS_ROOT = Path(__file__).parent.parent.parent / "runs"
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Praxis", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ws = WorkspaceManager(RUNS_ROOT)


# ---------------------------------------------------------------------------
# Page routes (serve HTML shell; JS fetches data via API)
# ---------------------------------------------------------------------------

def _html(name: str) -> HTMLResponse:
    path = TEMPLATES_DIR / name
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return _html("index.html")


@app.get("/hs/{hs_id}", response_class=HTMLResponse)
async def hs_detail_page(hs_id: str) -> HTMLResponse:
    return _html("hs_detail.html")


@app.get("/review", response_class=HTMLResponse)
async def review_page() -> HTMLResponse:
    return _html("review.html")


# ---------------------------------------------------------------------------
# API: HS management
# ---------------------------------------------------------------------------

class CreateHSRequest(BaseModel):
    name: str
    domain: str
    description: str = ""
    primary_metric: str = "score"
    budget_wall_seconds: int = 3600
    budget_llm_tokens: int = 500_000
    tags: list[str] = []
    # PM attaches the requirement doc as markdown
    requirement_doc: str = ""


@app.get("/api/hs")
async def list_hs() -> list[dict]:
    result = []
    for hs_id in ws.list_hs():
        try:
            fsm = LifecycleFSM(hs_id, ws)
            s = fsm.summary()
            config = ws.load_config(hs_id)
            result.append({
                **s,
                "domain": config.domain,
                "description": config.description,
                "tags": config.tags,
                "phase": s["phase"],
                "total_trials": s["total_trials"],
                "best_score": s["best_score"],
                "cumulative_tokens": s["cumulative_tokens"],
            })
        except Exception as e:
            result.append({"hs_id": hs_id, "error": str(e)})
    return result


@app.post("/api/hs", status_code=201)
async def create_hs(req: CreateHSRequest) -> dict:
    config = HSConfig(
        hs_id=req.name,
        domain=req.domain,
        description=req.description,
        primary_metric=req.primary_metric,
        budget_wall_seconds=req.budget_wall_seconds,
        budget_llm_tokens=req.budget_llm_tokens,
        tags=req.tags,
    )
    path = ws.create(config)

    # persist requirement doc if provided
    if req.requirement_doc:
        req_file = path / "requirement.md"
        req_file.write_text(req.requirement_doc, encoding="utf-8")

    return {"hs_id": req.name, "path": str(path)}


@app.get("/api/hs/{hs_id}")
async def get_hs(hs_id: str) -> dict:
    try:
        config = ws.load_config(hs_id)
    except FileNotFoundError:
        raise HTTPException(404, f"HS '{hs_id}' not found")

    fsm = LifecycleFSM(hs_id, ws)
    s = fsm.summary()
    log = TrialLog(str(RUNS_ROOT / hs_id / "trials.jsonl"))
    records = log.read_all()

    # regression cases
    reg_dir = RUNS_ROOT / hs_id / "regression_set"
    regression_cases = []
    if reg_dir.exists():
        for f in sorted(reg_dir.iterdir()):
            if f.suffix == ".json":
                try:
                    regression_cases.append({
                        "name": f.stem,
                        "data": json.loads(f.read_text()),
                    })
                except Exception:
                    pass

    # current policy
    policy_path = RUNS_ROOT / hs_id / "policy.py"
    policy_code = policy_path.read_text(encoding="utf-8") if policy_path.exists() else ""

    # requirement doc
    req_path = RUNS_ROOT / hs_id / "requirement.md"
    requirement_doc = req_path.read_text(encoding="utf-8") if req_path.exists() else ""

    return {
        "config": config.__dict__,
        "summary": s,
        "phase_instruction": fsm.next_phase_instruction(),
        "trials": [_trial_to_dict(r) for r in records],
        "regression_cases": regression_cases,
        "policy_code": policy_code,
        "requirement_doc": requirement_doc,
        "promotion_blockers": ws.validate_for_promotion(hs_id),
    }


# ---------------------------------------------------------------------------
# API: feedback inbox (PM submits, algo sees)
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    source: str = "manual"       # FeedbackSource value
    title: str
    body: str
    case_data: dict | None = None   # optional structured case for regression set


@app.post("/api/hs/{hs_id}/feedback", status_code=201)
async def add_feedback(hs_id: str, req: FeedbackRequest) -> dict:
    inbox = RUNS_ROOT / hs_id / "feedback_inbox"
    if not inbox.exists():
        raise HTTPException(404, f"HS '{hs_id}' not found")

    ts = int(datetime.utcnow().timestamp())
    entry = {
        "source": req.source,
        "title": req.title,
        "body": req.body,
        "case_data": req.case_data,
        "created_at": datetime.utcnow().isoformat(),
    }
    path = inbox / f"{ts}.json"
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": path.name, "created_at": entry["created_at"]}


@app.get("/api/hs/{hs_id}/feedback")
async def list_feedback(hs_id: str) -> list[dict]:
    inbox = RUNS_ROOT / hs_id / "feedback_inbox"
    if not inbox.exists():
        raise HTTPException(404, f"HS '{hs_id}' not found")
    result = []
    for f in sorted(inbox.iterdir()):
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text())
                data["id"] = f.name
                result.append(data)
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# API: regression cases (algo adds; PM sees count)
# ---------------------------------------------------------------------------

@app.post("/api/hs/{hs_id}/regression", status_code=201)
async def add_regression_case(
    hs_id: str,
    name: str = Body(...),
    input_data: dict = Body(...),
    expected_output: dict = Body(...),
    note: str = Body(""),
    x_role: str = Header(default="algo"),
) -> dict:
    if x_role != "algo":
        raise HTTPException(403, "Only algo engineers can add regression cases")
    reg_dir = RUNS_ROOT / hs_id / "regression_set"
    if not reg_dir.exists():
        raise HTTPException(404, f"HS '{hs_id}' not found")
    case = {
        "name": name,
        "input": input_data,
        "expected_output": expected_output,
        "note": note,
        "added_at": datetime.utcnow().isoformat(),
    }
    path = reg_dir / f"{name}.json"
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": name, "path": str(path)}


# ---------------------------------------------------------------------------
# API: promotion review (algo approves / rejects)
# ---------------------------------------------------------------------------

class ReviewDecision(BaseModel):
    decision: str   # "approve" | "reject"
    comment: str = ""


@app.get("/api/review")
async def list_pending_reviews() -> list[dict]:
    """Return all HS that are in PROMOTING or BLOCKED phase."""
    pending = []
    for hs_id in ws.list_hs():
        try:
            fsm = LifecycleFSM(hs_id, ws)
            phase = fsm.current_phase()
            if phase in (Phase.PROMOTING, Phase.BLOCKED, Phase.SIMPLIFYING):
                s = fsm.summary()
                config = ws.load_config(hs_id)
                log = TrialLog(str(RUNS_ROOT / hs_id / "trials.jsonl"))
                records = log.read_all()
                last = records[-1] if records else None
                pending.append({
                    **s,
                    "domain": config.domain,
                    "description": config.description,
                    "last_trial": _trial_to_dict(last) if last else None,
                    "promotion_blockers": ws.validate_for_promotion(hs_id),
                })
        except Exception:
            pass
    return pending


@app.post("/api/hs/{hs_id}/review")
async def submit_review(
    hs_id: str,
    req: ReviewDecision,
    x_role: str = Header(default="algo"),
) -> dict:
    if x_role != "algo":
        raise HTTPException(403, "Only algo engineers can submit reviews")

    review_dir = RUNS_ROOT / hs_id / "reviews"
    review_dir.mkdir(exist_ok=True)
    ts = int(datetime.utcnow().timestamp())
    entry = {
        "decision": req.decision,
        "comment": req.comment,
        "submitted_at": datetime.utcnow().isoformat(),
    }
    (review_dir / f"{ts}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entry


@app.get("/api/hs/{hs_id}/reviews")
async def list_reviews(hs_id: str) -> list[dict]:
    review_dir = RUNS_ROOT / hs_id / "reviews"
    if not review_dir.exists():
        return []
    result = []
    for f in sorted(review_dir.iterdir()):
        if f.suffix == ".json":
            try:
                result.append(json.loads(f.read_text()))
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# API: knowledge layer
# ---------------------------------------------------------------------------

@app.post("/api/knowledge/refresh")
async def refresh_knowledge(x_role: str = Header(default="algo")) -> dict:
    if x_role != "algo":
        raise HTTPException(403, "Only algo engineers can refresh the knowledge layer")
    mp = MetaPrompt(runs_root=RUNS_ROOT)
    mp.refresh()
    return {"ok": True, "refreshed_at": datetime.utcnow().isoformat()}


@app.get("/api/knowledge/hints/{domain}")
async def get_hints(domain: str, tags: str = "") -> dict:
    mp = MetaPrompt(runs_root=RUNS_ROOT)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    hints = mp.get_hints(domain, tag_list)
    return {"domain": domain, "hints": hints}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trial_to_dict(r: TrialRecord) -> dict:
    d = r.model_dump(mode="json")
    # add computed delta for the frontend
    d["score_delta"] = r.score.delta
    return d
