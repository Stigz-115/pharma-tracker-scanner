"""
Pharma Tracker Scanner — Streamlit app.

Scans a pharma/health website for third-party trackers, PHI/PII leakage, and
pre-consent tracker firing. Playwright (headless Chromium) captures every
network request across pre- and post-consent phases, then classifies against a
vendor signature DB and scores compliance risk.
"""

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
    Install it once per container; cached so it runs only on cold start."""
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True, capture_output=True, timeout=300,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
        )
        return True
    except Exception as e:
        return f"{type(e).__name__}: {e}"


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
    run = st.button("Run scan", type="primary", use_container_width=True)

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
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption("Raw emails, phone numbers, SSNs, DOBs, sensitive query params, and health "
                       "terms detected in requests to third-party hosts.")
        else:
            st.success("No PHI/PII leakage candidates detected in third-party requests.")

    # Consent tab
    with tabs[1]:
        controls = [{"page": p["page"], "consent_control": p["consent_control"],
                     "clicked": p["consent_clicked"]} for p in agg["page_scores"]]
        st.markdown("**Trackers firing before consent acceptance**")
        if agg["consent_issues"]:
            st.dataframe(pd.DataFrame(agg["consent_issues"]), use_container_width=True, hide_index=True)
        else:
            st.success("No advertising/social/session-replay trackers fired before consent.")
        st.markdown("**Consent control detected per page**")
        st.dataframe(pd.DataFrame(controls), use_container_width=True, hide_index=True)

    # Inventory tab
    with tabs[2]:
        rows = [{"vendor": name, "category": v["category"], "requests": v["requests"],
                 "pages": len(v["pages"]), "risk_weight": CATEGORY_WEIGHTS.get(v["category"], 2)}
                for name, v in agg["vendors"].items()]
        if rows:
            df = pd.DataFrame(rows).sort_values(["risk_weight", "requests"], ascending=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.bar_chart(df.set_index("vendor")["requests"])
        else:
            st.info("No known-vendor trackers matched. Check the raw request export for unknowns.")

    # Cookies tab
    with tabs[3]:
        crows = [{"cookie": k, "domains": ", ".join(sorted(x for x in v["domains"] if x)),
                  "pages_seen": len(v["pages"])} for k, v in agg["cookies"].items()]
        if crows:
            st.dataframe(pd.DataFrame(crows).sort_values("pages_seen", ascending=False),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No cookies captured.")

    # Per-page tab
    with tabs[4]:
        st.dataframe(pd.DataFrame(agg["page_scores"]), use_container_width=True, hide_index=True)

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
                               "text/html", use_container_width=True)
            st.download_button("🧾 Raw requests (CSV)", raw_df.to_csv(index=False),
                               "raw_requests.csv", "text/csv", use_container_width=True)
            if not phi_df.empty:
                st.download_button("🚨 PHI findings (CSV)", phi_df.to_csv(index=False),
                                   "phi_findings.csv", "text/csv", use_container_width=True)
        with colB:
            st.download_button("🗄 Full data (JSON)", json_blob, "scan_data.json",
                               "application/json", use_container_width=True)
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
                               use_container_width=True)

        st.markdown("#### Report preview")
        st.components.v1.html(html_report, height=520, scrolling=True)

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
