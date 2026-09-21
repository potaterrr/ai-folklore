# ai-folklore 🥔

Folklore-story research stage for the **AI folklore video pipeline** (research →
Gemini script → Veo video → Facebook Reels + Telegram). This repo holds the
scraper that finds the stories; Make.com / n8n do the generation and publishing.

## What it does

`folklore_scraper.py` scrapes **title + summary** of folklore stories from
Wikipedia (Philippine mythology front-loaded, world legends for variety weeks)
and hands them to your AI stage three ways:

| Mode | Command | Use with |
| :--- | :--- | :--- |
| **Push** | `python3 folklore_scraper.py scrape --limit 5` | Make.com / n8n webhooks |
| **Pull** | `python3 folklore_scraper.py serve --port 8099` | n8n HTTP Request node polling |
| **File** | `python3 folklore_scraper.py scrape --limit 10 --out stories.json` | manual import |

Zero pip dependencies — stdlib `urllib`/`json` only. Wikipedia API, not HTML
scraping, with a proper User-Agent and polite pacing. Dedupe via
`folklore-scraper-seen.json` (repeat runs deliver only NEW stories;
`--fresh` re-delivers).

## Webhook payload (one POST per story)

```json
{
  "source": "ai-folklore-scraper",
  "story": {
    "title": "Manananggal",
    "summary": "The manananggal (lit. 'remover') is a mythical creature from the folklore of the Philippines…",
    "source": "Wikipedia",
    "url": "https://en.wikipedia.org/wiki/Manananggal",
    "scraped_at": "2026-09-21T22:40:12+0800"
  }
}
```

### Make.com
1. Scenario: **Custom webhook** → (Gemini: write 60-sec script) → (Veo: render) → publish.
2. Put the hook URL in repo secret `MAKE_WEBHOOK_URL`, or pass `--webhook <url>`.
3. Map `{{story.title}}` and `{{story.summary}}` into your script-drafting prompt.

### n8n
*Push:* Webhook node → same payload fields.
*Pull:* Schedule Trigger → **HTTP Request** node →
`GET http://<host>:8099/stories?limit=3` → iterate `stories[]`.
On-demand lookup: `/story?title=Aswang`. Health check: `/health`.

## Story pool

Curated Wikipedia pages in `CATEGORY_PAGES` inside the script — Aswang,
Manananggal, Tikbalang, Kapre, Bathala, Maria Makiling… plus Banshee, Kitsune,
La Llorona, Wendigo & co. Edit the list to steer themes; runs shuffle the pool
so every batch is a different mix. The `/story?title=` endpoint accepts any
Wikipedia title for one-off lookups.

## CLI

```
scrape  [--limit N] [--webhook URL]... [--out FILE] [--fresh] [--jitter S]
serve   [--port N] [--limit N]
```

Exit codes: `0` ok · `1` no new stories · `2` a webhook failed (handy for
retry logic in CI or a Make/n8n wrapper).
