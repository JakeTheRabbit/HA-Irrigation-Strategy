#!/usr/bin/env node
import { serveStdio } from "@modelcontextprotocol/server/stdio";
import { configFromEnv, HaClient, SafeError } from "./ha.js";
import { createServer } from "./server.js";

try {
  const ha = new HaClient(configFromEnv(process.env));
  const handle = serveStdio(() => createServer(ha));
  const shutdown = () => {
    void handle.close().finally(() => process.exit(0));
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
} catch (error) {
  // stdout belongs exclusively to MCP. Never print env values or error stacks.
  process.stderr.write(
    (error instanceof SafeError
      ? error.message
      : "Crop Steering MCP startup failed.") + "\n",
  );
  process.exitCode = 1;
}
