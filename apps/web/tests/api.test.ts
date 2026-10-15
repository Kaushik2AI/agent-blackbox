import { describe, expect, it } from "vitest";
import { checkConnectivity } from "../lib/api";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const health = { status: "ok", service: "agent-blackbox-api", environment: "test" };
const check = (ok: boolean) => ({ ok, latency_ms: 1.2, detail: ok ? "fine" : "down" });

function fakeFetch(routes: Record<string, () => Response | Promise<Response>>) {
  return async (url: string) => {
    const key = Object.keys(routes).find((k) => url.endsWith(k));
    if (!key) throw new TypeError(`fetch failed: ${url}`);
    return routes[key]();
  };
}

describe("checkConnectivity (unit)", () => {
  it("reports ready only when /readyz says ready", async () => {
    const state = await checkConnectivity(
      fakeFetch({
        "/healthz": () => json(200, health),
        "/readyz": () => json(200, { status: "ready", checks: { database: check(true), redis: check(true) } }),
      }),
      "/backend",
    );
    expect(state.kind).toBe("ready");
  });

  it("reports degraded when /readyz returns 503", async () => {
    const state = await checkConnectivity(
      fakeFetch({
        "/healthz": () => json(200, health),
        "/readyz": () => json(503, { status: "not_ready", checks: { database: check(false), redis: check(true) } }),
      }),
      "/backend",
    );
    expect(state.kind).toBe("degraded");
  });

  it("reports unreachable on network failure instead of assuming success", async () => {
    const state = await checkConnectivity(fakeFetch({}), "/backend");
    expect(state.kind).toBe("unreachable");
    if (state.kind === "unreachable") expect(state.reason).toMatch(/fetch failed/);
  });

  it("reports unreachable when the proxy returns HTML (API process down)", async () => {
    const state = await checkConnectivity(
      fakeFetch({ "/healthz": () => new Response("<html>502</html>", { status: 502 }) }),
      "/backend",
    );
    expect(state.kind).toBe("unreachable");
  });
});

// Smoke test against a running stack. `make test-web-smoke` sets SMOKE_BASE_URL to the
// web server's /backend proxy, so this exercises browser path -> Next.js -> FastAPI.
const smokeBase = process.env.SMOKE_BASE_URL;
describe.skipIf(!smokeBase)("checkConnectivity (live smoke)", () => {
  it("reaches the real API through the Next.js proxy and it is ready", async () => {
    const state = await checkConnectivity(fetch, smokeBase!);
    expect(state, JSON.stringify(state)).toMatchObject({ kind: "ready" });
  });
});
