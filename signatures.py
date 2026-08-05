"""
Known-vendor tracker signature database.

Each signature matches on request hostnames and/or URL path fragments.
`category` drives risk scoring; `pharma_sensitive` flags vendors whose presence
on a health/pharma page is a heightened compliance concern (ad-tech, social
pixels, data brokers) versus benign infrastructure (CDNs, error monitoring).
"""

# category weights feed the per-page and site risk score
CATEGORY_WEIGHTS = {
    "advertising": 10,
    "social_pixel": 12,
    "data_broker": 12,
    "analytics": 5,
    "session_replay": 8,
    "tag_manager": 3,
    "consent": 0,
    "cdn": 1,
    "error_monitoring": 1,
    "other": 2,
}

# Each entry: name, list of host substrings, list of path substrings, category
SIGNATURES = [
    # ---- Social / ad pixels (highest pharma concern) ----
    {"name": "Meta / Facebook Pixel", "hosts": ["facebook.com", "facebook.net", "fbcdn.net", "connect.facebook"], "paths": ["/tr", "fbevents.js", "/signals"], "category": "social_pixel"},
    {"name": "TikTok Pixel", "hosts": ["analytics.tiktok.com", "tiktok.com"], "paths": ["/pixel", "events.js"], "category": "social_pixel"},
    {"name": "LinkedIn Insight", "hosts": ["linkedin.com", "licdn.com", "px.ads.linkedin"], "paths": ["/li.lms", "insight.min.js", "/collect"], "category": "social_pixel"},
    {"name": "Pinterest Tag", "hosts": ["pinterest.com", "pinimg.com", "ct.pinterest"], "paths": ["/v3", "pinit"], "category": "social_pixel"},
    {"name": "Snapchat Pixel", "hosts": ["sc-static.net", "tr.snapchat.com"], "paths": ["/p"], "category": "social_pixel"},
    {"name": "X / Twitter Pixel", "hosts": ["ads-twitter.com", "t.co", "analytics.twitter.com", "static.ads-twitter"], "paths": ["uwt.js", "/i/adsct"], "category": "social_pixel"},
    {"name": "Reddit Pixel", "hosts": ["redditstatic.com", "reddit.com/api"], "paths": ["pixel", "conversions"], "category": "social_pixel"},

    # ---- Advertising / DSP / retargeting ----
    {"name": "Google Ads / DoubleClick", "hosts": ["doubleclick.net", "googleadservices.com", "googlesyndication.com", "google.com/ads", "google.com/pagead"], "paths": ["/pagead", "/ads", "conversion"], "category": "advertising"},
    {"name": "The Trade Desk", "hosts": ["adsrvr.org"], "paths": [], "category": "advertising"},
    {"name": "Criteo", "hosts": ["criteo.com", "criteo.net"], "paths": [], "category": "advertising"},
    {"name": "Amazon Ads", "hosts": ["amazon-adsystem.com"], "paths": [], "category": "advertising"},
    {"name": "Bing / Microsoft Ads (UET)", "hosts": ["bat.bing.com", "clarity.ms"], "paths": ["/bat.js", "/action"], "category": "advertising"},
    {"name": "Taboola", "hosts": ["taboola.com"], "paths": [], "category": "advertising"},
    {"name": "Outbrain", "hosts": ["outbrain.com"], "paths": [], "category": "advertising"},
    {"name": "Quantcast", "hosts": ["quantserve.com", "quantcast.com"], "paths": [], "category": "advertising"},

    # ---- Data brokers / identity resolution (very high pharma concern) ----
    {"name": "LiveRamp", "hosts": ["rlcdn.com", "liveramp.com", "idsync.rlcdn"], "paths": [], "category": "data_broker"},
    {"name": "LiveIntent", "hosts": ["liadm.com", "liveintent.com"], "paths": [], "category": "data_broker"},
    {"name": "ID5", "hosts": ["id5-sync.com"], "paths": [], "category": "data_broker"},
    {"name": "Tapad", "hosts": ["tapad.com"], "paths": [], "category": "data_broker"},
    {"name": "Neustar", "hosts": ["agkn.com"], "paths": [], "category": "data_broker"},

    # ---- Analytics ----
    {"name": "Google Analytics (GA4/UA)", "hosts": ["google-analytics.com", "analytics.google.com", "g.doubleclick"], "paths": ["/collect", "/g/collect", "gtag/js", "analytics.js", "/mp/collect"], "category": "analytics"},
    {"name": "Adobe Analytics", "hosts": ["omtrdc.net", "2o7.net", "demdex.net", "adobedtm.com"], "paths": ["/b/ss", "appmeasurement"], "category": "analytics"},
    {"name": "Mixpanel", "hosts": ["mixpanel.com", "mxpnl.com"], "paths": [], "category": "analytics"},
    {"name": "Amplitude", "hosts": ["amplitude.com"], "paths": [], "category": "analytics"},
    {"name": "Segment", "hosts": ["segment.com", "segment.io"], "paths": ["analytics.js"], "category": "analytics"},
    {"name": "Heap", "hosts": ["heap.io", "heapanalytics.com"], "paths": [], "category": "analytics"},
    {"name": "Matomo / Piwik", "hosts": ["matomo", "piwik"], "paths": ["matomo.js", "piwik.js"], "category": "analytics"},
    {"name": "Plausible", "hosts": ["plausible.io"], "paths": [], "category": "analytics"},

    # ---- Session replay / heatmaps (captures form input -> PHI risk) ----
    {"name": "Hotjar", "hosts": ["hotjar.com", "hotjar.io"], "paths": [], "category": "session_replay"},
    {"name": "FullStory", "hosts": ["fullstory.com", "fs.js"], "paths": ["/rec/", "fs.js"], "category": "session_replay"},
    {"name": "Microsoft Clarity", "hosts": ["clarity.ms"], "paths": ["/collect", "clarity.js"], "category": "session_replay"},
    {"name": "Mouseflow", "hosts": ["mouseflow.com"], "paths": [], "category": "session_replay"},
    {"name": "LogRocket", "hosts": ["logrocket.com", "lr-ingest"], "paths": [], "category": "session_replay"},
    {"name": "Quantum Metric", "hosts": ["quantummetric.com"], "paths": [], "category": "session_replay"},
    {"name": "Contentsquare / Clicktale", "hosts": ["contentsquare.net", "clicktale.net"], "paths": [], "category": "session_replay"},

    # ---- Tag managers ----
    {"name": "Google Tag Manager", "hosts": ["googletagmanager.com"], "paths": ["gtm.js", "gtag/js"], "category": "tag_manager"},
    {"name": "Tealium", "hosts": ["tiqcdn.com", "tealium"], "paths": ["utag.js"], "category": "tag_manager"},
    {"name": "Ensighten", "hosts": ["ensighten.com", "nexus.ensighten"], "paths": [], "category": "tag_manager"},

    # ---- Consent management (presence is good, but we detect it) ----
    {"name": "OneTrust", "hosts": ["onetrust.com", "cookielaw.org", "cookiepro.com"], "paths": ["otSDKStub", "consent"], "category": "consent"},
    {"name": "TrustArc", "hosts": ["trustarc.com", "truste.com"], "paths": [], "category": "consent"},
    {"name": "Cookiebot", "hosts": ["cookiebot.com"], "paths": ["uc.js"], "category": "consent"},
    {"name": "Osano", "hosts": ["osano.com"], "paths": [], "category": "consent"},
    {"name": "Usercentrics", "hosts": ["usercentrics.eu", "usercentrics.com"], "paths": [], "category": "consent"},
    {"name": "Didomi", "hosts": ["didomi.io"], "paths": [], "category": "consent"},

    # ---- Error monitoring / infra (low concern) ----
    {"name": "Sentry", "hosts": ["sentry.io", "sentry-cdn.com", "ingest.sentry"], "paths": [], "category": "error_monitoring"},
    {"name": "New Relic", "hosts": ["newrelic.com", "nr-data.net"], "paths": [], "category": "error_monitoring"},
    {"name": "Datadog", "hosts": ["datadoghq.com", "datadog-browser"], "paths": [], "category": "error_monitoring"},
    {"name": "Cloudflare Insights", "hosts": ["cloudflareinsights.com"], "paths": [], "category": "error_monitoring"},

    # ---- CDNs (very low concern, informational) ----
    {"name": "Google Fonts", "hosts": ["fonts.googleapis.com", "fonts.gstatic.com"], "paths": [], "category": "cdn"},
    {"name": "jsDelivr", "hosts": ["jsdelivr.net"], "paths": [], "category": "cdn"},
    {"name": "cdnjs / Cloudflare", "hosts": ["cdnjs.cloudflare.com"], "paths": [], "category": "cdn"},
    {"name": "unpkg", "hosts": ["unpkg.com"], "paths": [], "category": "cdn"},
]


def classify_request(url: str):
    """Return (vendor_name, category) for a URL, or (None, None) if unknown."""
    low = url.lower()
    for sig in SIGNATURES:
        host_hit = any(h in low for h in sig["hosts"]) if sig["hosts"] else False
        path_hit = any(p.lower() in low for p in sig["paths"]) if sig["paths"] else False
        if sig["hosts"] and sig["paths"]:
            if host_hit and (path_hit or host_hit):
                return sig["name"], sig["category"]
        elif host_hit or path_hit:
            return sig["name"], sig["category"]
    return None, None
