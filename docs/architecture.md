[Back to main README](../README.md) | [Docs Guide](README.md) | [Deployment](deployment.md) | [Security](security.md) | [Roadmap](project-roadmap.md)

# AI Mail Assistant Architecture

## Scope

This document uses only what is confirmed by the public-safe workflow and the historical audit notes used to prepare it.

The historical workflow name inside `n8n` is `Mail Agent`.

## System In One View

![AI Mail Assistant architecture diagram](architecture-diagram.svg)

Text version:

1. One of three inbox triggers receives a new email.
2. The workflow normalizes the email fields.
3. It checks whether an attachment exists.
4. Spreadsheet and PDF files go through different extraction paths.
5. Email and attachment content are merged.
6. One AI branch builds an executive summary.
7. Another AI branch builds structured register JSON.
8. Telegram gets the summary. Google Sheets gets the register row.

## Main Components

- `n8n` runs the workflow.
- Three IMAP triggers handle inbound mail.
- File extraction nodes process PDF and spreadsheet attachments.
- One OpenAI branch creates a human summary.
- Another OpenAI branch creates structured register data.
- Google Sheets stores the final register row.
- Telegram receives the final summary.

## Workflow Stages

### 1. Intake

The historical workflow starts from three separate IMAP triggers.

That tells us the project was designed for more than one inbox, not for a single mailbox only.

### 2. Normalization

A `Set` node normalizes the main email fields before later steps use them.

This keeps the rest of the workflow more stable.

### 3. Attachment Routing

The workflow checks for an attachment.

If an attachment exists:

- spreadsheet files go into extraction and aggregation;
- PDF files go into text extraction.

If no attachment exists, the email can still continue through the workflow.

### 4. Merge Step

The email content and the extracted attachment content are merged into one payload.

This is important because both AI branches need the same context.

### 5. Two AI Branches

The workflow creates two different outputs from the same message:

- a short executive summary for Telegram;
- a structured JSON payload for a mail register.

This makes the workflow useful for both fast reading and later reporting.

## Important Hardening Change

One real fix matters a lot in this project.

The older design sent the Google Sheets append result into the same Telegram node used for the executive summary branch.

That design was brittle.

The GitHub-ready version removed that broken path, so the summary branch and the register branch are no longer mixed together in the wrong place.

## Structured Register Role

The structured branch fills business-friendly fields such as:

- date and sender;
- subject and category;
- priority and document type;
- organization and amount;
- summary and deadline;
- status, reply status, work status, and comment.

This makes the workflow more useful than a simple mail summary bot.

## Why This Architecture Is Strong

- It separates intake, extraction, AI generation, and final delivery.
- It uses one source email for two useful outputs.
- It supports attachment-aware routing.
- It stores structured business data, not only chat output.
- It shows real workflow repair work, not only a greenfield demo.

## Public Limits

This repository does not include:

- real mailbox addresses;
- live credentials;
- live sheet identifiers;
- private audit exports;
- end-to-end proof of a fresh successful live run in the audited environment.

That limit is intentional for the public version.