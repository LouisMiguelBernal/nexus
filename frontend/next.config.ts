import type { NextConfig } from "next";
import { config as loadDotenv } from "dotenv";
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

// Single source of truth: the repo-root .env (../.env relative to frontend/)
// We load it explicitly so the frontend and backend read from the same file -
// the user fills keys once and both sides pick them up. This overrides
// Next.js's default (which would read frontend/.env.local).
loadDotenv({ path: path.resolve(__dirname, "..", ".env") });

// Build stamp. VERSION is the one place the version number lives; the git SHA
// lets the status bar flag a frontend/backend mismatch (the packaged app has
// served stale builds before). Read at build/dev start and inlined by Next.
const ROOT = path.resolve(__dirname, "..");
const readVersion = (): string => {
  try {
    return fs.readFileSync(path.join(ROOT, "VERSION"), "utf8").trim() || "0.0.0";
  } catch {
    return "0.0.0";
  }
};
const readGitSha = (): string => {
  if (process.env.NEXUS_GIT_SHA) return process.env.NEXUS_GIT_SHA.slice(0, 12);
  try {
    return (
      execSync("git rev-parse --short=7 HEAD", { cwd: ROOT, stdio: ["ignore", "pipe", "ignore"] })
        .toString()
        .trim() || "unknown"
    );
  } catch {
    return "unknown";
  }
};

const nextConfig: NextConfig = {
  // Surface only the NEXT_PUBLIC_* vars the browser actually needs, plus the
  // build stamp. Server routes can still read any var via process.env.
  env: {
    ...(Object.fromEntries(
      Object.entries(process.env).filter(([k]) => k.startsWith("NEXT_PUBLIC_"))
    ) as Record<string, string>),
    NEXT_PUBLIC_NEXUS_VERSION: readVersion(),
    NEXT_PUBLIC_NEXUS_GIT_SHA: readGitSha(),
    NEXT_PUBLIC_NEXUS_BUILT_AT: new Date().toISOString(),
  },
};

export default nextConfig;
