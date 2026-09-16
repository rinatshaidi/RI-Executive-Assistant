#!/usr/bin/env python3
"""Small deterministic planning service for RI Assistant.

The service never accesses Google Calendar, Telegram, or voice providers.
n8n sends only a proposed day, constraints, and tasks; this service returns a
reviewable plan or relocation options.
"""
import hmac
import json
import os
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
PORT = int(os.getenv("PLANNER_PORT", "8080"))
TOKEN = os.getenv("PLANNER_API_TOKEN", "")


def parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError("date-time must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW)
    return parsed.astimezone(MOSCOW)


def to_iso(value):
    return value.astimezone(MOSCOW).isoformat()


def normalized_events(events, exclude_event_id=None):
    """Return opaque, timed calendar blocks sorted by start time."""
    blocks = []
    for event in events or []:
        if event.get("id") == exclude_event_id or event.get("transparency") == "transparent":
            continue
        start, end = event.get("start"), event.get("end")
        if not start or not end:
            continue
        start, end = parse_datetime(start), parse_datetime(end)
        if end <= start:
            continue
        blocks.append({
            "id": event.get("id", ""),
            "title": event.get("title", ""),
            "location": event.get("location", ""),
            "start": start,
            "end": end,
        })
    return sorted(blocks, key=lambda item: item["start"])


def free_intervals(window_start, window_end, events):
    cursor = window_start
    result = []
    for event in events:
        if event["end"] <= cursor or event["start"] >= window_end:
            continue
        if event["start"] > cursor:
            result.append((cursor, min(event["start"], window_end)))
        cursor = max(cursor, event["end"])
        if cursor >= window_end:
            break
    if cursor < window_end:
        result.append((cursor, window_end))
    return result


def plan_tasks(payload):
    window_start = parse_datetime(payload["windowStart"])
    window_end = parse_datetime(payload["windowEnd"])
    if window_end <= window_start:
        raise ValueError("windowEnd must be after windowStart")

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a non-empty array")

    events = normalized_events(payload.get("calendarEvents", []))
    travel_buffer = max(0, int(payload.get("travelBufferMinutes", 30)))
    available = free_intervals(window_start, window_end, events)
    proposed, unscheduled = [], []

    for raw_task in tasks:
        title = str(raw_task.get("title", "")).strip()
        if not title:
            raise ValueError("each task needs a title")
        duration = max(5, int(raw_task.get("durationMinutes", 30)))
        needs_travel = bool(str(raw_task.get("location", "")).strip())
        reserve = timedelta(minutes=travel_buffer if needs_travel else 0)
        required = timedelta(minutes=duration) + reserve

        placed = False
        for index, (start, end) in enumerate(available):
            if end - start < required:
                continue
            task_end = start + timedelta(minutes=duration)
            proposed.append({
                "title": title,
                "location": raw_task.get("location", ""),
                "start": to_iso(start),
                "end": to_iso(task_end),
                "durationMinutes": duration,
                "travelBufferAfterMinutes": travel_buffer if needs_travel else 0,
            })
            available[index] = (task_end + reserve, end)
            placed = True
            break
        if not placed:
            unscheduled.append({"title": title, "durationMinutes": duration})

    return {
        "timezone": "Europe/Moscow",
        "proposedEvents": proposed,
        "unscheduled": unscheduled,
        "conflicts": [
            {"title": event["title"], "start": to_iso(event["start"]), "end": to_iso(event["end"])}
            for event in overlapping_events(events)
        ],
    }


def overlapping_events(events):
    overlaps = []
    previous_end = None
    for event in events:
        if previous_end and event["start"] < previous_end:
            overlaps.append(event)
        previous_end = max(previous_end, event["end"]) if previous_end else event["end"]
    return overlaps


def relocation_options(payload):
    target = payload.get("targetEvent") or {}
    duration = max(5, int(target.get("durationMinutes", 0)))
    if not duration:
        raise ValueError("targetEvent.durationMinutes is required")
    window_start = parse_datetime(payload["windowStart"])
    window_end = parse_datetime(payload["windowEnd"])
    events = normalized_events(payload.get("calendarEvents", []), target.get("id"))
    buffer = timedelta(minutes=max(0, int(payload.get("travelBufferMinutes", 30))))
    options = []

    for start, end in free_intervals(window_start, window_end, events):
        candidate_end = start + timedelta(minutes=duration)
        if candidate_end + buffer <= end:
            options.append({"start": to_iso(start), "end": to_iso(candidate_end)})
        if len(options) == 3:
            break

    return {
        "timezone": "Europe/Moscow",
        "targetEventId": target.get("id", ""),
        "options": options,
        "conflicts": [
            {"title": event["title"], "start": to_iso(event["start"]), "end": to_iso(event["end"])}
            for event in overlapping_events(events)
        ],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return bool(TOKEN) and hmac.compare_digest(supplied, TOKEN)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok", "timezone": "Europe/Moscow"})
            return
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            self.reply(401, {"error": "unauthorized"})
            return
        try:
            payload = self.read_json()
            if self.path == "/v1/plan":
                self.reply(200, plan_tasks(payload))
                return
            if self.path == "/v1/relocation-options":
                self.reply(200, relocation_options(payload))
                return
            self.reply(404, {"error": "not_found"})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
