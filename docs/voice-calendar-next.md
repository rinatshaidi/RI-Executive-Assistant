# RI Assistant — voice calendar and notes implementation

This file is the implementation contract for the next working revision of the
Telegram assistant. It deliberately contains no bot token, OAuth credential,
Google Doc ID, or other private identifiers. The live n8n workflow keeps those
values in credentials or workflow configuration only.

## Scope of this release

- Telegram is the voice-first interface.
- The assistant understands natural Russian speech for calendar actions and
  voice notes.
- Every completed action returns a short text audit line. For a successful
  calendar change or saved note it also returns a brief voice response.
- Google Calendar remains the source of truth for timed events and all-day
  tasks.
- Google Docs stores raw voice notes in one rolling monthly document; the VPS
  does not store note text.
- Morning agenda is sent at 08:00 Europe/Moscow and explicitly reports an
  empty calendar.
- Siri, Apple Notes and background Telegram reminders are outside this
  release. Calendar-native notifications remain enabled on the user's devices.

## Intent contract

The AI extraction node must return one JSON object and must never perform a
Calendar change itself.

```json
{
  "intent": "create_timed_event | create_all_day_task | plan_tasks | relocate_event | choose_option | cancel | save_note | search_notes | unknown",
  "confidence": 0.0,
  "referenceDate": "YYYY-MM-DD",
  "title": "string or null",
  "start": "RFC3339 or null",
  "end": "RFC3339 or null",
  "durationMinutes": 30,
  "date": "YYYY-MM-DD or null",
  "tasks": [{"title": "string", "durationMinutes": 30, "location": "string or null"}],
  "window": {"start": "RFC3339", "end": "RFC3339"},
  "targetDescription": "string or null",
  "requestedTime": "RFC3339 or null",
  "noteText": "string or null",
  "spokenReply": "string"
}
```

Rules:

- If the user says "отбой", "не надо", "отмени создание", return `cancel`.
  No Calendar write is allowed.
- A task "в течение дня" becomes a Calendar all-day event with
  `start.date`, `end.date` (next day), and `transparency: transparent`.
- Ambiguity always produces a voice clarification. It never creates or moves
  an event based on a guess.
- For `plan_tasks`, the response is a proposal until the user says
  "подтверждаю" or names an offered option.

## n8n flow

### 1. Receive and acknowledge

1. **Telegram Trigger** listens for voice messages, text commands and callback
   queries from the RI Assistant bot.
2. **Callback acknowledgement** is the first node on every callback branch:
   call Telegram `answerCallbackQuery` immediately. This clears the Telegram
   spinner before Calendar work starts.
3. Voice messages use `getFile` -> speech-to-text. Text commands bypass
   transcription.
4. A single AI extraction node receives the transcript, current Moscow date,
   and active conversation state.

### 2. Create / plan / move

5. **Create timed event:** validate the supplied date-time in Europe/Moscow,
   create the Calendar event, then send a TTS voice response and the text
   audit line, for example: `Создано: Встреча — 17.09, 10:00–10:30.`
6. **All-day task:** create the transparent all-day Calendar event, then
   report: `Добавлено на 17.09: купить краску.`
7. **Plan several tasks:** get events for the requested window, calculate the
   proposed slots in n8n, and return them with buttons
   `Подтвердить план` and `Изменить`. Only confirmation creates events.
8. **Move event:** search Calendar by a narrow date interval and title. For
   an exact requested time, update after identifying one event. Otherwise call
   `/v1/relocation-options`, send up to three voice and button options, and
   save the selected event ID and options in short-lived n8n state.
9. **Cancel:** clear only pending state and answer `Ничего не добавляю.`
   It does not delete an existing Calendar event unless the request names an
   existing event and is confirmed by the user.

### 3. Notes

10. **Save note:** append the full transcript to the current monthly Google
    Doc with date/time and category. Reply: `Заметка сохранена.`
11. **Search notes:** query the monthly Google Doc; if no exact text is found,
    say so rather than inventing a result.
12. **Turn note into task:** read the target note, create either an all-day
    task or a proposal depending on the spoken request, then keep the source
    note unchanged.

### 4. Replies and buttons

- Text is the authoritative audit trail.
- TTS is sent only after successful state change. If TTS fails, send the text
  line and record an n8n execution warning; do not retry the Calendar write.
- Buttons use compact callback data carrying an action and a short opaque
  state key. Callback data must not expose titles, calendar IDs, note text, or
  credentials.
- After an action the bot edits or follows up to show one unambiguous result:
  `Перенесено на 15:30.` / `Отменено.` / `План подтверждён.`

## Morning agenda

Schedule: daily 08:00 `Europe/Moscow`.

The Calendar list branch must aggregate even zero returned items. Format:

```text
☀️ План на 17.09

10:00 — Встреча
15:00 — Забрать документы

📌 В течение дня
• Купить краску
```

For no events:

```text
☀️ План на 17.09

На сегодня запланированных мероприятий нет.
```

Buttons below the agenda: `Добавить голосом` and `Открыть календарь`. The
first opens a brief voice prompt; the second opens the Calendar URL. No
Telegram reminder branch is used in this release.

## Acceptance test

The release is accepted only after these six scenarios complete against the
production Telegram bot and Google Calendar:

1. Voice: a dated 30-minute event is created at the stated Moscow time; bot
   returns both a voice response and correct text audit line.
2. Voice: `отбой, ничего не ставь` creates no Calendar event.
3. Voice: an all-day task appears as an all-day transparent item.
4. Voice: three tasks are proposed only in free slots and are created only
   after `Подтвердить план`.
5. Voice: moving an ambiguous event presents options; selecting one clears the
   button spinner immediately and results in one Calendar update.
6. A manual Morning Agenda execution with zero events sends the explicit empty
   plan at the intended format. A scheduled run is then checked at 08:00
   Europe/Moscow.
