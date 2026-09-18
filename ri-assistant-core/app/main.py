"""State core for RI Assistant.

The service contains no bot, calendar, or AI credentials. n8n remains the
integration layer; it sends only chat id, callback data, and transcription.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

APP_KEY = os.environ.get("RI_ASSISTANT_CORE_KEY", "")
DB_PATH = Path(os.environ.get("RI_ASSISTANT_DB", "/data/assistant.db"))
EDIT_TTL_SECONDS = 30 * 60

app = FastAPI(title="RI Assistant Core", version="0.1.0")


class BeginEdit(BaseModel):
    chat_id: str
    event_id: str


class ResolveVoice(BaseModel):
    chat_id: str
    transcript: str = Field(min_length=1, max_length=8000)


class CompleteEdit(BaseModel):
    chat_id: str
    event_id: str


def require_key(key: str | None) -> None:
    if APP_KEY and key != APP_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS pending_edits (
                chat_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )"""
        )
        yield db
        db.commit()
    finally:
        db.close()


def cancellation_requested(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    phrases = (
        "отбой",
        "не надо",
        "не нужно",
        "ничего не став",
        "ничего не созда",
        "отменяй создание",
        "не создавай",
    )
    return any(phrase in normalized for phrase in phrases)


@app.get("/health")
def health() -> dict[str, str]:
    with connection() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/v1/edit/begin")
def begin_edit(payload: BeginEdit, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, str]:
    require_key(x_ri_assistant_key)
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO pending_edits(chat_id, event_id, expires_at) VALUES (?, ?, ?)",
            (payload.chat_id, payload.event_id, int(time.time()) + EDIT_TTL_SECONDS),
        )
    return {
        "status": "awaiting_voice",
        "reply": "Скажите голосом, что изменить в событии.",
    }


@app.post("/v1/voice/resolve")
def resolve_voice(payload: ResolveVoice, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, str | bool | None]:
    require_key(x_ri_assistant_key)
    if cancellation_requested(payload.transcript):
        with connection() as db:
            db.execute("DELETE FROM pending_edits WHERE chat_id = ?", (payload.chat_id,))
        return {"intent": "cancel_request", "event_id": None, "requires_update": False}

    now = int(time.time())
    with connection() as db:
        row = db.execute(
            "SELECT event_id, expires_at FROM pending_edits WHERE chat_id = ?", (payload.chat_id,)
        ).fetchone()
        if row and row[1] <= now:
            db.execute("DELETE FROM pending_edits WHERE chat_id = ?", (payload.chat_id,))
            row = None

    if row:
        return {"intent": "update_event", "event_id": row[0], "requires_update": True}
    return {"intent": "create_event", "event_id": None, "requires_update": False}


@app.post("/v1/edit/complete")
def complete_edit(payload: CompleteEdit, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, Literal["cleared"]]:
    require_key(x_ri_assistant_key)
    with connection() as db:
        db.execute(
            "DELETE FROM pending_edits WHERE chat_id = ? AND event_id = ?",
            (payload.chat_id, payload.event_id),
        )
    return {"status": "cleared"}
