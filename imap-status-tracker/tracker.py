#!/usr/bin/env python3
"""Minimal IMAP unread-status tracker for n8n.
Stores no email bodies or attachments.
"""
import hmac
import imaplib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path(os.getenv("TRACKER_DB_PATH", "/data/tracker.db"))
PORT = int(os.getenv("TRACKER_PORT", "8080"))
TOKEN = os.getenv("TRACKER_API_TOKEN", "")
MOSCOW = ZoneInfo("Europe/Moscow")
REFRESH_HOUR = int(os.getenv("TRACKER_REFRESH_HOUR", "7"))
REFRESH_MINUTE = int(os.getenv("TRACKER_REFRESH_MINUTE", "30"))
REFRESH_STATE = {"lastRefreshAt": None, "lastErrorCount": 0}
REFRESH_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def next_refresh_at(current=None):
    current = current or datetime.now(MOSCOW)
    candidate = datetime.combine(current.date(), time(REFRESH_HOUR, REFRESH_MINUTE), tzinfo=MOSCOW)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS tracked_messages (
            source TEXT NOT NULL,
            message_id TEXT NOT NULL,
            sender TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_unread_at TEXT,
            resolved_at TEXT,
            PRIMARY KEY (source, message_id)
        )
    """)
    return connection


def source_config(source):
    key = "IMAP_" + re.sub(r"[^A-Z0-9]+", "_", source.upper()).strip("_")
    values = {name: os.getenv(f"{key}_{name}", "") for name in ("HOST", "PORT", "USER", "PASSWORD")}
    if not all(values.values()):
        raise ValueError(f"IMAP configuration for source '{source}' is missing")
    return values


def unread_status(source, message_id):
    config = source_config(source)
    with imaplib.IMAP4_SSL(config["HOST"], int(config["PORT"])) as client:
        client.login(config["USER"], config["PASSWORD"])
        client.select("INBOX", readonly=True)
        status, matches = client.search(None, "HEADER", "MESSAGE-ID", message_id)
        if status != "OK" or not matches or not matches[0]:
            return False
        status, payload = client.fetch(matches[0].split()[-1], "(FLAGS)")
        if status != "OK" or not payload or not payload[0]:
            return False
        flags = payload[0][0].decode("utf-8", errors="replace")
        return "\\Seen" not in flags


def tracked_unread(refresh=False):
    connection = db()
    rows = connection.execute(
        "SELECT * FROM tracked_messages WHERE resolved_at IS NULL ORDER BY first_seen_at"
    ).fetchall()
    errors = 0
    if refresh:
        for row in rows:
            try:
                is_unread = unread_status(row["source"], row["message_id"])
            except Exception:
                # Do not erase a pending reminder merely because a mailbox is unavailable.
                errors += 1
                continue
            if is_unread:
                connection.execute(
                    "UPDATE tracked_messages SET last_seen_unread_at = ? WHERE source = ? AND message_id = ?",
                    (now(), row["source"], row["message_id"]),
                )
            else:
                connection.execute(
                    "UPDATE tracked_messages SET resolved_at = ? WHERE source = ? AND message_id = ?",
                    (now(), row["source"], row["message_id"]),
                )
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM tracked_messages WHERE resolved_at IS NULL ORDER BY first_seen_at"
        ).fetchall()
    result = [
        {
            "source": row["source"],
            "messageId": row["message_id"],
            "from": row["sender"],
            "subject": row["subject"],
            "firstSeenAt": row["first_seen_at"],
        }
        for row in rows
    ]
    connection.close()
    return result, errors


def refresh_once():
    with REFRESH_LOCK:
        _, errors = tracked_unread(refresh=True)
        REFRESH_STATE["lastRefreshAt"] = now()
        REFRESH_STATE["lastErrorCount"] = errors


def refresh_loop():
    while True:
        delay = max(1, (next_refresh_at() - datetime.now(MOSCOW)).total_seconds())
        threading.Event().wait(delay)
        try:
            refresh_once()
        except Exception:
            REFRESH_STATE["lastRefreshAt"] = now()
            REFRESH_STATE["lastErrorCount"] = 1


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
            self.reply(200, {
                "status": "ok",
                "lastRefreshAt": REFRESH_STATE["lastRefreshAt"],
                "nextRefreshAt": next_refresh_at().isoformat(),
                "lastErrorCount": REFRESH_STATE["lastErrorCount"],
            })
            return
        if self.path == "/v1/unread-important":
            if not self.authorized():
                self.reply(401, {"error": "unauthorized"})
                return
            items, _ = tracked_unread(refresh=False)
            self.reply(200, {"items": items})
            return
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            self.reply(401, {"error": "unauthorized"})
            return
        try:
            payload = self.read_json()
            if self.path == "/v1/important":
                records = payload.get("items", [])
                if not isinstance(records, list):
                    raise ValueError("items must be an array")
                connection = db()
                for item in records:
                    source, message_id = item.get("source", ""), item.get("messageId", "")
                    if not source or not message_id:
                        raise ValueError("source and messageId are required")
                    connection.execute("""
                        INSERT INTO tracked_messages (source, message_id, sender, subject, first_seen_at, last_seen_unread_at, resolved_at)
                        VALUES (?, ?, ?, ?, ?, ?, NULL)
                        ON CONFLICT(source, message_id) DO NOTHING
                    """, (source, message_id, item.get("from", ""), item.get("subject", ""), now(), now()))
                connection.commit()
                connection.close()
                self.reply(201, {"tracked": len(records)})
                return
            if self.path == "/v1/refresh":
                refresh_once()
                items, _ = tracked_unread(refresh=False)
                self.reply(200, {"items": items})
                return
            self.reply(404, {"error": "not_found"})
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except Exception:
            self.reply(500, {"error": "status_check_failed"})


if __name__ == "__main__":
    if not (0 <= REFRESH_HOUR <= 23 and 0 <= REFRESH_MINUTE <= 59):
        raise ValueError("TRACKER_REFRESH_HOUR and TRACKER_REFRESH_MINUTE must form a valid time")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db().close()
    threading.Thread(target=refresh_loop, name="imap-refresh", daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()