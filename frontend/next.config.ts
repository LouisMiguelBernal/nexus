import type { NextConfig } from "next";
import { config as loadDotenv } from "dotenv";
import path from "node:path";

// Single source of truth: repo-root .env at E:/nexus/.env
// We load it explicitly so the frontend and backend read from the same file -
// the user fills keys once and both sides pick them up. This overrides
// Next.js's default (which would read frontend/.env.local).
loadDotenv({ path: path.resolve(__dirname, "..", ".env") });

const nextConfig: NextConfig = {
  // Surface only the NEXT_PUBLIC_* vars the browser actually needs.
  // Server routes can still read any var via process.env.
  env: Object.fromEntries(
    Object.entries(process.env).filter(([k]) => k.startsWith("NEXT_PUBLIC_"))
  ) as Record<string, string>,
};

export default nextConfig;
