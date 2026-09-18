import path from "node:path";
import type { NextConfig } from "next";
const config: NextConfig = {
  outputFileTracingRoot: path.resolve(__dirname, "../.."),
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_URL || "http://127.0.0.1:8000"}/:path*`,
      },
    ];
  },
};
export default config;
