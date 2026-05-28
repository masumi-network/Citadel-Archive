# Citadel Archive Obsidian Plugin

This is the private beta companion plugin for Citadel Archive.

## Capabilities

- Connects to a Citadel HTTP server with a bearer token.
- Stores the token through Obsidian `SecretStorage`.
- Registers the current vault as an `obsidian_vault` source.
- Searches Citadel from a side pane.
- Pushes the active Markdown note or current selection to Citadel.

## Security Notes

- The plugin does not add telemetry.
- Note content is only sent when a user runs an explicit ingest command.
- HTTPS is expected for hosted Citadel servers. `localhost` is acceptable for local development.
- Full bidirectional sync is intentionally out of scope for this first version.

## Development

```bash
npm install
npm run dev
```

Copy `main.js`, `manifest.json`, and `styles.css` into an Obsidian vault plugin
folder named `.obsidian/plugins/citadel-archive`.
