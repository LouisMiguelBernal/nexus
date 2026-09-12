# Release Process

## Today (until Phase 5 lands)

The installed desktop app is a **thin orchestrator**: it contains no application code and spawns `next start` and `uvicorn` against the checked-out source tree on disk. Two consequences:

1. **Frontend changes need a build.** `just build-frontend`, then relaunch Nexus. Nothing else refreshes `.next`.
2. **Backend changes need a restart.** Tray → *Restart Backend* (or relaunch the app).

Building a new installer (rarely needed today, since the app reads source on disk):

```
cd frontend
npm run electron:build      # next build + electron-builder --win → dist-electron/Nexus-Setup-<ver>.exe
```

Then run the installer. Known problems with the current packaging, all fixed in Phase 5: the installer is not self-contained (it depends on the absolute source path), the asar bundles ~1.7 GB it never reads, `preload.js` is not wired, and there is no build stamp.

## Versioning

The version lives in **one** place: the root `VERSION` file. `scripts/sync_versions.py` (Phase 0) writes it into `frontend/package.json` and `pyproject.toml`; the backend reads `VERSION` at startup and reports it (with the git SHA) in `/api/health`; the status bar shows both. Bump `VERSION`, sync, add a `CHANGELOG.md` section, commit, tag `v<version>`.

## Target (Phase 5)

`just release <version>`:

1. Bumps `VERSION`, runs `sync_versions.py`, verifies `CHANGELOG.md` has a section for the version.
2. `just check` must be green.
3. `next build` with `output: 'export'` → `frontend/out/`, served from the asar over `nexus://`.
4. `electron-builder` with `files: ["electron/**", "out/**", "package.json"]` and `extraResources` = backend sources + `pyproject.toml` + `uv.lock` + `VERSION` + `uv.exe` + bootstrap script. Target asar ≤ 30 MB, installer ≤ 150 MB.
5. First run of the installed app bootstraps a Python 3.12 venv with `uv sync --frozen` into `%LOCALAPPDATA%\Nexus\venv` (`NEXUS_PYTHON` overrides), then waits on `/readyz`.
6. Tags the commit; `release.yml` builds the installer artifact in CI.
7. `scripts/coldstart_test.ps1` installs to a clean profile path and asserts readiness, version stamp, and zero references to the source path in logs.

No auto-update, no code signing (out of scope).
