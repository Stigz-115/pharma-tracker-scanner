"""Generate a standalone, shareable HTML report from aggregated scan data."""

import html
from datetime import datetime, timezone

BAND_COLOR = {"Critical": "#b3123b", "High": "#d1495b", "Moderate": "#c98a1b", "Low": "#2f7d4f"}
SEV_COLOR = {"critical": "#b3123b", "high": "#d1495b", "medium": "#c98a1b"}
CAT_LABEL = {
    "social_pixel": "Social pixel", "advertising": "Advertising", "data_broker": "Data broker",
    "analytics": "Analytics", "session_replay": "Session replay", "tag_manager": "Tag manager",
    "consent": "Consent tool", "error_monitoring": "Error monitoring", "cdn": "CDN", "other": "Other",
}


def _esc(x):
    return html.escape(str(x if x is not None else ""))


def build_report(seed_url, agg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    band = agg["risk_band"]
    band_c = BAND_COLOR[band]

    # vendor rows sorted by category severity then request count
    vend_rows = ""
    order = {"social_pixel": 0, "data_broker": 1, "advertising": 2, "session_replay": 3,
             "analytics": 4, "tag_manager": 5, "error_monitoring": 6, "consent": 7, "cdn": 8, "other": 9}
    for name, v in sorted(agg["vendors"].items(),
                          key=lambda kv: (order.get(kv[1]["category"], 9), -kv[1]["requests"])):
        vend_rows += f"""<tr>
<td>{_esc(name)}</td>
<td><span class="pill cat-{_esc(v['category'])}">{_esc(CAT_LABEL.get(v['category'], v['category']))}</span></td>
<td class="num">{v['requests']}</td>
<td class="num">{len(v['pages'])}</td></tr>"""
    if not vend_rows:
        vend_rows = '<tr><td colspan="4" class="muted">No known-vendor trackers detected.</td></tr>'

    # PHI rows
    phi_rows = ""
    for f in sorted(agg["phi_events"], key=lambda x: {"critical": 0, "high": 1, "medium": 2}.get(x["severity"], 3)):
        sc = SEV_COLOR.get(f["severity"], "#666")
        phi_rows += f"""<tr>
<td><span class="sev" style="background:{sc}">{_esc(f['severity'].upper())}</span></td>
<td>{_esc(f['type'])}</td>
<td>{_esc(f['vendor'])}</td>
<td>{_esc(f['phase'])}</td>
<td class="detail">{_esc(f['detail'])}</td>
<td class="url">{_esc(f['page'])}</td></tr>"""
    if not phi_rows:
        phi_rows = '<tr><td colspan="6" class="muted">No PHI/PII leakage candidates detected.</td></tr>'

    # consent rows
    con_rows = ""
    for c in agg["consent_issues"]:
        con_rows += f"""<tr>
<td>{_esc(c['vendor'])}</td>
<td><span class="pill cat-{_esc(c['category'])}">{_esc(CAT_LABEL.get(c['category'], c['category']))}</span></td>
<td>{_esc(c['issue'])}</td>
<td class="url">{_esc(c['page'])}</td></tr>"""
    if not con_rows:
        con_rows = '<tr><td colspan="4" class="muted">No pre-consent tracker firing detected.</td></tr>'

    # page score rows
    pg_rows = ""
    for p in sorted(agg["page_scores"], key=lambda x: -x["score"]):
        cc = "yes" if p["consent_clicked"] else ("none" if p["consent_clicked"] is None else "no")
        err = f'<span class="muted">— {_esc(p["error"])}</span>' if p["error"] else ""
        pg_rows += f"""<tr>
<td class="url">{_esc(p['page'])} {err}</td>
<td class="num">{p['score']}</td>
<td>{_esc(p['consent_control'] or '—')}</td></tr>"""

    phi_count = len(agg["phi_events"])
    crit_phi = sum(1 for f in agg["phi_events"] if f["severity"] == "critical")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tracker & PHI Scan — {_esc(seed_url)}</title>
<style>
:root{{--ink:#12161c;--muted:#6b7480;--line:#e6e9ee;--bg:#ffffff;--panel:#f7f8fa;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--panel);line-height:1.5}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 24px 80px}}
header{{border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:8px}}
h1{{font-size:20px;margin:0 0 4px;letter-spacing:-.01em}}
.sub{{color:var(--muted);font-size:13px;word-break:break-all}}
.scorecard{{display:flex;gap:16px;align-items:center;background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:22px 24px;margin:24px 0}}
.score-num{{font-size:52px;font-weight:700;line-height:1;color:{band_c}}}
.score-meta{{flex:1}}
.band{{display:inline-block;font-weight:600;color:#fff;background:{band_c};padding:3px 12px;border-radius:999px;font-size:12px;letter-spacing:.03em}}
.stats{{display:flex;gap:28px;margin-top:10px;flex-wrap:wrap}}
.stat b{{font-size:22px;display:block}}
.stat span{{color:var(--muted);font-size:12px}}
section{{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin:18px 0}}
h2{{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:var(--muted);font-weight:600;padding:8px 10px;border-bottom:2px solid var(--line);font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.url{{color:var(--muted);font-size:12px;word-break:break-all;max-width:340px}}
.detail{{font-size:12px;max-width:280px}}
.muted{{color:var(--muted);font-style:italic}}
.pill{{font-size:11px;padding:2px 9px;border-radius:999px;white-space:nowrap;background:#eef1f4;color:#333}}
.cat-social_pixel,.cat-data_broker{{background:#fbe4ea;color:#b3123b}}
.cat-advertising{{background:#fdeede;color:#b8690f}}
.cat-session_replay{{background:#f3e8fb;color:#6a2fb3}}
.cat-analytics{{background:#e6f0fb;color:#1a5fb4}}
.sev{{color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.03em}}
footer{{color:var(--muted);font-size:11px;margin-top:30px;text-align:center;line-height:1.6}}
</style></head>
<body><div class="wrap">
<header>
<h1>Pharma Tracker &amp; PHI Leakage Report</h1>
<div class="sub">{_esc(seed_url)} &nbsp;·&nbsp; {ts} &nbsp;·&nbsp; {agg['pages_scanned']} page(s) scanned</div>
</header>

<div class="scorecard">
<div class="score-num">{agg['site_score']}</div>
<div class="score-meta">
<span class="band">{band} risk</span>
<div class="stats">
<div class="stat"><b>{len(agg['vendors'])}</b><span>Tracker vendors</span></div>
<div class="stat"><b style="color:{'#b3123b' if phi_count else 'inherit'}">{phi_count}</b><span>PHI/PII flags ({crit_phi} critical)</span></div>
<div class="stat"><b>{len(agg['consent_issues'])}</b><span>Pre-consent firings</span></div>
<div class="stat"><b>{len(agg['cookies'])}</b><span>Distinct cookies</span></div>
</div></div></div>

<section><h2>PHI / PII leakage to third parties</h2>
<table><thead><tr><th>Severity</th><th>Type</th><th>Vendor / host</th><th>Phase</th><th>Detail</th><th>Page</th></tr></thead>
<tbody>{phi_rows}</tbody></table></section>

<section><h2>Consent — trackers firing before acceptance</h2>
<table><thead><tr><th>Vendor / host</th><th>Category</th><th>Issue</th><th>Page</th></tr></thead>
<tbody>{con_rows}</tbody></table></section>

<section><h2>Tracker inventory</h2>
<table><thead><tr><th>Vendor</th><th>Category</th><th>Requests</th><th>Pages</th></tr></thead>
<tbody>{vend_rows}</tbody></table></section>

<section><h2>Per-page risk scores</h2>
<table><thead><tr><th>Page</th><th>Score</th><th>Consent control used</th></tr></thead>
<tbody>{pg_rows}</tbody></table></section>

<footer>
Generated by Pharma Tracker Scanner. Findings are heuristic and flag candidates for human review —
they are not a legal determination of HIPAA, FTC, or state-privacy compliance.<br>
Scan only sites you are authorized to test.
</footer>
</div></body></html>"""
