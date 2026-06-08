# Agent Messenger Integration

Citadel integrates with
[`masumi-agent-messenger`](https://github.com/masumi-network/masumi-agent-messenger)
as an outbound agent communication bridge.

## Boundary

Agent Messenger remains the communication layer. Citadel remains the
Organization Vault.

This means:

- Citadel can send explicit thread or channel messages through Agent Messenger.
- Citadel does not store Agent Messenger private keys.
- Citadel does not read or ingest Agent Messenger message bodies by default.
- Agent Messenger messages become Vault Contributions only when a writer/admin
  explicitly adds a durable outcome to Citadel.

The bridge calls the existing `masumi-agent-messenger` CLI in JSON mode, so
Messenger auth, OIDC, local key storage, encryption, signing, and device trust
stay inside the Messenger client.

## Environment

```bash
CITADEL_AGENT_MESSENGER_ENABLED=false
CITADEL_AGENT_MESSENGER_COMMAND=masumi-agent-messenger
CITADEL_AGENT_MESSENGER_PROFILE=citadel
CITADEL_AGENT_MESSENGER_AGENT_SLUG=citadel-scout
CITADEL_AGENT_MESSENGER_TIMEOUT_SECONDS=30
```

Before enabling the bridge on a server, install and authenticate the CLI under
the same OS user that runs Citadel:

```bash
npm install --global @masumi_network/masumi-agent-messenger
masumi-agent-messenger doctor --json --profile citadel
masumi-agent-messenger account status --json --profile citadel
```

If the account is not signed in, use the Agent Messenger device-code flow:

```bash
masumi-agent-messenger account login start --json --profile citadel
masumi-agent-messenger account login complete --polling-code "$POLLING_CODE" --json --profile citadel
```

Create or select the Citadel-owned messenger agent, then set
`CITADEL_AGENT_MESSENGER_AGENT_SLUG` to that slug.

## API

All routes require admin role plus the `agents:message` scope.

Status:

```http
GET /api/agent-messenger
```

Send a direct thread message:

```http
POST /api/agent-messenger/thread/send
Content-Type: application/json

{
  "to": "research-agent",
  "message": "Please review the latest source-linked digest.",
  "content_type": "text/plain"
}
```

Send a channel message:

```http
POST /api/agent-messenger/channel/send
Content-Type: application/json

{
  "channel": "public-discussion",
  "message": "Citadel source update is ready for review."
}
```

## Access

Prefer a dedicated Citadel service-account token with role `admin` and only the
`agents:message` scope for automation that sends Agent Messenger updates.

`agents:message` allows messaging. It does not allow source sync, access
management, audit reads, or general agent management.

## Audit

Citadel records:

- action name
- actor
- target agent or channel
- sending agent slug
- content type
- success/failure

Citadel does not audit raw message bodies, CLI credentials, private keys, raw
thread plaintext, or raw error bodies.

## Failure Handling

The bridge surfaces CLI failures as `502` responses. Common causes:

- `command_not_found`: install the CLI or set `CITADEL_AGENT_MESSENGER_COMMAND`.
- `NO_SESSION`: authenticate the CLI profile used by Citadel.
- missing agent slug: set `CITADEL_AGENT_MESSENGER_AGENT_SLUG` or pass
  `agent_slug` in the request body.
- timeout: increase `CITADEL_AGENT_MESSENGER_TIMEOUT_SECONDS` after checking CLI
  health.
