#!/usr/bin/env python3
"""Minimal IMAP unread-status tracker for n8n.
Stores no email bodies or attachments.
"""
import hmac
import imaplib
import json
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
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
IMAP_SOURCES = tuple(filter(None, (item.strip() for item in os.getenv("IMAP_SOURCES", "").split(","))))


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




def configured_sources():
    if not IMAP_SOURCES:
        raise ValueError("IMAP_SOURCES is not configured")
    return IMAP_SOURCES


def imap_date(value):
    return value.strftime("%d-%b-%Y")


def decode_header_value(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def message_headers(payload):
    message = BytesParser(policy=policy.default).parsebytes(payload)
    raw_date = message.get("Date", "")
    try:
        received_at = parsedate_to_datetime(raw_date).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        received_at = ""
    return {
        "rfcMessageId": message.get("Message-ID", "").strip(),
        "from": decode_header_value(message.get("From", "")),
        "subject": decode_header_value(message.get("Subject", "")),
        "receivedAt": received_at,
    }


def fetch_headers(client, uid):
    status, payload = client.uid(
        "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])"
    )
    if status != "OK" or not payload:
        return None
    for part in payload:
        if isinstance(part, tuple) and isinstance(part[1], bytes):
            return message_headers(part[1])
    return None


def inbox_messages_for_date(source, target_date):
    config = source_config(source)
    start = datetime.fromisoformat(target_date).replace(tzinfo=MOSCOW)
    end = start + timedelta(days=1)
    records = []
    with imaplib.IMAP4_SSL(config["HOST"], int(config["PORT"])) as client:
        client.login(config["USER"], config["PASSWORD"])
        client.select("INBOX", readonly=True)
        status, matches = client.uid(
            "search", None, "SINCE", imap_date(start), "BEFORE", imap_date(end)
        )
        if status != "OK":
            raise RuntimeError("imap_search_failed")
        for uid in matches[0].split() if matches and matches[0] else []:
            headers = fetch_headers(client, uid)
            if headers and headers["rfcMessageId"]:
                records.append({
                    "source": source,
                    "mailbox": config["USER"],
                    "providerMessageId": uid.decode("ascii", errors="replace"),
                    **headers,
                })
    return records


def sent_mailbox(client):
    status, boxes = client.list()
    if status == "OK":
        for box in boxes or []:
            line = box.decode("utf-8", errors="replace") if isinstance(box, bytes) else str(box)
            if r"\Sent" in line:
                match = re.search(r'"([^"]+)"\s*$', line)
                if match:
                    return match.group(1)
    return "Sent"


def sent_reply_for(source, message_id):
    config = source_config(source)
    with imaplib.IMAP4_SSL(config["HOST"], int(config["PORT"])) as client:
        client.login(config["USER"], config["PASSWORD"])
        mailbox = sent_mailbox(client)
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            return None
        for header in ("IN-REPLY-TO", "REFERENCES"):
            status, matches = client.search(None, "HEADER", header, message_id)
            if status != "OK" or not matches or not matches[0]:
                continue
            sequence = matches[0].split()[-1]
            status, payload = client.fetch(sequence, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE)])")
            if status != "OK" or not payload:
                continue
            for part in payload:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    headers = message_headers(part[1])
                    return {
                        "source": source,
                        "rfcMessageId": message_id,
                        "answered": True,
                        "replyMessageId": headers["rfcMessageId"],
                        "answeredAt": headers["receivedAt"],
                        "matchConfidence": "header",
                    }
    return {"source": source, "rfcMessageId": message_id, "answered": False}


def collect_inbox_messages(target_date):
    records, errors = [], []
    for source in configured_sources():
        try:
            records.extend(inbox_messages_for_date(source, target_date))
        except Exception:
            errors.append(source)
    return records, errors


def lookup_sent_replies(items):
    results, errors = [], []
    for item in items:
        source = item.get("source", "")
        message_id = item.get("rfcMessageId", "")
        if not source or not message_id:
            continue
        try:
            results.append(sent_reply_for(source, message_id))
        except Exception:
            errors.append(source)
    return results, sorted(set(errors))

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
        # /internal routes are reachable only on the private mail-brief_n8n Docker network.
        # Existing /v1 routes retain bearer-token authentication.
        internal = self.path.startswith("/internal/")
        if not internal and not self.authorized():
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
            if self.path in ("/v1/messages", "/internal/messages"):
                target_date = payload.get("date", "")
                try:
                    datetime.fromisoformat(target_date)
                except (TypeError, ValueError):
                    raise ValueError("date must be YYYY-MM-DD")
                items, errors = collect_inbox_messages(target_date)
                self.reply(200, {"items": items, "errorSources": errors})
                return
            if self.path in ("/v1/reply-status", "/internal/reply-status"):
                records = payload.get("items", [])
                if not isinstance(records, list):
                    raise ValueError("items must be an array")
                items, errors = lookup_sent_replies(records)
                self.reply(200, {"items": items, "errorSources": errors})
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