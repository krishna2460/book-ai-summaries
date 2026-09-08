import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker needs standalone output; Vercel manages its own Next.js output.
  output: process.env.VERCEL ? undefined : "standalone",
};

export default nextConfig;
