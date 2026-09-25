import { Container } from "@cloudflare/containers";

export class GrokCellPreflight extends Container {
  defaultPort = 8080;
  sleepAfter = "1m";
}

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    if (path !== "/healthz" && path !== "/preflight") {
      return json(404, { error: "not_found" });
    }
    if (request.method !== "GET") {
      return json(405, { error: "method_not_allowed" });
    }
    return env.GROKCELL_PREFLIGHT.getByName("read-only").fetch(request);
  },
};
