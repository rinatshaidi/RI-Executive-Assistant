# Executive Assistant

A practical personal `n8n` automation that turns several inboxes into one useful morning Telegram summary. It is designed for a person who wants to see what needs attention without opening every mailbox.

The project contains public-safe workflow templates and the private-network state
component used by RI Assistant. It never includes mailbox addresses, passwords,
OAuth tokens, Telegram chat IDs, email bodies, attachments, execution logs, or
API keys.

## RI Assistant

RI Assistant is the voice calendar component of the same Telegram bot. Its
technical specification is in
[`docs/ri-assistant-technical-spec.md`](docs/ri-assistant-technical-spec.md).

It uses a deliberately small hybrid architecture:

- n8n handles Telegram, voice transcription, AI extraction, Google Calendar,
  Morning agenda, and Mail Brief;
- `ri-assistant-core` is a small FastAPI service that holds only the temporary
  edit state for a conversation, preventing an edit request from becoming a new
  event;
- the service runs on a private Docker network and has no public port or
  third-party credentials.

The component is in [`ri-assistant-core`](ri-assistant-core). Copy
`.env.example` to `.env` only on the deployment host; never commit that file.

## Current workflow: Mail Brief

`Mail Brief` is the active personal workflow.

- Collects message metadata from Gmail and IMAP mailboxes into one internal n8n queue.
- Keeps only the source, received date, sender, subject, and processing date. It does not store message bodies or attachments.
- At 08:05 Moscow time, sends one Telegram briefing for the preceding day.
- Groups messages into 🔴 requires attention today, 🟡 this week, and ⚪ other.
- Shows the source mailbox under each red or yellow item, so the user knows where to act. The source is intentionally omitted from ⚪ other.
- Deletes the sent-day queue rows after delivery, preventing duplicate briefs.
- Does not use Google Sheets.

Example output:

```text
📬 Почта за 10.09

🔴 Требуют реакции сегодня — 2
• Банк — подтвердить платёж до 15:00
  📬 work-mail@example.com
• Клиника — требуется ответ
  📬 personal-mail@example.com

🟡 На этой неделе — 1
• Клиент — согласование документа

⚪ Прочее
8 рассылок · 2 уведомления · 1 рекламное письмо
```

## Templates

- [`n8n/mail-brief.workflow.json`](n8n/mail-brief.workflow.json) — current daily Mail Brief workflow.
- [`n8n/ai-mail-assistant.workflow.json`](n8n/ai-mail-assistant.workflow.json) — historical mail-agent template retained as a portfolio artifact; it includes its original Google Sheets path.

## Importing Mail Brief

1. Import `n8n/mail-brief.workflow.json` into n8n.
2. Create Gmail and IMAP credentials for your own mailboxes.
3. Create an internal n8n Data Table with the columns `source`, `receivedAt`, `from`, `subject`, and `briefDate`.
4. Replace `REPLACE_WITH_YOUR_DATA_TABLE_ID` in the Data Table nodes.
5. Add your Telegram credential and replace `YOUR_TELEGRAM_CHAT_ID`.
6. Add an OpenAI credential to the classification node.
7. Set the schedules for 08:00 and 08:05 Moscow time according to the server time zone, then activate the workflow.

## Structure

```text
mail-assistant/
├── n8n/
│   ├── mail-brief.workflow.json
│   └── ai-mail-assistant.workflow.json
├── docs/
│   └── voice-calendar-next.md
└── README.md
```

## Security

Do not commit IMAP app passwords, Telegram bot tokens, OpenAI API keys, OAuth credentials, live workflow exports, personal mailbox addresses, or Telegram chat IDs. See [docs/security.md](docs/security.md).
