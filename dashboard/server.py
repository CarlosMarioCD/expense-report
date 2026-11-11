"""Control panel for factory runs.

Run:  uvicorn dashboard.server:app --port 8001
Then open http://127.0.0.1:8001 and start ./factory.sh <n> in a terminal.

The panel watches .factory/ (or $FACTORY_DIR). It never starts or stops a run. Its one
write is the human's answer on the plan (.factory/decision.json), accepted only while the
factory waits for that plan round; the terminal can answer too, so a broken panel never
blocks the run.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from dashboard.state import build_state

ROOT = Path(__file__).resolve().parent.parent
INDEX = Path(__file__).resolve().parent / "index.html"
POLL_SECONDS = 0.4
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HEARTBEAT_SECONDS = 15.0

app = FastAPI(title="Factory dashboard")


class Disconnectable(Protocol):
    async def is_disconnected(self) -> bool: ...


def factory_dir() -> Path:
    return Path(os.environ.get("FACTORY_DIR", ROOT / ".factory")).resolve()


def snapshot() -> dict[str, Any]:
    return build_state(factory_dir(), root=f"{ROOT}/")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX, media_type="text/html")


@app.get("/api/state")
def state() -> dict[str, Any]:
    return snapshot()


async def state_events(request: Disconnectable) -> AsyncIterator[str]:
    """Server-sent events: the full state whenever it changes, a comment ping otherwise."""
    last, idle = "", 0.0
    while not await request.is_disconnected():
        body = json.dumps(await asyncio.to_thread(snapshot))
        if body != last:
            last, idle = body, 0.0
            yield f"data: {body}\n\n"
        elif idle >= HEARTBEAT_SECONDS:
            idle = 0.0
            yield ": ping\n\n"
        await asyncio.sleep(POLL_SECONDS)
        idle += POLL_SECONDS


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(state_events(request), media_type="text/event-stream", headers=headers)


class Decision(BaseModel):
    round: int = Field(ge=1)
    decision: Literal["approve", "deny"]
    feedback: str = Field(default="", max_length=2000)


@app.post("/api/decision")
def decide(body: Decision, request: Request) -> dict[str, Any]:
    """The human approves the plan, or denies it with feedback for the next plan round."""
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
        raise HTTPException(403, "decisions come from the panel on this machine only")
    feedback = " ".join(body.feedback.split())
    if body.decision == "deny" and not feedback:
        raise HTTPException(422, "say what to change, so the next plan can address it")
    approval = snapshot()["approval"]
    if approval["state"] != "waiting" or approval["round"] != body.round:
        raise HTTPException(409, "no plan is waiting for that decision")
    target = factory_dir() / "decision.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"round": body.round, "decision": body.decision, "feedback": feedback}))
    tmp.replace(target)  # atomic: the factory never reads half a decision
    return {"ok": True}
