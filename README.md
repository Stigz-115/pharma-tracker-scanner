# 🩺 Pharma Tracker Scanner

A Streamlit app that scans a pharma/health website for third-party trackers,
PHI/PII leakage, and trackers firing before consent — an ObservePoint-style
audit you can self-host. Built on Playwright (headless Chromium) so it captures
**every** network request, including JS-injected tags that a requests-based
crawler would miss.

## What it does

- **Tracker inventory** — every third-party request classified against a vendor
  signature database (Meta Pixel, GA4, Adobe, TikTok, LinkedIn, LiveRamp,
  Hotjar, FullStory, and ~50 others across social pixels, ad-tech, data brokers,
  analytics, session replay, tag managers, consent tools, CDNs).
- **PHI / PII leakage** — regex + parameter-name + health-term detection for
  emails, phone numbers, SSNs, DOBs, sensitive query params, hashed identifiers,
  and condition keywords found in requests leaving to third parties.
- **Consent testing** — loads the page and captures traffic *before* touching
  anything, then auto-clicks the accept-all control (OneTrust, TrustArc,
  Cookiebot, Osano, Usercentrics, Didomi, or text-matched buttons) and
  re-captures, flagging ad/social/session-replay tags that fired pre-consent.
- **Cookies & localStorage** — captured in both phases.
- **Risk scoring** — per-page and site-level scores weighted by tracker category
  and PHI severity, with a Critical/High/Moderate/Low band.
- **Exports** — HTML report, per-finding CSVs, full JSON, and a ZIP bundle.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI, orchestration, exports |
| `scanner.py` | Playwright engine: crawl, two-phase capture, aggregation, scoring |
| `signatures.py` | Vendor signature DB + category weights |
| `phi_detect.py` | PHI/PII leakage heuristics |
| `report.py` | Standalone HTML report generator |
| `requirements.txt` | Python deps |
| `packages.txt` | apt system libs Chromium needs to launch (see notes) |
| `Dockerfile` | Self-host on any container host (Chromium preinstalled) |
| `run_local.sh` | One-shot venv setup + launch for local dev |
| `.gitignore` / `.dockerignore` | Standard ignores |
| `LICENSE` | MIT |

## Run locally

One command (creates a venv, installs everything, launches):

```bash
./run_local.sh
```

Or manually:

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
```

## Run with Docker (recommended for heavy use)

The `Dockerfile` builds on the official Playwright image, so Chromium and all
system libraries are preinstalled — no runtime download, more RAM than
Community Cloud:

```bash
docker build -t pharma-tracker-scanner .
docker run -p 8501:8501 pharma-tracker-scanner
# open http://localhost:8501
```

This same image deploys directly to Render, Fly.io, Railway, Cloud Run, or any
container host.

## Push to GitHub

This folder is already a git repo with an initial commit. Create an empty repo
on GitHub (no README/license — they're already here), then:

```bash
git remote add origin https://github.com/<you>/pharma-tracker-scanner.git
git branch -M main
git push -u origin main
```

If you're starting from the downloaded zip instead:

```bash
cd pharma-tracker-scanner
git init
git add .
git commit -m "Initial commit: pharma tracker scanner"
git remote add origin https://github.com/<you>/pharma-tracker-scanner.git
git push -u origin main
```

## Deploy on Streamlit Community Cloud

1. Push these files to a public GitHub repo.
2. On https://share.streamlit.io, create a new app pointing at `app.py`.
3. `requirements.txt` and `packages.txt` are picked up automatically. Playwright
   is pinned to `1.55.0` — see the note below on why an older exact pin broke
   the build.
4. `packages.txt` lists the apt packages Chromium needs to **launch**
   (glib, nss, atk, dbus, etc.) — installed at build time by Streamlit Cloud
   itself (which runs as root), since the app's own runtime process can't
   `sudo apt-get install` anything. The browser **binary** is separate and
   handled at runtime by `ensure_chromium()` (`playwright install chromium`,
   no apt involved). First scan on a cold container takes ~30–60s extra while
   Chromium downloads; subsequent scans are fast.

> **Why `packages.txt` isn't hand-guessed, and why not `--with-deps`:** two
> apt traps bit earlier versions of this app. (1) Hand-listing Chromium's
> libraries with their old Debian names (`libglib2.0-0`, `libatk1.0-0`, etc.)
> breaks because current Debian (trixie) renamed them with a `t64` suffix
> (`libglib2.0-0t64`) — pinning the old names gives an unsatisfiable
> `held broken packages` conflict. The names currently in `packages.txt` were
> copied verbatim from Playwright's own `BrowserType.launch` error, which
> detects the container's actual Debian release and prints the exact names it
> needs — trust that over any list found elsewhere, since Debian's naming has
> changed more than once. (2) `playwright install --with-deps` runs
> `apt-get update` across every configured repo first; if any single repo is
> unreachable or unsigned, apt returns code 100 and the command fails *before
> the browser even downloads* ("Failed to install browsers ... exited with code:
> 100"). So we install the browser binary alone via pip's `ensure_chromium()`
> (no apt), and rely on `packages.txt` alone for the system libs. If you ever
> see `installer returned a non-zero exit code` in the Cloud **build** log
> (distinct from a launch-time error in the **app** log), it's `packages.txt`'s
> apt step or `requirements.txt`'s pip step — check which one printed last.

> **`installer returned a non-zero exit code` can also mean a pip build
> failure, not apt.** Streamlit Community Cloud's Python version isn't
> reliably pinnable from the repo — it has been observed ignoring a
> `runtime.txt` pin (e.g. `3.11`) and building with a newer default (currently
> Python 3.14) regardless. `playwright==1.49.0` hard-pins `greenlet==3.1.1`,
> which has no prebuilt wheel for 3.14 and fails to compile — 3.14 made
> `_PyInterpreterFrame` an opaque type and renamed
> `c_recursion_remaining`/`Py_C_RECURSION_LIMIT`, which greenlet's C extension
> depends on directly. Playwright 1.55+ relaxes its greenlet requirement to a
> range (`>=3.1.1,<4.0.0`), which resolves to `greenlet==3.2.x` — that version
> *does* ship a `cp314` wheel, so pip installs it instead of compiling. If you
> ever need a specific Python version, set it in the app's Settings ->
> Advanced UI on Community Cloud rather than via `runtime.txt`.

### If Chromium still won't launch on Streamlit Cloud

Streamlit Cloud containers are memory-limited (~1 GB) and headless Chromium is
heavy. If you hit crashes on large crawls:
- Keep **Pages to crawl** low (≤ 5) and settle time moderate.
- The launch args already include `--no-sandbox --disable-dev-shm-usage
  --disable-gpu` for constrained containers.
- If Chromium launch fails with "Host system is missing dependencies to run
  browsers", that's `packages.txt` being out of date for whatever Debian
  release Cloud is currently on — copy the exact package names from the error
  message (they include the current `t64` suffixes) into `packages.txt`,
  commit, push, and reboot the app. The runtime app process can't install
  these itself (no root) — only Cloud's own build step can.
- For heavy production use, deploy on a container host you control (Render, Fly,
  Railway, Cloud Run, or a VM) using the included `Dockerfile`, which builds on
  the official Playwright image with Chromium and all libraries preinstalled —
  no runtime download, more RAM, and none of the apt issues above.

## Notes & limits

- Findings are **heuristic** — they flag candidates for human review, not legal
  conclusions about HIPAA, FTC Health Breach, or state-privacy compliance.
- The consent auto-clicker covers common CMPs and English accept-button text;
  bespoke or non-English banners may not be detected (shown as "consent control:
  none" per page).
- Only scan sites you are authorized to test.

## Extending

- Add vendors by appending to `SIGNATURES` in `signatures.py`.
- Tune scoring via `CATEGORY_WEIGHTS`.
- Add PHI patterns/params in `phi_detect.py`.
- Add non-English accept text in `ACCEPT_TEXT` / `ACCEPT_SELECTORS` in `scanner.py`.
