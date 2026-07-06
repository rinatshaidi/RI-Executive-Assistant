[Back to main README](../README.md) | [Docs Guide](README.md) | [Architecture](architecture.md) | [Security](security.md) | [Roadmap](project-roadmap.md)

# AI Mail Assistant Deployment Overview

## Scope

This document explains the runtime shape that is confirmed by the public-safe workflow.

It is not a production runbook.

## What A Working Runtime Needs

The public-safe workflow shows that AI Mail Assistant needs:

- an `n8n` instance;
- three IMAP credentials for the inbox triggers;
- an `OpenAI` credential;
- a `Telegram Bot` credential;
- a `Google Sheets OAuth2` credential.

## Runtime Values In The Sanitized Workflow

The workflow also expects safe runtime mapping for values such as:

- `MAIL_AGENT_TELEGRAM_CHAT_ID`
- `REPLACE_WITH_GOOGLE_SHEET_ID`
- `REPLACE_WITH_SHEET_NAME`

These placeholders are safe to publish. Real values are not.

## Safe Setup Order

1. Create the needed credentials inside `n8n`.
2. Import the sanitized workflow from `n8n/`.
3. Replace placeholders in a private local environment.
4. Check Google Sheets mapping before activation.
5. Keep the workflow inactive until credential mapping and manual validation are complete.

## What This Public Repo Does Not Include

- mailbox login values;
- IMAP host details tied to private accounts;
- sheet IDs or live URLs;
- deployment scripts;
- infrastructure-as-code;
- CI/CD files;
- production environment variables.

## Important Note

The workflow in this repository is useful for review and controlled import work.

It is not a drop-in production workflow, because private mailbox and destination values are intentionally not published.

## Best Next Improvement

The most useful next deployment improvement would be a safe import checklist with placeholders only.