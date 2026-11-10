"""REST API for the Maritime Hypercare Agents.

Run locally (from the repository root):
    uvicorn api:app --app-dir app --reload

Then open http://localhost:8000/docs for the interactive Swagger UI.
"""
import json
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import hypercare_agents

app = FastAPI(
    title="Maritime Hypercare Agents API",
    description="Multi-agent support for AQUA / SpotOn maritime pricing (LangGraph + Snowflake Cortex).",
    version="1.0.0",
)


@lru_cache(maxsize=1)
def get_graph():
    return hypercare_agents.build_graph()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Can you look up booking BK-001 and tell me its status?"])
    subject: str | None = Field(None, description="Optional ticket subject (defaults to the question).")
    quote_id: str = ""
    booking_id: str = ""
    route_id: str = ""


class AskResponse(BaseModel):
    answer: str
    category: str | None = None
    route: str | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    kb_healing_proposal: dict | None = None
    trace: list[dict] = []


def _to_response(result: dict) -> AskResponse:
    proposal = result.get("kb_healing_proposal") or ""
    try:
        proposal_obj = json.loads(proposal) if proposal else None
    except json.JSONDecodeError:
        proposal_obj = None
    return AskResponse(
        answer=result.get("answer", ""),
        category=result.get("category"),
        route=result.get("route"),
        escalated=bool(result.get("escalated", False)),
        escalation_reason=result.get("escalation_reason") or None,
        kb_healing_proposal=proposal_obj,
        trace=result.get("trace", []),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Send a free-form question / ticket through the agent pipeline."""
    try:
        result = hypercare_agents.process_ticket(
            get_graph(),
            subject=(req.subject or req.question)[:120],
            body=req.question,
            quote_id=req.quote_id,
            booking_id=req.booking_id,
            route_id=req.route_id,
        )
    except Exception as e:  # surface configuration / Snowflake errors to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _to_response(result)


@app.post("/tickets/{ticket_id}/process", response_model=AskResponse)
def process_existing_ticket(ticket_id: str) -> AskResponse:
    """Load an existing ticket from the TICKETS table and process it."""
    try:
        result = hypercare_agents.process_ticket_from_db(get_graph(), ticket_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _to_response(result)
