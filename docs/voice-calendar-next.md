# Voice Calendar — next workflow revision

This document describes the next revision of the personal Telegram voice-calendar flow. It is deliberately a specification, not a production export: live n8n exports contain instance-specific credential references and must stay outside Git.

## Accepted voice intents

1. **Timed event**
   Example: “Tomorrow at 15:00, meeting with Ivan for 30 minutes.”
   Create one normal Google Calendar event in Europe/Moscow.

2. **Tasks in free slots**
   Example: “Tomorrow from 08:00 to 10:00, distribute: call Ivan, prepare documents, pay the invoice.”
   Read the calendar inside the requested window, exclude busy events, then create tasks sequentially in available gaps. A task with no specified duration receives 30 minutes. If the available time is insufficient, create only the tasks that fit and state that the remaining tasks were not scheduled.

3. **All-day task**
   Example: “Tomorrow, buy paint during the day.”
   Create a real all-day Google Calendar event using start.date and end.date, with transparency: transparent. It must not occupy a timed free slot and must sync to Apple Calendar as an all-day item.

4. **Cancellation**
   Example: “Never mind, do not add anything.”
   Do not create an event; return one brief acknowledgement.

## Morning agenda presentation

Timed events are listed as HH:mm — title. All-day tasks are grouped separately:

    ☀️ План на 14.09

    10:00 — Звонок
    15:00 — Совещание

    📌 В течение дня
    • Купить краску

If the calendar is empty, the message remains explicit:

    ☀️ План на 14.09

    На сегодня запланированных мероприятий нет.

## Acceptance checks

- A multi-task request never overlaps an opaque calendar event.
- A task labelled “during the day” is an actual all-day event, not a midnight timed event.
- All generated date-times use Europe/Moscow.
- The response shows the created slots in one compact Telegram message.
- The deployment test uses an actual voice message and verifies both Google Calendar and Telegram output.

## Current delivery state

The source workflow has been backed up and an importable working copy was generated locally. It has not yet been loaded into the production n8n instance, so the live workflow remains unchanged until the import and acceptance tests are performed.
