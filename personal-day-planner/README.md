# Personal Day Planner

Internal deterministic scheduling service for RI Assistant.

It accepts only normalized calendar events and tasks from n8n. It does not
store personal notes, read Google Calendar, call Telegram, or contain OAuth
credentials.

## Endpoints

- GET /health — unauthenticated health check.
- POST /v1/plan — proposes non-overlapping slots for tasks.
- POST /v1/relocation-options — returns up to three free alternatives for an event.

All authenticated calls require Authorization: Bearer PLANNER_API_TOKEN.

## Deployment

Run as a separate Docker Compose project on AI Prod 01. It has no public port
and is available only through the existing ri_cloud_n8n internal network.
Create the real .env directly on the server with mode 600.

## n8n integration contract

For a planning request, n8n sends a time window, calendarEvents, task list and
travelBufferMinutes. The response includes proposedEvents, unscheduled, and
detected conflicts. n8n must present the plan to RI and only create Calendar
events after a voice confirmation.
