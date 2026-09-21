from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import ToolRequest
from app.store import KnowledgeStore
from app.tools import ToolDispatcher
from app.voice import session_config

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

store = KnowledgeStore(settings.db_path)
dispatcher = ToolDispatcher(store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    yield


app = FastAPI(
    title="TacitOS",
    description="Voice-to-expertise intelligence for the AssemblyAI Voice Agent Hackathon.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "TacitOS", "environment": settings.app_env}


@app.get("/api/voice-token")
async def voice_token(expires_in_seconds: int = Query(default=300, ge=60, le=600)):
    if not settings.assemblyai_api_key:
        raise HTTPException(
            status_code=503,
            detail="ASSEMBLYAI_API_KEY is not configured on the server.",
        )

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            settings.voice_token_url,
            params={"expires_in_seconds": expires_in_seconds},
            headers={"Authorization": f"Bearer {settings.assemblyai_api_key}"},
        )

    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail=f"AssemblyAI token request failed: {response.text[:300]}",
        )

    data = response.json()
    return {"token": data["token"], "expires_in_seconds": expires_in_seconds}


@app.get("/api/voice-config")
async def voice_config(mode: str = Query(default="capture", pattern="^(capture|apprentice)$")):
    return session_config(mode)


@app.post("/api/tool")
async def execute_tool(request: ToolRequest):
    try:
        result = dispatcher.run(request.name, request.arguments)
        if request.session_id:
            store.add_audit(
                "voice.tool_called",
                {
                    "session_id": request.session_id,
                    "tool": request.name,
                    "arguments": request.arguments,
                },
            )
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/dashboard")
async def dashboard():
    rules = store.list_rules()
    conflicts = store.list_conflicts()
    topic_states = []
    seen = set()
    for rule in rules:
        key = rule["topic"].lower()
        if key not in seen:
            seen.add(key)
            topic_states.append(dispatcher.engine.inspect_knowledge_state(rule["topic"]))

    return {
        "stats": store.stats(),
        "rules": rules[:50],
        "conflicts": conflicts[:50],
        "topics": topic_states,
    }
