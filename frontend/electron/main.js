/**
 * Nexus - Electron Main Process (the version number lives in the root VERSION file)
 * One-click launcher: starts Next.js dev server + Python backend automatically.
 * Pinnable to taskbar, runs as standalone app.
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, shell } = require("electron");
const path = require("path");
const { spawn, execSync } = require("child_process");
const http = require("http");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");

let mainWindow = null;
let tray = null;
let backendProcess = null;
let nextProcess = null;
let splashWindow = null;

const APP_ID = "com.nexus.terminal";
const NEXT_PORT = 3000;
const API_PORT = 8001;
const OLLAMA_PORT = 11434;

// When packaged as an installer, __dirname lives inside the installed app
// (%LOCALAPPDATA%\Programs\Nexus\resources\app.asar\electron) - not at
// the repository root. The launcher always orchestrates the real codebase, so resolve
// FRONTEND_DIR / PROJECT_DIR to absolute paths when packaged. Override via
// NEXUS_HOME env var if you ever move the project.
const NEXUS_HOME = process.env.NEXUS_HOME || path.join("E:", "Personal Projects & Tech Stack", "nexus");
const IS_PACKAGED = app.isPackaged;
const FRONTEND_DIR = IS_PACKAGED ? path.join(NEXUS_HOME, "frontend") : path.join(__dirname, "..");
const PROJECT_DIR  = IS_PACKAGED ? NEXUS_HOME                          : path.join(__dirname, "..", "..");
const ICON_PATH = path.join(__dirname, "icon.ico");
const ICON_PNG  = path.join(__dirname, "icon.png");

// Production mode = use pre-built .next via `next start` (≈2s cold start).
// Dev mode = `next dev` with HMR (≈15s, watches source).
// Packaged installs always run production.
const IS_PROD = IS_PACKAGED || process.env.NODE_ENV === "production";
let ollamaProcess = null;

// Runtime data (SQLite, logs, API token). Mirrors backend.config.NEXUS_DATA_DIR.
const DATA_DIR = process.env.NEXUS_DATA_DIR || path.join(PROJECT_DIR, "data");
const TOKEN_FILE = path.join(DATA_DIR, "api_token");

// Local API token shared with the backend, which enforces it on /api/*. We hand
// it to the backend via env, inject it into every renderer request to the API
// at the network layer, and expose it to the preload for the fetch shim.
function ensureApiToken() {
  if (process.env.NEXUS_API_TOKEN) return process.env.NEXUS_API_TOKEN;
  try {
    const existing = fs.readFileSync(TOKEN_FILE, "utf8").trim();
    if (existing) return existing;
  } catch {
    /* first run */
  }
  const token = crypto.randomBytes(32).toString("base64url");
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(TOKEN_FILE, token + "\n", { mode: 0o600 });
    console.log("[Auth] generated API token at " + TOKEN_FILE);
  } catch (e) {
    console.warn("[Auth] could not persist API token: " + e.message);
  }
  return token;
}
const API_TOKEN = ensureApiToken();

// Windows taskbar pinning & jumplist grouping key.
// MUST be set BEFORE any window is created, otherwise pinned shortcuts will
// create a duplicate taskbar entry instead of attaching to the existing one.
if (process.platform === "win32") {
  app.setAppUserModelId(APP_ID);
}

// ---------------------------------------------------------------------------
// Splash screen while loading
// ---------------------------------------------------------------------------
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 400,
    height: 250,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });

  // Obsidian/silver splash matching the new design system
  const html = `data:text/html,
    <html>
    <body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;
      background:rgba(14,14,14,0.96);border-radius:14px;
      border:1px solid rgba(198,198,199,0.18);
      box-shadow:0 20px 60px rgba(0,0,0,0.5),inset 0 1px 0 rgba(255,255,255,0.06);
      font-family:'Inter','Segoe UI',system-ui,sans-serif;color:%23e7e5e4;
      flex-direction:column;gap:10px;">
      <div style="font-size:30px;font-weight:800;letter-spacing:0.22em;
        background:linear-gradient(180deg,%23f0f0f0,%23a8a8a9);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;
        background-clip:text;color:transparent;">NEXUS</div>
      <div style="font-size:10px;color:%23acabaa;letter-spacing:0.18em;text-transform:uppercase;">Institutional Terminal</div>
      <div style="margin-top:14px;font-size:9px;color:%23767575;letter-spacing:0.14em;text-transform:uppercase;" id="status">Starting systems</div>
      <div style="width:220px;height:2px;background:%23252626;border-radius:1px;overflow:hidden;margin-top:6px;">
        <div style="width:20%25;height:100%25;background:linear-gradient(90deg,%23484848,%23c6c6c7,%23484848);border-radius:1px;animation:load 1.8s ease-in-out infinite;"></div>
      </div>
      <style>@keyframes load{0%25{width:20%25;margin-left:0}50%25{width:70%25;margin-left:30%25}100%25{width:20%25;margin-left:80%25}}</style>
    </body>
    </html>`;

  splashWindow.loadURL(html);
  splashWindow.center();
}

// ---------------------------------------------------------------------------
// Start Ollama if not already running (Gemma 4 inference backend)
// ---------------------------------------------------------------------------
function startOllama() {
  return new Promise((resolve) => {
    checkPort(OLLAMA_PORT, (inUse) => {
      if (inUse) {
        console.log("[Ollama] Already running on port " + OLLAMA_PORT);
        resolve();
        return;
      }
      const bin = resolveOllamaBin();
      console.log("[Ollama] Not detected - starting via " + bin);
      try {
        ollamaProcess = spawn(bin, ["serve"], {
          stdio: "ignore",
          // Don't use a shell: with a resolved absolute path it adds nothing
          // and breaks on install paths containing spaces.
          shell: bin === "ollama",
          detached: true,
          windowsHide: true,
        });
        ollamaProcess.unref();
        ollamaProcess.on("error", (err) => {
          console.error("[Ollama] spawn failed: " + err.message);
        });
        // 8s was not enough to be conclusive, and resolving silently meant a
        // dead Ollama looked identical to a healthy one at startup. Wait 30s
        // and say plainly which happened - the AI brief depends on it.
        const start = Date.now();
        const poll = () => {
          if (Date.now() - start > 30000) {
            console.error(
              "[Ollama] STILL DOWN on port " + OLLAMA_PORT +
              " after 30s - AI briefs will fail until 'ollama serve' is running."
            );
            resolve();
            return;
          }
          checkPort(OLLAMA_PORT, (up) => {
            if (up) {
              console.log("[Ollama] up after " + Math.round((Date.now() - start) / 1000) + "s");
              resolve();
            } else {
              setTimeout(poll, 400);
            }
          });
        };
        poll();
      } catch (e) {
        console.error("[Ollama] Could not start automatically:", e.message);
        resolve(); // AI features degrade, but the terminal still runs
      }
    });
  });
}

// Locate the ollama binary. Relying on PATH alone is fragile: Electron does
// not always inherit the user's interactive PATH, and a bare spawn("ollama")
// failing is indistinguishable from Ollama simply being slow to bind.
function resolveOllamaBin() {
  const candidates = [
    process.env.OLLAMA_PATH,
    path.join(os.homedir(), "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
    "C:\\Program Files\\Ollama\\ollama.exe",
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
  ].filter(Boolean);
  for (const c of candidates) {
    try { if (fs.existsSync(c)) return c; } catch { /* keep looking */ }
  }
  return "ollama"; // last resort: hope it is on PATH
}

// ---------------------------------------------------------------------------
// Start Next.js dev server
// ---------------------------------------------------------------------------
function startNextDev() {
  return new Promise((resolve) => {
    // Check if Next.js is already running
    checkPort(NEXT_PORT, (inUse) => {
      if (inUse) {
        console.log("[Next.js] Already running on port " + NEXT_PORT);
        resolve();
        return;
      }

      const nextCli = path.join(FRONTEND_DIR, "node_modules", "next", "dist", "bin", "next");
      const nextScript = IS_PROD ? "start" : "dev";
      console.log(`[Next.js] Launching '${nextScript}' (${IS_PROD ? "production" : "development"} mode)`);
      // Launch next's JS entry directly under node. Do NOT go through npm.cmd /
      // shell:true - npm's .cmd shim corrupts any path containing '&' (this
      // project lives under "Personal Projects & Tech Stack").
      nextProcess = spawn(process.execPath, [nextCli, nextScript, "--port", String(NEXT_PORT)], {
        cwd: FRONTEND_DIR,
        stdio: "pipe",
        windowsHide: true,
        env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
      });

      nextProcess.stdout.on("data", (data) => {
        const msg = data.toString();
        console.log(`[Next.js] ${msg.trim()}`);
        // 'next dev' prints "Ready in …", 'next start' prints "Ready on …" / "started server on"
        if (msg.includes("Ready in") || msg.includes("Ready on") || msg.includes("started server") || msg.includes("localhost:" + NEXT_PORT)) {
          resolve();
        }
      });

      nextProcess.stderr.on("data", (data) => {
        console.log(`[Next.js] ${data.toString().trim()}`);
      });

      nextProcess.on("error", (err) => {
        console.error("Failed to start Next.js:", err);
        resolve(); // Don't block
      });

      // Fallback: resolve after 15 seconds even if no "Ready" message
      setTimeout(resolve, 15000);
    });
  });
}

// ---------------------------------------------------------------------------
// Start Python FastAPI backend
// ---------------------------------------------------------------------------
function startBackend() {
  return new Promise((resolve) => {
    checkPort(API_PORT, (inUse) => {
      if (inUse) {
        console.log("[Backend] Already running on port " + API_PORT);
        resolve();
        return;
      }

      const pythonCmd = process.platform === "win32" ? "python" : "python3";
      // Loopback only: the API serves signed exchange-account reads and must not
      // be reachable from the LAN. The token and data dir travel via env.
      backendProcess = spawn(pythonCmd, ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)], {
        cwd: PROJECT_DIR,
        stdio: "pipe",
        windowsHide: true,
        env: { ...process.env, NEXUS_API_TOKEN: API_TOKEN, NEXUS_DATA_DIR: DATA_DIR },
      });

      backendProcess.stdout.on("data", (data) => {
        const msg = data.toString();
        console.log(`[Backend] ${msg.trim()}`);
        if (msg.includes("Application startup complete") || msg.includes("Uvicorn running")) {
          resolve();
        }
      });

      backendProcess.stderr.on("data", (data) => {
        const msg = data.toString();
        console.log(`[Backend] ${msg.trim()}`);
        if (msg.includes("Application startup complete") || msg.includes("Uvicorn running")) {
          resolve();
        }
      });

      backendProcess.on("error", (err) => {
        console.error("Failed to start backend:", err);
        resolve();
      });

      backendProcess.on("close", (code) => {
        console.log(`Backend exited with code ${code}`);
        backendProcess = null;
      });

      // Fallback: resolve after 20 seconds
      setTimeout(resolve, 20000);
    });
  });
}

// ---------------------------------------------------------------------------
// Main window
// ---------------------------------------------------------------------------
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1200,
    minHeight: 800,
    title: "Nexus",
    icon: ICON_PATH,
    backgroundColor: "#0e0e0e",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      preload: path.join(__dirname, "preload.js"),
      // Read by preload.js and exposed as window.nexus.apiToken.
      additionalArguments: ["--nexus-api-token=" + API_TOKEN],
    },
  });

  // Reinforce the AUMID on the window so pinned taskbar icons stay grouped.
  if (process.platform === "win32") {
    try { mainWindow.setAppDetails({ appId: APP_ID, relaunchDisplayName: "Nexus" }); } catch { /* ignore */ }
  }

  // Belt and braces: attach the API token to every renderer request to the
  // backend at the network layer, so even a frontend bundle that predates the
  // fetch shim keeps working once the backend enforces auth.
  mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: [`http://127.0.0.1:${API_PORT}/*`, `http://localhost:${API_PORT}/*`] },
    (details, callback) => {
      if (!details.requestHeaders["Authorization"]) {
        details.requestHeaders["Authorization"] = "Bearer " + API_TOKEN;
      }
      callback({ requestHeaders: details.requestHeaders });
    }
  );

  const loadApp = () => mainWindow.loadURL(`http://localhost:${NEXT_PORT}`);
  loadApp();

  mainWindow.webContents.on("did-finish-load", () => {
    console.log("[Nexus] Frontend loaded");
    if (splashWindow) {
      try { splashWindow.destroy(); } catch { /* ignore */ }
      splashWindow = null;
    }
    mainWindow.show();
    mainWindow.focus();
  });

  // If loadURL fails (e.g. Next.js not yet serving), retry a few times
  let loadRetries = 0;
  mainWindow.webContents.on("did-fail-load", (_e, errorCode, errorDesc) => {
    if (loadRetries++ < 10) {
      console.warn(`[Nexus] Load failed (${errorCode} ${errorDesc}), retrying in 1s (${loadRetries}/10)`);
      setTimeout(loadApp, 1000);
    } else {
      console.error(`[Nexus] Giving up after 10 reloads: ${errorDesc}`);
    }
  });

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Keep the renderer on the app origin; anything else opens in the browser.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(`http://localhost:${NEXT_PORT}`)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.on("close", (event) => {
    if (tray) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ---------------------------------------------------------------------------
// System tray
// ---------------------------------------------------------------------------
function createTray() {
  let trayIcon;
  try {
    // Load from PNG and resize for tray (Windows tray prefers 16x16 / 32x32)
    const img = nativeImage.createFromPath(ICON_PNG);
    if (img.isEmpty()) throw new Error("PNG empty, fallback to ICO");
    trayIcon = img.resize({ width: 16, height: 16 });
  } catch {
    try { trayIcon = nativeImage.createFromPath(ICON_PATH); }
    catch { trayIcon = nativeImage.createEmpty(); }
  }
  try {
    tray = new Tray(trayIcon);
  } catch {
    tray = new Tray(nativeImage.createEmpty());
  }

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Open Nexus",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: "separator" },
    {
      label: "Health Check",
      click: () => shell.openExternal(`http://localhost:${API_PORT}/api/health`),
    },
    {
      label: "API Docs",
      click: () => shell.openExternal(`http://localhost:${API_PORT}/docs`),
    },
    { type: "separator" },
    {
      label: "Restart Backend",
      click: async () => {
        killTree(backendProcess);
        backendProcess = null;
        await startBackend();
      },
    },
    { type: "separator" },
    {
      label: "Quit Nexus",
      click: () => {
        tray = null;
        cleanup();
        app.quit();
      },
    },
  ]);

  tray.setToolTip("Nexus - Crypto Trading Terminal");
  tray.setContextMenu(contextMenu);

  tray.on("double-click", () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ---------------------------------------------------------------------------
// Cleanup - kill entire process trees on Windows to avoid orphan uvicorn/next
// ---------------------------------------------------------------------------
function killTree(proc) {
  if (!proc || !proc.pid) return;
  try {
    if (process.platform === "win32") {
      execSync(`taskkill /pid ${proc.pid} /T /F`, { stdio: "ignore", windowsHide: true });
    } else {
      try { process.kill(-proc.pid, "SIGTERM"); } catch { proc.kill("SIGTERM"); }
    }
  } catch { /* ignore */ }
}

function cleanup() {
  killTree(backendProcess);
  backendProcess = null;
  killTree(nextProcess);
  nextProcess = null;
}

// ---------------------------------------------------------------------------
// Port check helper (guarded against double-fire)
// ---------------------------------------------------------------------------
function checkPort(port, callback) {
  let done = false;
  const finish = (v) => { if (!done) { done = true; callback(v); } };
  const req = http.request({ host: "127.0.0.1", port, timeout: 1000 }, () => {
    finish(true);
  });
  req.on("error", () => finish(false));
  req.on("timeout", () => { req.destroy(); finish(false); });
  req.end();
}

// ---------------------------------------------------------------------------
// Kill any process holding a port (Windows-safe) - used on startup to reclaim
// stale 3000/8001 from previously orphaned runs.
// ---------------------------------------------------------------------------
function killPortProcess(port) {
  try {
    if (process.platform === "win32") {
      const out = execSync(`netstat -ano -p TCP | findstr :${port}`, {
        stdio: ["ignore", "pipe", "ignore"], windowsHide: true,
      }).toString();
      const pids = new Set();
      for (const line of out.split(/\r?\n/)) {
        const m = line.match(/LISTENING\s+(\d+)/);
        if (m) pids.add(m[1]);
      }
      for (const pid of pids) {
        try {
          execSync(`taskkill /pid ${pid} /T /F`, { stdio: "ignore", windowsHide: true });
          console.log(`[Nexus] Killed stale process ${pid} holding port ${port}`);
        } catch { /* ignore */ }
      }
    } else {
      try { execSync(`fuser -k ${port}/tcp`, { stdio: "ignore" }); } catch { /* ignore */ }
    }
  } catch { /* nothing listening */ }
}

// ---------------------------------------------------------------------------
// Wait for port to be ready
// ---------------------------------------------------------------------------
function waitForPort(port, timeout = 30000) {
  return new Promise((resolve) => {
    const start = Date.now();
    const check = () => {
      if (Date.now() - start > timeout) {
        resolve(false);
        return;
      }
      checkPort(port, (inUse) => {
        if (inUse) {
          resolve(true);
        } else {
          setTimeout(check, 500);
        }
      });
    };
    check();
  });
}

// ---------------------------------------------------------------------------
// Single instance lock
// ---------------------------------------------------------------------------
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    // Handle jumplist commands even when the app is already running
    if (argv.includes("--open-health")) {
      shell.openExternal(`http://localhost:${API_PORT}/api/health`);
    } else if (argv.includes("--open-docs")) {
      shell.openExternal(`http://localhost:${API_PORT}/docs`);
    }
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    // Windows jumplist - right-click the pinned taskbar icon to see these
    if (process.platform === "win32") {
      try {
        app.setJumpList([
          {
            type: "custom",
            name: "Quick Actions",
            items: [
              {
                type: "task",
                title: "Open Health Dashboard",
                program: process.execPath,
                args: `--open-health`,
                iconPath: ICON_PATH,
                iconIndex: 0,
                description: "Open the API health endpoint",
              },
              {
                type: "task",
                title: "Open API Docs",
                program: process.execPath,
                args: `--open-docs`,
                iconPath: ICON_PATH,
                iconIndex: 0,
                description: "Open FastAPI /docs",
              },
            ],
          },
        ]);
      } catch (e) { console.warn("JumpList unavailable:", e.message); }
    }

    createSplash();
    createTray();

    // Reclaim any stale ports from orphaned previous runs
    console.log("[Nexus] Reclaiming stale ports...");
    killPortProcess(NEXT_PORT);
    killPortProcess(API_PORT);
    // Brief settle window so OS releases the sockets
    await new Promise((r) => setTimeout(r, 500));

    // Start all three services in parallel - Ollama, Python backend, Next.js frontend
    console.log("[Nexus] Starting backend, frontend, and Ollama...");
    await Promise.all([
      startOllama(),
      startBackend(),
      startNextDev(),
    ]);

    // Wait for Next.js to be fully ready
    console.log("[Nexus] Waiting for frontend...");
    const frontendReady = await waitForPort(NEXT_PORT, 45000);
    if (!frontendReady) {
      console.warn("[Nexus] Frontend did not come up in 45s - showing window anyway");
    }

    console.log("[Nexus] Creating main window...");
    createWindow();

    // Safety net: force-close splash + show main window after 20s even if
    // did-finish-load never fires (stale page, hung HMR, etc.)
    setTimeout(() => {
      if (splashWindow) {
        try { splashWindow.destroy(); } catch { /* ignore */ }
        splashWindow = null;
      }
      if (mainWindow && !mainWindow.isVisible()) {
        try { mainWindow.show(); mainWindow.focus(); } catch { /* ignore */ }
      }
    }, 20000);
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin" && !tray) {
      cleanup();
      app.quit();
    }
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });

  app.on("before-quit", () => {
    cleanup();
  });
}
