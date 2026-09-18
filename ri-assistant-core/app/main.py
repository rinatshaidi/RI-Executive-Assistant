"""State core for RI Assistant.

The service contains no bot, calendar, or AI credentials. n8n remains the
integration layer; it sends only chat id, callback data, and transcription.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI, OpenAIError

APP_KEY = os.environ.get("RI_ASSISTANT_CORE_KEY", "")
DB_PATH = Path(os.environ.get("RI_ASSISTANT_DB", "/data/assistant.db"))
EDIT_TTL_SECONDS = 30 * 60
MOSCOW = ZoneInfo("Europe/Moscow")
RESPONSES_MODEL = os.environ.get("OPENAI_RESPONSES_MODEL", "gpt-4.1-mini")

app = FastAPI(title="RI Assistant Core", version="0.1.0")


class BeginEdit(BaseModel):
    chat_id: str | int
    event_id: str


class ResolveVoice(BaseModel):
    chat_id: str | int
    transcript: str = Field(min_length=1, max_length=8000)


class CompleteEdit(BaseModel):
    chat_id: str | int
    event_id: str


class CalendarInterval(BaseModel):
    start: str
    end: str
    location: str = ""


class DayTask(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    location: str = Field(default="", max_length=300)


class DayPlanRequest(BaseModel):
    date: str
    tasks: list[DayTask] = Field(min_length=1, max_length=20)
    calendar: list[CalendarInterval] = Field(default_factory=list, max_length=100)
    work_start: str = "08:00"
    work_end: str = "23:00"
    event_buffer_minutes: int = Field(default=30, ge=0, le=120)


class CalendarContextEvent(BaseModel):
    event_id: str
    title: str
    start: str
    end: str
    location: str = ""


class VoiceInterpretRequest(BaseModel):
    chat_id: str | int
    transcript: str = Field(min_length=1, max_length=8000)
    calendar: list[CalendarContextEvent] = Field(default_factory=list, max_length=100)
    timezone: str = "Europe/Moscow"


VOICE_ACTIONS = (
    "calendar_create",
    "calendar_update",
    "calendar_cancel",
    "calendar_search",
    "day_plan",
    "day_task_create",
    "note_save",
    "clarify",
)


class VoiceAction(BaseModel):
    action: Literal[
        "calendar_create", "calendar_update", "calendar_cancel", "calendar_search",
        "day_plan", "day_task_create", "note_save", "clarify",
    ]
    arguments: dict


def tool_schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


VOICE_TOOLS = [
    tool_schema("calendar_create", "Create one calendar event only when date and time are clear.", {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "location": {"type": "string"}}, ["title", "start", "end"]),
    tool_schema("calendar_update", "Update one identified event. Use its event_id from calendar context.", {"event_id": {"type": "string"}, "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "location": {"type": "string"}}, ["event_id"]),
    tool_schema("calendar_cancel", "Cancel one identified event. Use its event_id from calendar context.", {"event_id": {"type": "string"}}, ["event_id"]),
    tool_schema("calendar_search", "Find events before proposing a change or cancellation when no single event is identified.", {"operation": {"type": "string", "enum": ["update", "cancel", "find"]}, "query": {"type": "string"}, "date_hint": {"type": "string"}}, ["operation", "query"]),
    tool_schema("day_plan", "Propose slots for several tasks without creating events until the user confirms.", {"date": {"type": "string"}, "tasks": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "duration_minutes": {"type": "integer"}, "location": {"type": "string"}}, "required": ["title"]}}}, ["date", "tasks"]),
    tool_schema("day_task_create", "Create an all-day task without a fixed time.", {"title": {"type": "string"}, "date": {"type": "string"}}, ["title", "date"]),
    tool_schema("note_save", "Save a dictated note without creating a calendar event.", {"content": {"type": "string"}, "title": {"type": "string"}}, ["content"]),
    tool_schema("clarify", "Ask one short Russian clarification when a safe action cannot be determined.", {"question": {"type": "string"}}, ["question"]),
]


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


def parse_moscow(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MOSCOW)
    return parsed.astimezone(MOSCOW)


def free_slots(
    day_start: datetime, day_end: datetime, calendar: list[CalendarInterval], buffer_minutes: int
) -> list[tuple[datetime, datetime]]:
    occupied: list[tuple[datetime, datetime]] = []
    buffer = timedelta(minutes=buffer_minutes)
    for item in calendar:
        start, end = parse_moscow(item.start), parse_moscow(item.end)
        start, end = max(start - buffer, day_start), min(end + buffer, day_end)
        if end > start:
            occupied.append((start, end))
    occupied.sort(key=lambda item: item[0])
    merged: list[list[datetime]] = []
    for start, end in occupied:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    result: list[tuple[datetime, datetime]] = []
    cursor = day_start
    for start, end in merged:
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < day_end:
        result.append((cursor, day_end))
    return result


def plan_tasks(request: DayPlanRequest) -> dict:
    try:
        day = datetime.fromisoformat(request.date).date()
        work_start_hour, work_start_minute = map(int, request.work_start.split(":"))
        work_end_hour, work_end_minute = map(int, request.work_end.split(":"))
    except ValueError as exc:
        raise ValueError("date and working hours must use ISO formats") from exc
    day_start = datetime(day.year, day.month, day.day, work_start_hour, work_start_minute, tzinfo=MOSCOW)
    day_end = datetime(day.year, day.month, day.day, work_end_hour, work_end_minute, tzinfo=MOSCOW)
    if day_end <= day_start:
        raise ValueError("work_end must be after work_start")

    slots = free_slots(day_start, day_end, request.calendar, request.event_buffer_minutes)
    planned, unplanned = [], []
    # Grouping equal declared locations avoids needless back-and-forth. It is not
    # a traffic estimate: route durations require a future maps integration.
    tasks = sorted(request.tasks, key=lambda task: (not bool(task.location.strip()), task.location.casefold(), task.title.casefold()))
    for task in tasks:
        duration = timedelta(minutes=task.duration_minutes)
        placed = False
        for index, (start, end) in enumerate(slots):
            if end - start < duration:
                continue
            finish = start + duration
            planned.append(
                {
                    "title": task.title,
                    "start": start.isoformat(),
                    "end": finish.isoformat(),
                    "location": task.location,
                }
            )
            if finish == end:
                slots.pop(index)
            else:
                slots[index] = (finish, end)
            placed = True
            break
        if not placed:
            unplanned.append({"title": task.title, "duration_minutes": task.duration_minutes, "location": task.location})
    return {
        "date": request.date,
        "planned": planned,
        "unplanned": unplanned,
        "free_slots": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in slots],
        "route_note": "Задачи с одинаковой указанной локацией сгруппированы; время в пути пока не рассчитывается.",
    }


def voice_instruction(payload: VoiceInterpretRequest) -> str:
    calendar = [item.model_dump() for item in payload.calendar]
    today = datetime.now(MOSCOW).date().isoformat()
    return (
        "You are RI Assistant, a careful executive assistant. Interpret the user's "
        "Russian voice transcription and call exactly one tool. Do not create, update, "
        "or cancel a calendar event unless the date, time, and target are unambiguous. "
        "For an uncertain target, use calendar_search or clarify. For multiple tasks, "
        "use day_plan; it proposes a plan and does not create events. For a calendar "
        "change or cancellation without one identified event, use calendar_search with "
        "operation update or cancel. For a task without "
        "a fixed time, use day_task_create. For dictated ideas, use note_save. Do not "
        "invent event identifiers. Return all user-facing text in Russian. "
        f"Today in {payload.timezone} is {today}. Resolve relative Russian dates such as "
        "'сегодня' and 'завтра' from that date. Calendar start and end values must be "
        "ISO 8601 datetimes with the +03:00 offset. "
        f"Timezone: {payload.timezone}. Calendar context: {json.dumps(calendar, ensure_ascii=False)}. "
        f"User transcription: {payload.transcript}"
    )


def parse_voice_tool_call(name: str, arguments: str) -> VoiceAction:
    if name not in VOICE_ACTIONS:
        raise ValueError("model requested an unsupported action")
    decoded = json.loads(arguments)
    if not isinstance(decoded, dict):
        raise ValueError("tool arguments must be an object")
    return VoiceAction(action=name, arguments=decoded)


def get_openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured")
    return OpenAI(api_key=api_key)


@app.get("/health")
def health() -> dict[str, str]:
    with connection() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/v1/edit/begin")
def begin_edit(payload: BeginEdit, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, str]:
    require_key(x_ri_assistant_key)
    chat_id = str(payload.chat_id)
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO pending_edits(chat_id, event_id, expires_at) VALUES (?, ?, ?)",
            (chat_id, payload.event_id, int(time.time()) + EDIT_TTL_SECONDS),
        )
    return {
        "status": "awaiting_voice",
        "reply": "Скажите голосом, что изменить в событии.",
    }


@app.post("/v1/voice/resolve")
def resolve_voice(payload: ResolveVoice, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, str | bool | None]:
    require_key(x_ri_assistant_key)
    chat_id = str(payload.chat_id)
    if cancellation_requested(payload.transcript):
        with connection() as db:
            db.execute("DELETE FROM pending_edits WHERE chat_id = ?", (chat_id,))
        return {"intent": "cancel_request", "event_id": None, "requires_update": False}

    now = int(time.time())
    with connection() as db:
        row = db.execute(
            "SELECT event_id, expires_at FROM pending_edits WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if row and row[1] <= now:
            db.execute("DELETE FROM pending_edits WHERE chat_id = ?", (chat_id,))
            row = None

    if row:
        return {"intent": "update_event", "event_id": row[0], "requires_update": True}
    return {"intent": "create_event", "event_id": None, "requires_update": False}


@app.post("/v1/edit/complete")
def complete_edit(payload: CompleteEdit, x_ri_assistant_key: str | None = Header(default=None)) -> dict[str, Literal["cleared"]]:
    require_key(x_ri_assistant_key)
    chat_id = str(payload.chat_id)
    with connection() as db:
        db.execute(
            "DELETE FROM pending_edits WHERE chat_id = ? AND event_id = ?",
            (chat_id, payload.event_id),
        )
    return {"status": "cleared"}


@app.post("/v1/voice/interpret")
def interpret_voice(payload: VoiceInterpretRequest, x_ri_assistant_key: str | None = Header(default=None)) -> dict:
    require_key(x_ri_assistant_key)
    try:
        response = get_openai_client().responses.create(
            model=RESPONSES_MODEL,
            input=voice_instruction(payload),
            tools=VOICE_TOOLS,
            tool_choice="required",
            parallel_tool_calls=False,
            store=False,
        )
        calls = [item for item in response.output if item.type == "function_call"]
        if len(calls) != 1:
            raise ValueError("model must request exactly one action")
        action = parse_voice_tool_call(calls[0].name, calls[0].arguments)
        return action.model_dump()
    except HTTPException:
        raise
    except (OpenAIError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="voice interpretation unavailable") from exc


@app.post("/v1/day-plan")
def day_plan(payload: DayPlanRequest, x_ri_assistant_key: str | None = Header(default=None)) -> dict:
    require_key(x_ri_assistant_key)
    try:
        return plan_tasks(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
