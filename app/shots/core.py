"""Core logic: settings, projects, page discovery, capture, run history and comparison."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml

from . import __version__

# ------------------------------------------------------------------ locations

HOME = Path(os.environ.get("SHOTS_HOME", "~/Toolkit/shots")).expanduser()
PROJECTS = HOME / "projects"
CONFIG = HOME / "config.yml"
PREPARE_JS = Path(__file__).with_name("prepare.js")

DEFAULT_CONFIG = """\
# shots settings

# Where screenshots go. Relative paths are relative to ~/Toolkit/shots.
# Each project gets its own subfolder here.
# A single project can send its screenshots elsewhere (e.g. its Google Drive folder)
# with `captures_dir:` in its project file.
captures_dir: captures
"""

# ------------------------------------------------------------------ house standard

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900, "scale": 2, "mobile": False, "user_agent": None},
    "mobile": {
        "width": 390, "height": 844, "scale": 3, "mobile": True,
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        ),
    },
}

# Known consent and chat tools. Unknown banners are caught by prepare.js by behaviour.
DEFAULT_HIDE = [
    "#cmplz-cookiebanner-container", ".cmplz-cookiebanner",
    "#BorlabsCookieBox", "#BorlabsCookieWidget", ".brlbs-cmpnt-container",
    "#CybotCookiebotDialog", "#CybotCookiebotDialogBodyUnderlay",
    "#usercentrics-root", "#usercentrics-cmp-ui",
    "#onetrust-consent-sdk",
    "#real-cookie-banner", ".rcb-banner", "[id^='rcb-']",
    "#cookie-law-info-bar", ".cky-consent-container", ".cky-overlay",
    "#moove_gdpr_cookie_info_bar",
    "#tidio-chat", "#crisp-chatbox", ".intercom-lightweight-app",
]

# Pages that start unticked when choosing pages
LEGAL = re.compile(
    r"impressum|imprint|datenschutz|privacy|agb|terms|widerruf|cookie|disclaimer|"
    r"rechtliche|legal-notice|barrierefreiheitserkl|accessibility-statement",
    re.I,
)

# Pages that are never offered at all
SKIP_PATTERNS = [
    r"/wp-(admin|login|json|content|includes)", r"/feed/?$", r"/xmlrpc",
    r"/(tag|category|kategorie|author|autor)/", r"/page/\d+", r"/attachment/",
    r"/(cart|warenkorb|checkout|kasse|my-account|mein-konto)/",
    r"\.(pdf|jpe?g|png|gif|webp|svg|zip|docx?|xlsx?|mp4|mp3|xml|txt|css|js|ico)$",
]
MAX_PAGES = 60


# ------------------------------------------------------------------ settings & projects

def settings() -> dict:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(DEFAULT_CONFIG)
    return yaml.safe_load(CONFIG.read_text()) or {}


def _resolve(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else HOME / p


def captures_dir(cfg: dict) -> Path:
    """Folder holding all runs of a project."""
    if cfg.get("captures_dir"):
        return _resolve(cfg["captures_dir"])  # project-specific, used as-is
    return _resolve(settings().get("captures_dir", "captures")) / cfg["project"]


def list_projects() -> list[str]:
    settings()
    return sorted(p.stem for p in PROJECTS.glob("*.yml") if not p.stem.startswith("_"))


def project_file(name: str) -> Path:
    return PROJECTS / f"{name}.yml"


def load_project(name: str) -> dict:
    path = project_file(name)
    if not path.exists():
        raise SystemExit(f"No project called '{name}'. Projects: {', '.join(list_projects()) or 'none yet'}")
    cfg = yaml.safe_load(path.read_text()) or {}
    cfg.setdefault("project", name)
    cfg.setdefault("pages", [])
    cfg.setdefault("viewports", list(VIEWPORTS))
    cfg.setdefault("hide", [])
    cfg.setdefault("wait", 1500)
    return cfg


PROJECT_HEADER = """\
# shots project file. Safe to edit by hand.
#
# Optional settings:
#   captures_dir: ~/Library/CloudStorage/GoogleDrive-.../Clients/X/Screenshots
#                 -> screenshots for this project go straight to that folder
#   hide: [".newsletter-popup", "#announcement-bar"]   -> extra elements to hide
#   wait: 1500        -> ms to wait after loading, raise for slow sites
#   viewports: [desktop, mobile]
"""


def save_project(cfg: dict) -> Path:
    settings()
    keys = ["project", "website", "captures_dir", "hide", "wait", "viewports", "pages"]
    out = {k: cfg[k] for k in keys if k in cfg and cfg[k] not in (None, [], "")}
    # don't write defaults back
    if out.get("wait") == 1500:
        out.pop("wait")
    if out.get("viewports") == list(VIEWPORTS):
        out.pop("viewports")
    path = project_file(cfg["project"])
    path.write_text(PROJECT_HEADER + yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
    return path


def slugify(text: str) -> str:
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def suggest_name(url: str) -> str:
    host = urlsplit(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    return slugify("-".join(parts[:-1]) if len(parts) > 1 else host) or "project"


def is_legal(page: dict) -> bool:
    return bool(LEGAL.search(page["name"]) or LEGAL.search(urlsplit(page["url"]).path))


# ------------------------------------------------------------------ discovery

def _normalise(url: str) -> str:
    p = urlsplit(url)
    path = p.path or "/"
    for idx in ("index.html", "index.htm", "index.php"):
        if path.endswith("/" + idx):
            path = path[: -len(idx)]
    return urlunsplit((p.scheme, p.netloc.lower(), path, "", ""))


def _wanted(url: str, host: str) -> bool:
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
        return False
    return not any(re.search(pat, p.path, re.I) for pat in SKIP_PATTERNS)


def _from_sitemaps(request, base: str, start: str) -> list[str]:
    roots = list(dict.fromkeys([base, start.rstrip("/")]))
    candidates = [r + n for r in roots for n in ("/sitemap_index.xml", "/sitemap.xml", "/wp-sitemap.xml")]
    try:
        robots = request.get(base + "/robots.txt", timeout=15000)
        if robots.ok:
            candidates = re.findall(r"(?im)^sitemap:\s*(\S+)", robots.text()) + candidates
    except Exception:
        pass
    seen, pages, queue = set(), [], list(dict.fromkeys(candidates))
    while queue and len(seen) < 30:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = request.get(sm, timeout=15000)
            body = r.text() if r.ok else ""
        except Exception:
            continue
        if "<loc>" not in body:
            continue
        locs = [l.strip() for l in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</loc>", body, re.S)]
        if "<sitemapindex" in body:
            queue += locs
        else:
            pages += locs
    return pages


def _crawl(page, start: str, host: str) -> list[str]:
    seen, queue, found = set(), [start], []
    while queue and len(found) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if not resp or resp.status >= 400 or "text/html" not in resp.headers.get("content-type", ""):
                continue
            final = _normalise(page.url)
            if final != url and final in seen:
                continue
            seen.add(final)
            found.append(final)
            links = page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
        except Exception:
            continue
        queue += [l for l in map(_normalise, links) if l not in seen and _wanted(l, host)]
    return found


def _page_name(url: str, used: set) -> str:
    path = unquote(urlsplit(url).path).strip("/")
    path = re.sub(r"\.(html?|php|aspx?)$", "", path)
    name = slugify(path) or "home"
    if name in ("index", "start", "startseite"):
        name = "home"
    base, n = name, 2
    while name in used:
        name, n = f"{base}-{n}", n + 1
    used.add(name)
    return name


def discover(start_url: str) -> tuple[list[dict], str]:
    """Find a site's pages. Returns (pages, source) with source 'sitemap' or 'crawl'."""
    from playwright.sync_api import sync_playwright

    tries = [start_url] if "://" in start_url else ["https://" + start_url, "http://" + start_url]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i, url in enumerate(tries):  # bare domain: try https, fall back to http for older sites
            page = browser.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                break
            except Exception:
                page.close()
                if i == len(tries) - 1:
                    browser.close()
                    raise
        start = _normalise(page.url)
        parts = urlsplit(start)
        base, host = f"{parts.scheme}://{parts.netloc}", parts.netloc.lower().removeprefix("www.")
        urls, source = [_normalise(u) for u in _from_sitemaps(page.request, base, start)], "sitemap"
        if not urls:
            urls, source = _crawl(page, start, host), "crawl"
        browser.close()

    urls = [u for u in dict.fromkeys([start] + urls) if _wanted(u, host)][:MAX_PAGES]
    used: set = set()
    return [{"name": _page_name(u, used), "url": u} for u in urls], source


# ------------------------------------------------------------------ capture

def _prepare_js(cfg: dict) -> str:
    return PREPARE_JS.read_text().replace("__HIDE__", json.dumps(DEFAULT_HIDE + cfg["hide"]))


def capture(cfg: dict, label: str, progress=print) -> tuple[Path, dict]:
    """Capture all pages of a project. Writes PNGs plus run.json into a new run folder."""
    from playwright.sync_api import sync_playwright

    label = slugify(label) or "capture"
    started = dt.datetime.now()
    root = captures_dir(cfg)
    run_dir = root / f"{started:%Y-%m-%d_%H%M}_{label}"
    if run_dir.exists():
        run_dir = root / f"{started:%Y-%m-%d_%H%M%S}_{label}"
    run_dir.mkdir(parents=True)

    js = _prepare_js(cfg)
    pages = {pg["name"]: {"name": pg["name"], "url": pg["url"], "results": {}} for pg in cfg["pages"]}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp_name in cfg["viewports"]:
            vp = VIEWPORTS[vp_name]
            ctx = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                device_scale_factor=vp["scale"], is_mobile=vp["mobile"], has_touch=vp["mobile"],
                user_agent=vp["user_agent"], reduced_motion="reduce", locale="de-DE",
            )
            for pg in cfg["pages"]:
                entry = pages[pg["name"]]
                result = {"ok": False, "files": []}
                page = ctx.new_page()
                try:
                    resp = page.goto(pg["url"], wait_until="load", timeout=60000)
                    status = resp.status if resp else None
                    entry["status"] = status
                    entry["final_url"] = page.url
                    if status and status >= 400:
                        raise RuntimeError(f"HTTP {status}")
                    page.wait_for_timeout(cfg["wait"])
                    page.evaluate(js)
                    entry["title"] = page.title()
                    for crop, full in (("fold", False), ("full", True)):
                        f = f"{pg['name']}_{vp_name}_{crop}.png"
                        page.screenshot(path=str(run_dir / f), full_page=full, animations="disabled")
                        result["files"].append(f)
                    result["ok"] = True
                    progress(f"  ok      {pg['name']}  ({vp_name})")
                except Exception as e:
                    result["error"] = str(e).strip().splitlines()[0][:200]
                    progress(f"  FAILED  {pg['name']}  ({vp_name}): {result['error']}")
                finally:
                    page.close()
                entry["results"][vp_name] = result
            ctx.close()
        browser.close()

    manifest = {
        "project": cfg["project"],
        "label": label,
        "started": started.isoformat(timespec="seconds"),
        "finished": dt.datetime.now().isoformat(timespec="seconds"),
        "tool_version": __version__,
        "viewports": {v: {k: VIEWPORTS[v][k] for k in ("width", "height", "scale")} for v in cfg["viewports"]},
        "pages": list(pages.values()),
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    write_history_md(cfg)
    return run_dir, manifest


# ------------------------------------------------------------------ history

def runs(cfg: dict) -> list[dict]:
    """All runs of a project, oldest first. The run folders are the source of truth."""
    out = []
    for f in captures_dir(cfg).glob("*/run.json"):
        try:
            m = json.loads(f.read_text())
        except Exception:
            continue
        m["dir"] = f.parent
        m["id"] = f.parent.name
        out.append(m)
    return sorted(out, key=lambda m: m["started"])


def run_summary(m: dict) -> tuple[int, list[str]]:
    failed = [pg["name"] for pg in m["pages"] if not all(r["ok"] for r in pg["results"].values())]
    return len(m["pages"]), failed


def fmt_date(iso: str, with_time=True) -> str:
    d = dt.datetime.fromisoformat(iso)
    return d.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def history_lines(cfg: dict) -> list[str]:
    lines = []
    for m in runs(cfg):
        n, failed = run_summary(m)
        state = "ok" if not failed else f"{len(failed)} failed ({', '.join(failed[:3])}{'…' if len(failed) > 3 else ''})"
        lines.append(f"{fmt_date(m['started']):17} {m['label']:14} {n:3} pages  {state}")
    return lines


def status_hint(cfg: dict) -> str:
    rs = runs(cfg)
    if not rs:
        return "no captures yet"
    labels = [r["label"] for r in rs]
    last = rs[-1]
    if any(l.startswith("before") for l in labels) and not any(l.startswith("after") for l in labels):
        return f"before {fmt_date(rs[0]['started'], False)} · no after yet"
    return f"last: {last['label']} {fmt_date(last['started'], False)}"


def suggest_label(cfg: dict) -> str:
    labels = [r["label"] for r in runs(cfg)]
    if not labels:
        return "before"
    if not any(l.startswith("after") for l in labels):
        return "after"
    n = 2
    while f"after-v{n}" in labels:
        n += 1
    return f"after-v{n}"


def write_history_md(cfg: dict) -> Path:
    """A readable timeline with thumbnails. Opens in Obsidian or any Markdown viewer."""
    root = captures_dir(cfg)
    rs = runs(cfg)
    out = [f"# Screenshots: {cfg['project']}", ""]
    if cfg.get("website"):
        out += [f"Website: {cfg['website']}", ""]
    out += [f"{len(rs)} capture runs. Generated by shots, rewritten after every run.", ""]
    for m in reversed(rs):
        n, failed = run_summary(m)
        out += [f"## {m['label']} · {fmt_date(m['started'])}", ""]
        out.append(f"{n} pages" + (f", failed: {', '.join(failed)}" if failed else "") + f" · folder `{m['id']}`")
        out.append("")
        thumbs = []
        for pg in m["pages"][:6]:
            r = pg["results"].get("desktop") or next(iter(pg["results"].values()), {})
            if r.get("ok"):
                f = f"{m['id']}/{pg['name']}_desktop_fold.png" if "desktop" in pg["results"] else f"{m['id']}/{r['files'][0]}"
                thumbs.append(f"![{pg['name']}|320]({f})")
        if thumbs:
            out += [" ".join(thumbs), ""]
    comp = root / "compare"
    if comp.exists():
        out += ["## Comparisons", ""]
        for d in sorted(comp.iterdir(), reverse=True):
            if d.is_dir():
                out.append(f"- `compare/{d.name}` ({len(list(d.glob('*.png')))} images)")
        out.append("")
    path = root / "history.md"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out))
    return path


# ------------------------------------------------------------------ compare

def default_pair(rs: list[dict]) -> tuple[dict, dict] | None:
    if len(rs) < 2:
        return None
    befores = [r for r in rs if r["label"].startswith("before")]
    if befores:
        a = befores[-1]
        later = [r for r in rs if r["started"] > a["started"] and not r["label"].startswith("before")]
        if later:
            return a, later[-1]
    return rs[-2], rs[-1]


def _font(size):
    from PIL import ImageFont
    for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def compare(cfg: dict, a: dict, b: dict) -> list[Path]:
    from PIL import Image, ImageDraw

    out_dir = captures_dir(cfg) / "compare" / f"{a['id']}__vs__{b['id']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    font = _font(44)
    written = []
    for f_a in sorted(a["dir"].glob("*_fold.png")):
        f_b = b["dir"] / f_a.name
        if not f_b.exists():
            continue
        img_a, img_b = Image.open(f_a), Image.open(f_b)
        gap, label_h, margin = 80, 110, 80
        w = margin * 2 + img_a.width + gap + img_b.width
        h = margin * 2 + label_h + max(img_a.height, img_b.height)
        canvas = Image.new("RGB", (w, h), "#f2f2f2")
        draw = ImageDraw.Draw(canvas)
        x2 = margin + img_a.width + gap
        draw.text((margin, margin), f"{a['label']} · {fmt_date(a['started'], False)}", fill="#1a1a1a", font=font)
        draw.text((x2, margin), f"{b['label']} · {fmt_date(b['started'], False)}", fill="#1a1a1a", font=font)
        canvas.paste(img_a, (margin, margin + label_h))
        canvas.paste(img_b, (x2, margin + label_h))
        target = out_dir / f_a.name.replace("_fold", "_compare")
        canvas.save(target, optimize=True)
        written.append(target)
    write_history_md(cfg)
    return written
