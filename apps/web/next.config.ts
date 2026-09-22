import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output ships a self-contained server.js with only the modules it
  // needs, which is what the runtime Docker stage copies (§A1).
  output: "standalone",

  // Nothing is fetched from the API on the server: Server Components render
  // layout shells only, and every authenticated request happens in the browser
  // through the same origin Caddy serves (§A11). So no rewrites, no proxy, no
  // API routes — deliberately (§A0).
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
