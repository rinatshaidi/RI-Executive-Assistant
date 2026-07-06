[Back to main README](../README.md) | [Docs Guide](README.md) | [Architecture](architecture.md) | [Deployment](deployment.md) | [Roadmap](project-roadmap.md)

# AI Mail Assistant Security Notes

## Main Rule

This public repository shows workflow structure, not private operations.

If there is any doubt about a value, it should stay out of the public repo.

## Safe To Publish

- sanitized workflow structure;
- safe placeholders for runtime values;
- documentation based on confirmed project artifacts.

## Not Safe To Publish

- personal mailbox addresses;
- passwords, tokens, or API keys;
- OAuth credential data;
- real Telegram chat IDs;
- real Google Sheet IDs or URLs;
- webhook IDs;
- internal workflow IDs or runtime dumps;
- private audit notes and live environment details.

## What Was Removed Or Hidden

The public workflow version uses these protections:

- workflow ID was replaced with a public placeholder;
- workflow version ID was replaced with a public placeholder;
- node IDs were replaced with public placeholders;
- the live webhook ID on the Telegram node was replaced with a public placeholder;
- private destination values remain as placeholders only;
- live mailbox mapping documents were not included in this repo.

## Current Review Result

At the time of the latest review, this repository did not expose:

- personal email addresses;
- real chat IDs;
- secret values;
- real sheet IDs;
- `.env` contents;
- private audit exports.

## Review Checklist For Future Changes

Before publishing any new file, confirm all of the following:

1. no mailbox address or personal email is present;
2. no real credential value is present;
3. no real webhook or chat value is present;
4. no live sheet identifier is present;
5. no runtime dump or internal audit detail is present;
6. every kept value is needed for technical understanding.