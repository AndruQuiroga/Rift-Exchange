import type { NextConfig } from "next";

const API_ORIGIN = process.env.RIFT_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // NEXT_DIST_DIR lets a production build run beside `next dev` (which owns .next) for local checks.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // The browser only ever talks to this origin; /api is proxied so session cookies stay first-party.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  images: { remotePatterns: [{ protocol: "http", hostname: "static.lolesports.com" }, { protocol: "https", hostname: "static.lolesports.com" }] },
};

export default nextConfig;
