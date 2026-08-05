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
| `packages.txt` | Debian system libs Chromium needs on Streamlit Cloud |
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
3. `requirements.txt` and `packages.txt` are picked up automatically —
   `packages.txt` installs the system libraries Chromium needs.
4. The Playwright **browser binary** is *not* installed by pip. The app handles
   this itself: on first scan it runs `playwright install chromium` (cached per
   container via `@st.cache_resource`, with `PLAYWRIGHT_BROWSERS_PATH=0` so the
   binary lands inside the venv). First scan on a cold container takes ~30–60s
   extra while Chromium downloads; subsequent scans are fast.

### If Chromium still won't launch on Streamlit Cloud

Streamlit Cloud containers are memory-limited (~1 GB) and headless Chromium is
heavy. If you hit crashes on large crawls:
- Keep **Pages to crawl** low (≤ 5) and settle time moderate.
- The launch args already include `--no-sandbox --disable-dev-shm-usage
  --disable-gpu` for constrained containers.
- For heavy production use, deploy on a container host you control (Render, Fly,
  a VM, or Docker) instead of Community Cloud — same code, more RAM. A minimal
  Dockerfile: base `mcr.microsoft.com/playwright/python`, `pip install -r
  requirements.txt`, `CMD streamlit run app.py`.

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
