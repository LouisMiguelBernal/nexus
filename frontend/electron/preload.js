/**
 * Nexus - Electron Preload Script
 *
 * Runs sandboxed with context isolation. Exposes only what the renderer needs:
 * the platform, an "is Electron" flag, and the local API token the main process
 * passes in via additionalArguments (see main.js ensureApiToken). No Node APIs
 * reach the page.
 */

const { contextBridge } = require("electron");

const TOKEN_FLAG = "--nexus-api-token=";
const tokenArg = process.argv.find((arg) => arg.startsWith(TOKEN_FLAG));

contextBridge.exposeInMainWorld("nexus", {
  platform: process.platform,
  isElectron: true,
  apiToken: tokenArg ? tokenArg.slice(TOKEN_FLAG.length) : null,
});
