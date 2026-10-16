import type { NextConfig } from "next";

/**
 * The browser never talks to FastAPI directly. Requests to /backend/* are proxied by the
 * Next.js server to API_INTERNAL_URL, so only ONE port (the web port) has to be reachable
 * from your browser. That matters on remote machines you reach through a single
 * forwarded port or a web-IDE port proxy.
 *
 * PUBLIC_PATH_PREFIX: the URL path under which the BROWSER sees this app when a reverse
 * proxy strips that prefix before forwarding, e.g. a browser-based VS Code (code-server)
 * port proxy:  https://<gateway>/<...>/proxy/<web-port>/  ->  PUBLIC_PATH_PREFIX=/<...>/proxy/<web-port>
 * The server still serves from "/", but scripts, styles and API calls are emitted with the
 * prefix so the browser requests them through the proxy. Leave empty for direct access.
 */
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
const publicPrefix = (process.env.PUBLIC_PATH_PREFIX ?? "").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  assetPrefix: publicPrefix || undefined,
  env: { NEXT_PUBLIC_BASE_PATH: publicPrefix },
  async rewrites() {
    const backend = { source: "/backend/:path*", destination: `${apiInternalUrl}/:path*` };
    if (!publicPrefix) return [backend];
    // Same build must also work when opened directly on the node (e.g. browser tests on
    // 127.0.0.1): map prefixed URLs back onto the app's real routes.
    return {
      beforeFiles: [
        { source: `${publicPrefix}/backend/:path*`, destination: `${apiInternalUrl}/:path*` },
        { source: `${publicPrefix}/:path*`, destination: "/:path*" },
        { source: publicPrefix, destination: "/" },
      ],
      afterFiles: [backend],
      fallback: [],
    };
  },
};

export default nextConfig;
