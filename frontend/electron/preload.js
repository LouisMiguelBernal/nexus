/**
 * Nexus - Electron Preload Script
 * Minimal - no Node integration exposed to renderer.
 */

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("nexus", {
  platform: process.platform,
  isElectron: true,
});
