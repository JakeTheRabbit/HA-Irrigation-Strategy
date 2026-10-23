/** Loopback server for the compiled dashboard (www/dashboard.html), for scripts that take a URL. */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

export async function serveDashboard() {
  const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
  const server = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    res.end(html);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    origin: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}
