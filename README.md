# ai-folklore 🥔

Folklore-story pipeline: **research → AI script → (Veo video) → publish**.
This repo holds the research stage — a scraper that fetches folklore stories
(title + summary) from Wikipedia and feeds them to Make.com or n8n, plus
importable blueprints for both.

```
folklore_scraper.py ──push──▶ Make.com webhook ──▶ Gemini script ──▶ Gmail draft (review)
        │
        └──pull-api──▶ n8n schedule ──▶ Gemini script ──▶ Telegram delivery
```

## 1. The scraper

```bash
python3 folklore_scraper.py scrape --limit 5          # push to webhooks
python3 folklore_scraper.py serve --port 8099         # JSON API for n8n to poll
python3 folklore_scraper.py scrape --limit 10 --out stories.json
```

* **Zero pip dependencies** (stdlib `urllib` + `json`) — Python 3.9+ is all it needs.
* Sources are a curated Wikipedia pool (Philippine mythology front-loaded:
  Aswang, Manananggal, Tikbalang, Kapre, Bathala, Maria Makiling… plus world
  legends like Banshee, Kitsune, La Llorona for variety weeks). Pool lives in
  `CATEGORY_PAGES` — edit it to steer themes; every run shuffles it.
* **Dedupe**: `folklore-scraper-seen.json` remembers delivered titles, so each
  run pushes only NEW stories. `--fresh` re-delivers everything.
* Politeness: real User-Agent + 0.5s jitter between API calls. Exit codes:
  `0` ok · `1` no new stories · `2` a webhook failed.

### Payload (one POST per story)

```json
{
  "source": "ai-folklore-scraper",
  "story": {
    "title": "Manananggal",
    "summary": "The manananggal is a mythical creature from Philippine folklore…",
    "source": "Wikipedia",
    "url": "https://en.wikipedia.org/wiki/Manananggal",
    "scraped_at": "2026-09-21T22:40:12+0800"
  }
}
```

---

## 2. Make.com setup (`make/blueprint.json`)

**Scenario:** Webhook → Gemini (script) → Set Variables (split narration/caption) → Gmail draft.

1. Make.com → **Scenarios → Create a new scenario → ⋯ (menu) → Import Blueprint** → upload `make/blueprint.json`.
2. Open module 1 (**Custom webhook**) → **Add** a new webhook → copy its URL → paste into the `hook` field.
3. Open module 2 (**Gemini**) → connect your Google/Gemini account → pick your model.
4. Open module 4 (**Gmail**) → connect your account → confirm the draft recipient.
5. Save, toggle the scenario **ON**.
6. Give it a story — either run the scraper (step 3 below) or click **Run once** and POST this test:
   ```bash
   curl -X POST "<your-make-webhook-url>" -H "Content-Type: application/json" \
     -d '{"source":"test","story":{"title":"Aswang","summary":"An aswang is a Filipino vampire-like monster…","source":"Wikipedia","url":"https://en.wikipedia.org/wiki/Aswang"}}'
   ```
7. Check your Gmail — a draft titled `🥔 Folklore script ready: Aswang` should appear with narration + caption.

The Gemini prompt is baked into the blueprint (hook → campfire story → comment
bait question → `CAPTION:` line with hashtags). Edit module 2 to taste.

---

## 3. n8n setup (`n8n/workflow.json`)

**Workflow:** Schedule (Wed 6AM PHT) → HTTP pull → Split → Gemini → Tidy → File → Telegram.

1. n8n → **Workflows → Import from File** → `n8n/workflow.json`.
2. **Scraper host**: the workflow pulls `http://127.0.0.1:8099/stories?limit=3`.
   - n8n on the same machine? Start the API: `python3 folklore_scraper.py serve --port 8099`
     (run it under systemd/screen so it stays up).
   - n8n in the cloud? Run the scraper on any always-on box and edit the URL.
3. **Gemini credential**: Credentials → New → **Header Auth** →
   name `x-goog-api-key`, value = your Gemini API key → select it in the Gemini node.
4. **Telegram node**: set your channel/chat ID and connect a Telegram bot credential
   (or delete it and add Gmail/Sheets — the data is in `Tidy fields`).
5. Activate. Every Wednesday 6AM PHT: pull up to 3 new stories → one Gemini script each → Telegram.

---

## 4. Test the whole chain now

```bash
# terminal 1 — the API
python3 folklore_scraper.py serve --port 8099

# terminal 2 — poke it like n8n would
curl "http://127.0.0.1:8099/stories?limit=2" | jq
curl "http://127.0.0.1:8099/story?title=Aswang" | jq
```

Then push straight into your imported Make scenario:

```bash
export MAKE_WEBHOOK_URL="https://hook.us2.make.com/xxxx"
python3 folklore_scraper.py scrape --limit 2
```

## Repo layout

```
folklore_scraper.py     # the scraper (push / pull-API / file modes)
make/blueprint.json     # importable Make.com scenario (webhook → Gemini → Gmail draft)
n8n/workflow.json       # importable n8n workflow (schedule → pull → Gemini → Telegram)
```
