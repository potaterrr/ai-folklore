#!/usr/bin/env python3
"""folklore_scraper.py — feeds the ai-folklore pipeline.

Scrapes folklore stories (title + summary) from Wikipedia — Philippine
mythology heavy, world legends mixed in — and hands them to your AI
generation stage in three ways:

  1. PUSH  — POST each story as JSON to Make.com / n8n webhooks:
       python folklore_scraper.py scrape --limit 5
       python folklore_scraper.py scrape --limit 5 \
           --webhook https://hook.us2.make.com/xxxx --webhook https://n8n.../webhook/yyy
       (also reads MAKE_WEBHOOK_URL / N8N_WEBHOOK_URL env vars)

  2. PULL  — small JSON API so n8n can poll it:
       python folklore_scraper.py serve --port 8099
       GET /stories?limit=5      -> new stories
       GET /story?title=Aswang   -> one story on demand
       GET /health               -> {"status": "ok"}

  3. FILE  — batch for manual import:
       python folklore_scraper.py scrape --limit 10 --out stories.json

Payload shape (one per webhook call):
  {"source": "ai-folklore-scraper",
   "story": {"title": ..., "summary": ..., "source": "Wikipedia",
             "url": ..., "scraped_at": ...}}

Design notes
------------
* Wikipedia REST API, not HTML scraping — stable, polite, stdlib-only
  (urllib + json, zero pip installs). Real User-Agent sent (Wikipedia
  blocks default library UAs).
* Stories come from a curated pool of Wikipedia pages (Philippine
  mythology heavy, world legends for variety weeks), shuffled per run.
* Dedupe via folklore-scraper-seen.json so repeated runs deliver only
  NEW stories — same pattern as your rss-news scraper.
* Exit codes: 0 ok, 1 no stories found, 2 any webhook failed.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = ("ai-folklore-scraper/1.0 "
              "(https://github.com/potaterrr; contact: kristiandyanbusiness@gmail.com)")
SEEN_FILE = "folklore-scraper-seen.json"
CACHE_FILE = "folklore-scraper-cache.json"
SUMMARY_SENTENCES = 6
MIN_SUMMARY_CHARS = 220
TIMEOUT = 20

# Story sources: Wikipedia pages whose content IS a legend / creature / deity.
# Philippine mythology front-loaded, world folklore behind it for variety weeks.
CATEGORY_PAGES = [
    "List of Philippine mythical creatures",
    "Philippine mythology",
    "Aswang", "Manananggal", "Tikbalang", "Kapre", "Tiyanak",
    "Bathala", "Diwata", "Bakunawa", "Maria Makiling", "Sarimanok",
    "Sigbin", "Wakwak", "Amomongo", "Bungisngis", "Kumakatok",
    "Mangkukulam", "Multo", "Santelmo",
    "Banshee", "Chupacabra", "Kraken", "La Llorona", "Werewolf",
    "Kitsune", "Yuki-onna", "Pontianak (folklore)", "Strigoi",
    "Rusalka", "Headless Horseman", "Wendigo", "Selkie", "Djinn", "Golem",
]


# --------------------------------------------------------------------------
# Wikipedia helpers (stdlib only)
# --------------------------------------------------------------------------
def http_get_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_extract(title: str) -> tuple[str, str] | None:
    """Plain-text extract + canonical title for one page; None if missing."""
    data = http_get_json(API, {
        "action": "query", "format": "json", "prop": "extracts",
        "explaintext": 1, "exintro": 0, "redirects": 1,
        "titles": title,
    })
    for _, page in data.get("query", {}).get("pages", {}).items():
        if "missing" in page:
            return None
        return page.get("title", title), page.get("extract", "")
    return None


def to_summary(extract: str, max_chars: int = 900) -> str:
    """First few sentences of the extract, cleaned for AI consumption."""
    text = " ".join(extract.split())
    sentences: list[str] = []
    count = 0
    for sentence in text.replace("! ", "!|").replace("? ", "?|").split("|"):
        s = sentence.strip()
        if not s:
            continue
        sentences.append(s)
        count += len(s)
        if len(sentences) >= SUMMARY_SENTENCES or count >= max_chars:
            break
    summary = " ".join(sentences)
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "…"
    return summary


def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return default


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------
def scrape_stories(limit: int, jitter: float) -> list[dict]:
    cache = load_json(CACHE_FILE, {})      # pool title -> story dict
    seen = set(load_json(SEEN_FILE, []))   # titles already delivered

    pool = CATEGORY_PAGES[:]
    random.shuffle(pool)                    # different mix every run
    candidates = pool[: max(limit * 2, limit)]

    stories: list[dict] = []
    for title in candidates:
        if len(stories) >= limit:
            break

        if title in cache:
            story = cache[title]
        else:
            try:
                result = api_extract(title)
            except Exception as exc:  # noqa: BLE001 — network errors just skip
                print(f"  ! fetch failed: {title}: {exc}", file=sys.stderr)
                continue
            if not result or len(result[1]) < MIN_SUMMARY_CHARS:
                continue
            canonical, extract = result
            story = {
                "title": canonical,
                "summary": to_summary(extract),
                "source": "Wikipedia",
                "url": ("https://en.wikipedia.org/wiki/"
                        + urllib.parse.quote(canonical.replace(" ", "_"))),
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            cache[title] = story
            time.sleep(jitter)              # polite pacing for the API

        if title in seen:
            continue                        # already delivered on a past run
        stories.append(story)
        seen.add(title)

    if stories:
        save_json(CACHE_FILE, cache)
        save_json(SEEN_FILE, sorted(seen))
    return stories


# --------------------------------------------------------------------------
# Delivery: one POST per story per webhook (clean Make/n8n run history)
# --------------------------------------------------------------------------
def post_webhook(url: str, payload: dict) -> bool:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        print(f"  ! webhook failed ({url[:60]}…): {exc}", file=sys.stderr)
        return False


def deliver(stories: list[dict], urls: list[str]) -> bool:
    ok = True
    for story in stories:
        for url in urls:
            good = post_webhook(url, {"source": "ai-folklore-scraper", "story": story})
            print(f"  -> {url[:48]}… {story['title']} {'✓' if good else '✗'}")
            ok = ok and good
            time.sleep(0.3)
    return ok


# --------------------------------------------------------------------------
# Pull mode: tiny JSON API for n8n polling
# --------------------------------------------------------------------------
def serve(port: int, limit: int) -> None:  # pragma: no cover (manual use)
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            n = max(1, min(int(query.get("limit", [str(limit)])[0]), 50))
            if parsed.path == "/stories":
                stories = scrape_stories(n, jitter=0.5)
                self._send(200, {"count": len(stories),
                                 "note": "empty means seen-file has everything",
                                 "stories": stories})
            elif parsed.path == "/story":
                title = query.get("title", [""])[0]
                result = api_extract(title) if title else None
                if not result or len(result[1]) < MIN_SUMMARY_CHARS:
                    self._send(404, {"error": f"no usable Wikipedia page for {title!r}"})
                else:
                    canonical, extract = result
                    self._send(200, {"story": {
                        "title": canonical,
                        "summary": to_summary(extract),
                        "source": "Wikipedia",
                        "url": ("https://en.wikipedia.org/wiki/"
                                + urllib.parse.quote(canonical.replace(" ", "_"))),
                    }})
            elif parsed.path == "/health":
                self._send(200, {"status": "ok", "service": "ai-folklore-scraper"})
            else:
                self._send(404, {"error": "use /stories?limit=N, /story?title=..., /health"})

        def log_message(self, fmt, *args):  # silence request logging
            pass

    print(f"ai-folklore scraper API on http://127.0.0.1:{port}  "
          f"(GET /stories?limit=5 · /story?title=Aswang · /health)", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape folklore stories (title + summary) for the ai-folklore pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scrape = sub.add_parser("scrape", help="scrape stories; push to webhooks and/or save to file")
    p_scrape.add_argument("--limit", type=int, default=5, help="stories per run (default 5)")
    p_scrape.add_argument("--webhook", action="append", default=[],
                          help="webhook URL (repeatable); falls back to MAKE_WEBHOOK_URL / N8N_WEBHOOK_URL")
    p_scrape.add_argument("--out", help="also write the batch to this JSON file")
    p_scrape.add_argument("--fresh", action="store_true", help="ignore seen-file (re-deliver everything)")
    p_scrape.add_argument("--jitter", type=float, default=0.5, help="seconds between API calls")

    p_serve = sub.add_parser("serve", help="small JSON API for n8n polling")
    p_serve.add_argument("--port", type=int, default=8099)
    p_serve.add_argument("--limit", type=int, default=5, help="default /stories limit")

    args = parser.parse_args()

    if args.cmd == "serve":
        serve(args.port, args.limit)
        return 0

    if args.fresh and os.path.exists(SEEN_FILE):
        os.remove(SEEN_FILE)

    stories = scrape_stories(args.limit, args.jitter)
    if not stories:
        print("No new stories (all delivered already, or sources failed).")
        return 1

    print(f"Scraped {len(stories)} stories:")
    for story in stories:
        print(f"  • {story['title']} — {story['summary'][:90]}…")

    if args.out:
        save_json(args.out, {"count": len(stories), "stories": stories})
        print(f"Wrote {args.out}")

    urls = list(args.webhook)
    for env_name in ("MAKE_WEBHOOK_URL", "N8N_WEBHOOK_URL"):
        env_url = os.getenv(env_name)
        if env_url and env_url not in urls:
            urls.append(env_url)

    if urls:
        return 0 if deliver(stories, urls) else 2
    print("(no webhooks configured — pass --webhook or set MAKE_WEBHOOK_URL / N8N_WEBHOOK_URL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
