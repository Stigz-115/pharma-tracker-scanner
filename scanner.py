"""
Core scanning engine.

Uses Playwright (headless Chromium) to load pages, capture ALL network
requests, cookies, and localStorage in two phases:
  Phase A (pre-consent): load page, wait, capture. Do NOT interact.
  Phase B (post-consent): click the accept/agree control, wait, re-capture.

Then crawls internal links up to a page budget.

Everything is classified against the vendor signature DB and scanned for PHI.
"""

import asyncio
import re
from collections import defaultdict
from urllib.parse import urlparse, urljoin, urldefrag

from playwright.async_api import async_playwright

from signatures import classify_request, CATEGORY_WEIGHTS
from phi_detect import scan_url_for_phi

# Text used to locate consent "accept all" buttons across common CMPs
ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    "#truste-consent-button",
    "#accept-recommended-btn-handler",
    ".cookiebot-accept",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "button[aria-label*='accept' i]",
    "button[title*='accept' i]",
]
ACCEPT_TEXT = re.compile(
    r"^(accept all|accept cookies|accept|agree|allow all|i agree|got it|allow cookies|"
    r"ok|continue|i understand|yes, i agree)$",
    re.IGNORECASE,
)


def _registrable(host: str) -> str:
    parts = (host or "").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class PageResult:
    def __init__(self, url):
        self.url = url
        self.error = None
        # phase -> list of request dicts
        self.requests = {"pre_consent": [], "post_consent": []}
        self.cookies = {"pre_consent": [], "post_consent": []}
        self.local_storage = {"pre_consent": {}, "post_consent": {}}
        self.consent_clicked = False
        self.consent_control = None
        self.discovered_links = []


class _Recorder:
    """Single request listener that writes into whichever sink is 'active'.
    Switching phases just repoints .active — no add/remove listener churn."""
    def __init__(self, first_party_host, initial_sink):
        self.first_party_host = first_party_host
        self.active = initial_sink

    def switch(self, sink):
        self.active = sink

    def on_request(self, req):
        url = req.url
        host = urlparse(url).netloc
        is_third = _registrable(host) != _registrable(self.first_party_host)
        vendor, category = classify_request(url)
        post_body = ""
        try:
            if req.method == "POST":
                post_body = req.post_data or ""
        except Exception:
            post_body = ""
        phi = scan_url_for_phi(url, post_body) if is_third else []
        self.active.append({
            "url": url,
            "host": host,
            "method": req.method,
            "resource_type": req.resource_type,
            "third_party": is_third,
            "vendor": vendor,
            "category": category or ("other" if is_third else "first_party"),
            "phi_findings": phi,
        })


async def _grab_cookies_storage(context, page):
    cookies = []
    try:
        for c in await context.cookies():
            cookies.append({
                "name": c.get("name"), "domain": c.get("domain"),
                "expires": c.get("expires"), "httpOnly": c.get("httpOnly"),
                "secure": c.get("secure"), "sameSite": c.get("sameSite"),
            })
    except Exception:
        pass
    ls = {}
    try:
        ls = await page.evaluate(
            "() => { const o={}; for (let i=0;i<localStorage.length;i++){const k=localStorage.key(i); o[k]=(localStorage.getItem(k)||'').slice(0,120);} return o; }"
        )
    except Exception:
        ls = {}
    return cookies, ls


async def _try_accept_consent(page):
    """Attempt to click an accept-all control. Return the label used or None."""
    for sel in ACCEPT_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click(timeout=2500)
                return sel
        except Exception:
            continue
    # Fallback: scan buttons/links by visible text
    try:
        candidates = await page.query_selector_all("button, a[role='button'], [role='button'], input[type='button'], input[type='submit']")
        for el in candidates:
            try:
                txt = ((await el.inner_text()) or (await el.get_attribute("value")) or "").strip()
            except Exception:
                txt = ""
            if txt and ACCEPT_TEXT.match(txt):
                if await el.is_visible():
                    await el.click(timeout=2500)
                    return f"text:{txt}"
    except Exception:
        pass
    return None


async def _scan_single(pw_browser, url, first_party_host, wait_ms, capture_consent):
    result = PageResult(url)
    context = await pw_browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        viewport={"width": 1366, "height": 900},
        ignore_https_errors=True,
    )
    page = await context.new_page()
    recorder = _Recorder(first_party_host, result.requests["pre_consent"])
    page.on("request", recorder.on_request)

    try:
        await page.goto(url, wait_until="load", timeout=45000)
    except Exception as e:
        result.error = f"navigation: {type(e).__name__}: {e}"
        await context.close()
        return result

    await page.wait_for_timeout(wait_ms)

    # discover internal links
    try:
        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        seen = set()
        for h in hrefs:
            h2, _ = urldefrag(h)
            p = urlparse(h2)
            if p.scheme in ("http", "https") and _registrable(p.netloc) == _registrable(first_party_host):
                if h2 not in seen:
                    seen.add(h2)
                    result.discovered_links.append(h2)
    except Exception:
        pass

    c, ls = await _grab_cookies_storage(context, page)
    result.cookies["pre_consent"] = c
    result.local_storage["pre_consent"] = ls

    if capture_consent:
        # Repoint the recorder so post-consent traffic lands in its own sink
        recorder.switch(result.requests["post_consent"])
        label = await _try_accept_consent(page)
        result.consent_control = label
        result.consent_clicked = label is not None
        if label:
            await page.wait_for_timeout(wait_ms)
            c2, ls2 = await _grab_cookies_storage(context, page)
            result.cookies["post_consent"] = c2
            result.local_storage["post_consent"] = ls2

    await context.close()
    return result


async def _run(seed_url, max_pages, wait_ms, capture_consent, progress_cb=None):
    first_party_host = urlparse(seed_url).netloc
    results = []
    queue = [seed_url]
    visited = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        while queue and len(visited) < max_pages:
            url = queue.pop(0)
            u, _ = urldefrag(url)
            if u in visited:
                continue
            visited.add(u)
            if progress_cb:
                progress_cb(len(visited), max_pages, u)
            res = await _scan_single(browser, u, first_party_host, wait_ms, capture_consent)
            results.append(res)
            for link in res.discovered_links:
                if link not in visited and link not in queue:
                    queue.append(link)
        await browser.close()
    return results


def run_scan(seed_url, max_pages=5, wait_ms=3500, capture_consent=True, progress_cb=None):
    """Synchronous entry point for Streamlit. Returns list[PageResult]."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            _run(seed_url, max_pages, wait_ms, capture_consent, progress_cb)
        )
    finally:
        loop.close()


# ---------------- aggregation & scoring ----------------

def aggregate(results):
    """Build a site-level summary from per-page results."""
    vendors = defaultdict(lambda: {"category": None, "pages": set(), "requests": 0, "third_party": True})
    phi_events = []
    consent_issues = []
    all_cookies = defaultdict(lambda: {"domains": set(), "pages": set()})
    page_scores = []

    for r in results:
        page_score = 0
        page_vendor_cats = []

        # count vendors from BOTH phases; pre-consent firing is the concern
        for phase in ("pre_consent", "post_consent"):
            for req in r.requests[phase]:
                if req["vendor"]:
                    v = vendors[req["vendor"]]
                    v["category"] = req["category"]
                    v["pages"].add(r.url)
                    v["requests"] += 1
                # PHI findings
                for f in req["phi_findings"]:
                    phi_events.append({
                        "page": r.url, "phase": phase, "vendor": req["vendor"] or req["host"],
                        "host": req["host"], "type": f["type"],
                        "severity": f["severity"], "detail": f["detail"], "url": req["url"],
                    })

        # pre-consent tracker firing: any advertising/social/data_broker before accept
        pre_bad = [req for req in r.requests["pre_consent"]
                   if req["category"] in ("advertising", "social_pixel", "data_broker", "session_replay")]
        if pre_bad and r.consent_clicked is not None:
            for req in pre_bad:
                consent_issues.append({
                    "page": r.url, "vendor": req["vendor"] or req["host"],
                    "category": req["category"], "host": req["host"],
                    "issue": "Fired before consent accepted",
                })

        # scoring
        counted = set()
        for phase in ("pre_consent", "post_consent"):
            for req in r.requests[phase]:
                key = (req["vendor"], req["category"])
                if req["vendor"] and key not in counted:
                    counted.add(key)
                    page_score += CATEGORY_WEIGHTS.get(req["category"], 2)
                    page_vendor_cats.append(req["category"])
        # PHI is heavily weighted
        for f in phi_events:
            if f["page"] == r.url:
                page_score += {"critical": 40, "high": 25, "medium": 10}.get(f["severity"], 5)
        # pre-consent firing penalty
        page_score += len(pre_bad) * 6

        page_scores.append({"page": r.url, "score": page_score,
                            "error": r.error, "consent_clicked": r.consent_clicked,
                            "consent_control": r.consent_control})

    # cookies
    for r in results:
        for phase in ("pre_consent", "post_consent"):
            for c in r.cookies[phase]:
                key = c["name"]
                all_cookies[key]["domains"].add(c["domain"])
                all_cookies[key]["pages"].add(r.url)

    site_score = min(100, int(sum(p["score"] for p in page_scores) / max(1, len(page_scores))))
    if any(f["severity"] == "critical" for f in phi_events):
        site_score = max(site_score, 85)

    band = ("Critical" if site_score >= 80 else
            "High" if site_score >= 55 else
            "Moderate" if site_score >= 30 else "Low")

    return {
        "vendors": vendors,
        "phi_events": phi_events,
        "consent_issues": consent_issues,
        "cookies": all_cookies,
        "page_scores": page_scores,
        "site_score": site_score,
        "risk_band": band,
        "pages_scanned": len(results),
    }
