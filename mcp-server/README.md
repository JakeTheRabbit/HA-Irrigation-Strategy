# Crop Steering MCP

Connect an MCP-compatible assistant to an existing Crop Steering installation in Home Assistant. This is a **local stdio server**: the assistant launches a Node process, and the process calls a fixed Home Assistant API. It opens no HTTP listener.

Reads and previews work by default. Configuration saves require an explicit environment opt-in, a reviewed proposal, unchanged source configuration, Home Assistant validation, and successful readback. There are no tools for operating pumps, valves, engine switches, manual overrides, or activating grow plans.

## Install

Use Node.js 22 or newer. From your checkout:

Clone this repository or download **crop_steering_mcp_source.zip** from the [latest GitHub release](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/latest), then extract it before running:

```sh
cd mcp-server
npm ci
npm run build
npm test
```

The server entry point is `mcp-server/dist/index.js`. Configure the host to run `node` with that **absolute** file path. Do not use `npm start` as the stdio command: npm can print text to stdout, which belongs to the protocol.

This private package is installed from source; it is not published to npm. Updates require pulling the reviewed source, running `npm ci`, rebuilding, and restarting your MCP host.

## Claude Desktop

Open Settings → Developer → Edit Config, merge this entry into `mcpServers`, and restart Claude Desktop. Replace the paths and placeholders. On Windows, forward slashes in absolute paths are convenient; escaped backslashes also work.

```json
{
  "mcpServers": {
    "crop-steering": {
      "command": "node",
      "args": ["C:/path/to/HA-Irrigation-Strategy/mcp-server/dist/index.js"],
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "REPLACE_WITH_YOUR_PRIVATE_HA_TOKEN"
      }
    }
  }
}
```

Use the absolute Node executable path if the desktop host cannot find `node`. Keep the configuration file private; never commit a real token. The connection format follows the [official local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

For another stdio-capable MCP host, configure the same command, argument and environment variables. The host must launch a persistent process and speak MCP over stdin/stdout. This package does not provide a remote connector URL or claim support for hosts that only accept HTTP connectors.

## First workflow

Ask the assistant to list rooms, read one room's configuration, search candidate sensors if needed, and preview your requested changes. Read the complete diff. If you want it saved, enable writes in the host environment and restart; make a fresh preview because proposals are held only in that process. Authorize the exact proposal before it calls `apply_proposal`.

```json
"CROP_STEERING_ALLOW_WRITES": "true"
```

The token is single-use and expires after ten minutes. It binds the exact payload; it cannot prove that a human reviewed it. Leave your MCP host's approval for `apply_proposal` enabled.

See [the full guide](../docs/MCP.md) for tool schemas, Home Assistant prerequisites, scope, failure handling, and verification evidence.
