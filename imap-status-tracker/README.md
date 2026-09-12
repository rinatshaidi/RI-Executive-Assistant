# IMAP Status Tracker

This optional companion container lets Mail Brief verify, once a day, whether an important IMAP email is still unread. n8n by itself cannot reliably retain and revisit an IMAP message by its RFC `Message-ID`.

## Privacy boundary

The local SQLite data contains only a mailbox alias, RFC `Message-ID`, optional sender and subject, and timestamps. It never stores an email body, attachment, OAuth token, or Telegram data. IMAP app passwords stay only in the server-side `.env`, which is excluded from Git.

## Daily operation

The container runs one status check at **07:30 Europe/Moscow** by default. It opens each tracked IMAP Inbox in read-only mode, inspects the matching message flags, and removes the item from its pending list after the email is read. The schedule is configurable through `TRACKER_REFRESH_HOUR` and `TRACKER_REFRESH_MINUTE`.

## n8n interface

- `POST /v1/important` registers important email metadata after classification.
- `GET /v1/unread-important` returns the status produced at the last daily check.
- `POST /v1/refresh` is a protected manual diagnostic endpoint; it is not used by the daily workflow.
- `GET /health` exposes readiness and the next scheduled check, without private email data.

All `/v1/*` endpoints require a bearer token.

## Deployment

On AI Prod 01, copy `.env.example` to `.env` once and enter each mailbox app password there. Start with `docker compose -p mail-brief up -d --build`. The container has no public port and is reachable only from the private Mail Brief / RI Cloud n8n Docker network.

Gmail unread state remains in the existing Gmail OAuth branch because it does not use an IMAP app password.

## Acceptance test

Register one known important IMAP email, confirm it appears in `GET /v1/unread-important`, read it in the mailbox, then let the next 07:30 check run (or use the protected diagnostic endpoint once). It must disappear from the returned list.