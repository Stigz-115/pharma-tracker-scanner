"""
Pharma Tracker Scanner — Streamlit app.

Scans a pharma/health website for third-party trackers, PHI/PII leakage, and
pre-consent tracker firing. Playwright (headless Chromium) captures every
network request across pre- and post-consent phases, then classifies against a
vendor signature DB and scores compliance risk.
"""

import html
import io
import json
import zipfile
from urllib.parse import urlparse

import os
import subprocess
import sys

import pandas as pd
import streamlit as st


@st.cache_resource(show_spinner="Installing headless Chromium (first run only)…")
def ensure_chromium():
    """Streamlit Cloud installs pip deps but not Playwright's browser binary.
    Install it once per container; cached so it runs only on cold start.

    Order matters. `playwright install --with-deps` runs `apt-get update` across
    ALL of the container's apt repos first; if any one repo is unreachable or
    unsigned, apt returns code 100 and the whole command fails *before the
    browser is ever downloaded* ("Failed to install browsers ... exited with
    code: 100"). So we do the reverse:

      1. Install just the Chromium binary (no apt — this is the part that must
         succeed and it only needs network to the Playwright CDN).
      2. Best-effort attempt the system libs via --with-deps, but treat ANY
         failure as non-fatal: on Community Cloud the libs from packages.txt /
         the base image are usually enough, and on the Docker image they're
         already present.

    Returns True if the browser binary is installed, else an error string.

    Deliberately does NOT set PLAYWRIGHT_BROWSERS_PATH=0 (install into the
    venv's site-packages dir): the runtime app user often can't write there
    (EACCES), and even when it can, that override was only ever applied to
    this install subprocess's env, not the main process's — so the later
    in-process browser launch in scanner.py would look in the default
    location anyway, a mismatch. Using the default (~/.cache/ms-playwright)
    for both install and launch keeps them consistent and stays inside a
    directory the app user actually owns."""
    env = os.environ

    # Step 1 — browser binary (required)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True, capture_output=True, timeout=600, env=env,
        )
    except subprocess.CalledProcessError as e:
        # Playwright's installer CLI often writes the actual failure reason
        # (network error, download URL, disk space) to stdout, not stderr.
        out = (e.stdout or b"").decode("utf-8", "replace")
        err = (e.stderr or b"").decode("utf-8", "replace")
        detail = (out + "\n" + err).strip()[-1200:]
        return f"Chromium download failed (exit {e.returncode}).\n{detail}"
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if e.stdout else ""
        err = (e.stderr or b"").decode("utf-8", "replace") if e.stderr else ""
        detail = (out + "\n" + err).strip()[-1200:]
        return f"Chromium download timed out after {e.timeout}s.\n{detail}"
    except Exception as e:
        return f"Chromium install failed: {type(e).__name__}: {e}"

    # Step 2 — system libraries (best-effort, never fatal)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            check=False, capture_output=True, timeout=300, env=env,
        )
    except Exception:
        pass  # libs may already be present; launch will tell us if not

    return True


from scanner import run_scan, aggregate
from report import build_report
from signatures import CATEGORY_WEIGHTS

st.set_page_config(page_title="Pharma Tracker Scanner", page_icon="🩺", layout="wide")

# ---- lightweight styling ----
st.markdown("""
<style>
.block-container{padding-top:2.2rem;max-width:1200px}
h1{letter-spacing:-.02em}
.metric-band{font-weight:600;color:#fff;padding:2px 12px;border-radius:999px;font-size:13px}
div[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums}
.small{color:#6b7480;font-size:13px}
</style>
""", unsafe_allow_html=True)

BAND_COLOR = {"Critical": "#b3123b", "High": "#d1495b", "Moderate": "#c98a1b", "Low": "#2f7d4f"}

st.title("🩺 Pharma Tracker Scanner")
st.markdown(
    '<p class="small">Scan a pharma or health website for third-party trackers, PHI/PII leakage, '
    'and trackers firing before consent. Inventory + risk scoring in one pass.</p>',
    unsafe_allow_html=True,
)

# ---- sidebar controls ----
with st.sidebar:
    st.header("Scan settings")
    url = st.text_input("Website URL", placeholder="https://www.example-pharma.com")
    max_pages = st.slider("Pages to crawl", 1, 25, 5,
                          help="Seed URL plus internal links, breadth-first.")
    wait_ms = st.slider("Settle time per page (ms)", 1000, 8000, 3500, step=500,
                        help="How long to wait after load for tags to fire.")
    capture_consent = st.checkbox("Test pre- + post-consent", value=True,
                                  help="Capture traffic before clicking accept, then click and re-capture.")
    st.divider()
    st.caption("⚠️ Only scan sites you are authorized to test. Findings are heuristic "
               "and flag candidates for review, not legal conclusions.")
    run = st.button("Run scan", type="primary", width='stretch')

# ---- validation ----
def valid_url(u):
    try:
        p = urlparse(u.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

if run:
    if not valid_url(url):
        st.error("Enter a valid URL including http:// or https://")
        st.stop()

    chk = ensure_chromium()
    if chk is not True:
        st.error(f"Could not install Chromium: {chk}")
        st.stop()

    prog = st.progress(0.0, text="Starting…")
    status = st.empty()

    def cb(done, total, current):
        prog.progress(min(1.0, done / max(1, total)), text=f"Scanning page {done}/{total}")
        status.markdown(f'<p class="small">↳ {current}</p>', unsafe_allow_html=True)

    try:
        results = run_scan(url.strip(), max_pages=max_pages, wait_ms=wait_ms,
                           capture_consent=capture_consent, progress_cb=cb)
    except Exception as e:
        prog.empty()
        st.error(f"Scan failed: {type(e).__name__}: {e}")
        st.info("If this is a Playwright/browser error, the Chromium binary may not be "
                "installed in this environment. See deployment notes in the README.")
        st.stop()

    prog.empty()
    status.empty()
    agg = aggregate(results)
    st.session_state["agg"] = agg
    st.session_state["results"] = results
    st.session_state["seed"] = url.strip()

# ---- render results ----
if "agg" in st.session_state:
    agg = st.session_state["agg"]
    results = st.session_state["results"]
    seed = st.session_state["seed"]
    band = agg["risk_band"]

    st.markdown(
        f'### Results for `{seed}` '
        f'<span class="metric-band" style="background:{BAND_COLOR[band]}">{band} risk</span>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Risk score", f"{agg['site_score']}/100")
    c2.metric("Tracker vendors", len(agg["vendors"]))
    crit = sum(1 for f in agg["phi_events"] if f["severity"] == "critical")
    c3.metric("PHI/PII flags", len(agg["phi_events"]), delta=f"{crit} critical" if crit else None,
              delta_color="inverse")
    c4.metric("Pre-consent firings", len(agg["consent_issues"]))
    c5.metric("Pages scanned", agg["pages_scanned"])

    tabs = st.tabs(["🚨 PHI / PII leakage", "🍪 Consent", "📋 Tracker inventory",
                    "🗂 Cookies", "📄 Per-page", "⬇️ Export"])

    # PHI tab
    with tabs[0]:
        if agg["phi_events"]:
            df = pd.DataFrame(agg["phi_events"])[
                ["severity", "type", "vendor", "host", "phase", "detail", "page"]]
            sev_rank = {"critical": 0, "high": 1, "medium": 2}
            df = df.sort_values("severity", key=lambda s: s.map(sev_rank))
            st.info(
                "These are **regex pattern matches, not confirmed leaks** — review each "
                "finding's raw URL/request (Export tab) before treating it as a real issue. "
                "Common false positives: **phone_number** / **date_of_birth** hits are often "
                "random tokens, ray IDs, or timestamps in a request that happen to fall into "
                "a digit grouping the pattern matches (bot-protection domains like "
                "`challenges.cloudflare.com` frequently trigger this and don't collect phone "
                "numbers). A **vendor/host** that's a CDN, bot-protection, or infra domain "
                "rather than an ad-tech/analytics one is a signal to double-check before acting.",
                icon="ℹ️",
            )
            st.dataframe(df, width='stretch', hide_index=True)
            st.caption("Raw emails, phone numbers, SSNs, DOBs, sensitive query params, and health "
                       "terms detected in requests to third-party hosts.")
        else:
            st.success("No PHI/PII leakage candidates detected in third-party requests.")

    # Consent tab
    with tabs[1]:
        controls = [{"page": p["page"], "consent_control": p["consent_control"],
                     "clicked": p["consent_clicked"]} for p in agg["page_scores"]]
        with st.expander("ℹ️ Legend / how to read this tab"):
            st.markdown(
                "**Trackers firing before consent acceptance** — any request in the "
                "`advertising`, `social_pixel`, `data_broker`, or `session_replay` "
                "categories that fired during the pre-consent phase (before the scanner "
                "clicked an accept-all control). Most privacy frameworks expect "
                "non-essential trackers to wait for affirmative consent, so anything "
                "listed here is worth reviewing regardless of severity — the `issue` "
                "column is just a presence flag, not a score. The score impact of these "
                "hits (6 points each) is baked into the **Per-page** tab.\n\n"
                "**Consent control detected per page** — which cookie-banner control the "
                "scanner found and clicked (`consent_control`), and whether the click "
                "succeeded (`clicked`). A blank/`None` control does **not** necessarily "
                "mean the page has no consent banner or is non-compliant — it can also "
                "mean the banner uses button text/selectors the scanner's detection list "
                "(`scanner.py`'s `ACCEPT_SELECTORS`/`ACCEPT_TEXT`) doesn't recognize. "
                "Treat a blank control as \"unverified,\" not \"confirmed absent.\""
            )
        st.markdown("**Trackers firing before consent acceptance**")
        if agg["consent_issues"]:
            st.dataframe(pd.DataFrame(agg["consent_issues"]), width='stretch', hide_index=True)
        else:
            st.success("No advertising/social/session-replay trackers fired before consent.")
        st.markdown("**Consent control detected per page**")
        st.dataframe(pd.DataFrame(controls), width='stretch', hide_index=True)

    # Inventory tab
    with tabs[2]:
        with st.expander("ℹ️ Legend / how to read this tab"):
            weight_rows = "\n".join(
                f"| `{cat}` | {w} |" for cat, w in
                sorted(CATEGORY_WEIGHTS.items(), key=lambda kv: -kv[1]))
            st.markdown(
                "Every third-party request is matched against a built-in signature DB "
                "(40+ known vendors); unmatched third-party domains aren't shown here — "
                "check the raw request export if you need the full picture.\n\n"
                "- **vendor** — matched entry from the signature DB (`signatures.py`).\n"
                "- **category** — drives risk weighting; see the table below. "
                "`social_pixel` and `data_broker` carry the highest pharma-compliance "
                "concern (identity resolution / audience matching), `session_replay` is "
                "elevated because it can capture form input, and `cdn`/`error_monitoring` "
                "are informational only.\n"
                "- **risk_weight** — points this vendor's category contributes per "
                "occurrence to a page's score (see **Per-page** tab).\n"
                "- **requests** — total requests to this vendor across the whole crawl "
                "(both consent phases).\n"
                "- **pages** — distinct pages that triggered this vendor.\n\n"
                "Rows are sorted by risk weight, then request volume — review top-to-bottom.\n\n"
                "| category | risk weight |\n|---|---|\n" + weight_rows
            )
        rows = [{"vendor": name, "category": v["category"], "requests": v["requests"],
                 "pages": len(v["pages"]), "risk_weight": CATEGORY_WEIGHTS.get(v["category"], 2)}
                for name, v in agg["vendors"].items()]
        if rows:
            df = pd.DataFrame(rows).sort_values(["risk_weight", "requests"], ascending=False)
            st.dataframe(df, width='stretch', hide_index=True)
            st.bar_chart(df.set_index("vendor")["requests"])
        else:
            st.info("No known-vendor trackers matched. Check the raw request export for unknowns.")

    # Cookies tab
    with tabs[3]:
        with st.expander("ℹ️ Legend / how to read this tab"):
            st.markdown(
                "Every cookie observed during the crawl, across both pre- and "
                "post-consent phases.\n\n"
                "- **cookie** — cookie name.\n"
                "- **domains** — domain(s) that set it. First-party domains here aren't "
                "automatically fine, and third-party domains aren't automatically a "
                "problem — cross-reference against your own cookie policy / CMP "
                "declaration.\n"
                "- **pages_seen** — how many crawled pages set this cookie.\n\n"
                "This tab is a **descriptive inventory only** — it doesn't classify "
                "cookies as strictly-necessary vs. non-essential. A cookie set here that "
                "isn't declared in your CMP's cookie list is the thing worth chasing down."
            )
        crows = [{"cookie": k, "domains": ", ".join(sorted(x for x in v["domains"] if x)),
                  "pages_seen": len(v["pages"])} for k, v in agg["cookies"].items()]
        if crows:
            st.dataframe(pd.DataFrame(crows).sort_values("pages_seen", ascending=False),
                         width='stretch', hide_index=True)
        else:
            st.info("No cookies captured.")

    # Per-page tab
    with tabs[4]:
        with st.expander("ℹ️ Legend / how to read this tab"):
            st.markdown(
                "One row per crawled page.\n\n"
                "- **page** — URL crawled.\n"
                "- **score** — this page's weighted risk score: the risk weight of each "
                "unique vendor+category hit (see **Tracker inventory** tab), plus PHI "
                "severity points (critical +40, high +25, medium +10 per finding), plus "
                "+6 for each tracker that fired pre-consent. Higher = worse; there's no "
                "fixed ceiling per page. The site-level score shown at the top is the "
                "average across all pages (capped at 100, and floored at 85 if any "
                "finding anywhere is `critical`).\n"
                "- **error** — set if the scanner failed to load this page (timeout, DNS, "
                "etc.); the rest of that row's data will be empty/partial when this is set.\n"
                "- **consent_clicked** / **consent_control** — same detection as the "
                "**Consent** tab, per page."
            )
        st.dataframe(pd.DataFrame(agg["page_scores"]), width='stretch', hide_index=True)

    # Export tab
    with tabs[5]:
        # Build full raw request table
        raw = []
        for r in results:
            for phase in ("pre_consent", "post_consent"):
                for req in r.requests[phase]:
                    raw.append({
                        "page": r.url, "phase": phase, "request_url": req["url"],
                        "host": req["host"], "method": req["method"],
                        "resource_type": req["resource_type"], "third_party": req["third_party"],
                        "vendor": req["vendor"], "category": req["category"],
                        "phi_flags": "; ".join(f["type"] for f in req["phi_findings"]),
                    })
        raw_df = pd.DataFrame(raw)

        html_report = build_report(seed, agg)
        phi_df = pd.DataFrame(agg["phi_events"])
        vend_df = pd.DataFrame([{"vendor": n, **{k: (len(v[k]) if isinstance(v[k], set) else v[k])
                                                 for k in v}} for n, v in agg["vendors"].items()])
        json_blob = json.dumps({
            "seed": seed, "site_score": agg["site_score"], "risk_band": agg["risk_band"],
            "pages_scanned": agg["pages_scanned"],
            "vendors": {n: {"category": v["category"], "requests": v["requests"],
                            "pages": sorted(v["pages"])} for n, v in agg["vendors"].items()},
            "phi_events": agg["phi_events"], "consent_issues": agg["consent_issues"],
            "page_scores": agg["page_scores"],
        }, indent=2)

        colA, colB = st.columns(2)
        with colA:
            st.download_button("📄 HTML report", html_report, "tracker_report.html",
                               "text/html", width='stretch')
            st.download_button("🧾 Raw requests (CSV)", raw_df.to_csv(index=False),
                               "raw_requests.csv", "text/csv", width='stretch')
            if not phi_df.empty:
                st.download_button("🚨 PHI findings (CSV)", phi_df.to_csv(index=False),
                                   "phi_findings.csv", "text/csv", width='stretch')
        with colB:
            st.download_button("🗄 Full data (JSON)", json_blob, "scan_data.json",
                               "application/json", width='stretch')
            # zip bundle
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("tracker_report.html", html_report)
                z.writestr("raw_requests.csv", raw_df.to_csv(index=False))
                z.writestr("scan_data.json", json_blob)
                if not phi_df.empty:
                    z.writestr("phi_findings.csv", phi_df.to_csv(index=False))
                if not vend_df.empty:
                    z.writestr("vendors.csv", vend_df.to_csv(index=False))
            st.download_button("📦 Everything (ZIP)", zbuf.getvalue(),
                               "pharma_scan_bundle.zip", "application/zip",
                               width='stretch')

        st.markdown("#### Report preview")
        # Embed the self-contained report inside a sandboxed iframe via srcdoc so
        # its document-level CSS (body/table/h1 rules) stays isolated from the
        # Streamlit page. st.html replaces the deprecated st.components.v1.html;
        # the iframe restores the height/scrolling and style isolation that
        # st.components.v1.html gave us.
        srcdoc = html.escape(html_report)
        st.html(
            f'<iframe srcdoc="{srcdoc}" '
            'style="width:100%;height:520px;border:1px solid #e6e9ee;'
            'border-radius:10px;" sandbox></iframe>'
        )

else:
    st.info("Enter a URL in the sidebar and click **Run scan** to begin.")
    with st.expander("What this tool checks"):
        st.markdown("""
- **Tracker inventory** — every third-party request, matched against a vendor signature database
  (Meta Pixel, GA4, Adobe, LiveRamp, Hotjar, TikTok, and dozens more).
- **PHI / PII leakage** — emails, phone numbers, SSNs, DOBs, sensitive query parameters, and
  health/condition terms detected in requests leaving to third parties.
- **Consent** — auto-clicks the accept-all control and compares which trackers fire *before*
  versus *after* consent, flagging pre-consent firing of ad/social/session-replay tags.
- **Cookies & localStorage** — captured in both phases.
- **Risk scoring** — per-page and site-level scores weighted by tracker category and PHI severity.
""")
