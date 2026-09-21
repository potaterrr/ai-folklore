# ai-folklore 🥔

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Daily folklore story push](https://img.shields.io/badge/GitHub_Actions-daily_6%3A30AM_PHT-2088FF?logo=githubactions&logoColor=white)]

Folklore-story pipeline: **research → AI script → (Veo video) → publish**.
This repo holds the research stage — a scraper that fetches folklore stories
(title + summary) from Wikipedia and feeds them to Make.com or n8n, plus
importable blueprints for both.

> ✅ **Tested against live Wikipedia** — batch scrape, dedupe, webhook push,
> pull API, edge cases and concurrency. Full results:
> [TESTING.md](TESTING.md)

```
folklore_scraper.py ──push──▶ Make.com webhook ──▶ Gemini script ──▶ Gmail draft (review)
        │
        └──pull-api──▶ n8n schedule ──▶ Gemini script ──▶ Telegram delivery
```

## 1. The scraper

```bash
python3 folklore_scraper.py scrape --limit 5          # push to webhooks
python3 folklore_scraper.py serve --port 8099         # JSON API for n8n (loopback only)
python3 folklore_scraper.py serve --host 0.0.0.0      # API reachable by Docker containers
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

**Workflow:** Execute (manual click) → HTTP pull → Split → Gemini → Tidy → Sheets log → File → Telegram.

1. n8n → **Workflows → Import from File** → `n8n/workflow.json`.
   The workflow triggers **manually** — click **Execute workflow** to run one
   batch (pull up to 3 new stories → a Gemini script each → Sheets log →
   Telegram). Add a Schedule trigger node later if you want full automation.
2. **Scraper host**: the workflow pulls `http://host.docker.internal:8099/stories?limit=3`
   (correct when n8n runs in Docker — `host.docker.internal` is mapped to the
   host by the `extra_hosts` entry in the n8n compose file).
   - Preferred: run the scraper as a persistent service (binds `0.0.0.0:8099`):
     ```bash
     mkdir -p ~/.config/systemd/user
     cp make/folklore-scraper.service ~/.config/systemd/user/
     systemctl --user daemon-reload
     systemctl --user enable --now folklore-scraper.service
     ```
   - Dockerized n8n can't see `127.0.0.1` of the host — that's why the URL is
     `host.docker.internal`. If the node times out (rather than refusing), allow
     the Docker subnet through the firewall:
     `sudo ufw allow from 172.16.0.0/12 to any port 8099 proto tcp`
   - n8n **not** in Docker (same machine)? Edit the node URL to
     `http://127.0.0.1:8099` and just run `python3 folklore_scraper.py serve --port 8099`.
   - n8n in the cloud? Run the scraper on any always-on box and edit the URL.
3. **Gemini credential**: Credentials → New → **Header Auth** →
   name `x-goog-api-key`, value = your Gemini API key → select it in the Gemini node.
4. **Google Sheets topic tracker** (see the next section for the full walkthrough):
   create the spreadsheet, paste its ID into the **Log topic to Sheets** node,
   and connect a Google Sheets credential.
5. **Telegram node**: set your channel/chat ID and connect a Telegram bot credential
   (or delete the node — the data is already saved to Sheets and `Tidy fields`).
6. Click **Execute workflow** to run a batch whenever you want.

### First-run checklist (do this in order)

Everything machine-side is already done: the scraper runs as a systemd user
service (`folklore-scraper.service`, bound to `0.0.0.0:8099`), the firewall
allows the Docker subnet, and the workflow's scraper URL points at
`host.docker.internal`. What's left is spreadsheet + credential work in the
n8n UI (~10 minutes):

- [ ] **Scraper healthy?**  `curl http://127.0.0.1:8099/health` → `{"status": "ok", ...}`
- [ ] **Create the Google Sheet** — name it, add a `Topics` tab, header row
      `Timestamp | Title | URL` (exact names — see the mapping table below)
- [ ] **Paste the spreadsheet ID** into the **Log topic to Sheets** node
      (replace `YOUR_SPREADSHEET_ID`)
- [ ] **Google Sheets OAuth2 credential** — create it in the node and finish
      the Google sign-in (Docker redirect-URL gotcha documented below)
- [ ] **Gemini credential** — the **Gemini: write 60s script** node needs a
      **Header Auth** credential: name `x-goog-api-key`, value = your Gemini
      API key (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- [ ] **Telegram (optional)** — set your channel/chat ID in **Send to Telegram**;
      it currently points at the existing `Voice Receptionist Bot` credential —
      swap it for a dedicated bot if you prefer
- [ ] Click **Execute workflow**

**Expected result:** up to 3 new rows in the `Topics` tab (one per story), one
`folklore-<title>.txt` script generated per story, and one Telegram message per
story (if configured).

**If something fails:**

| Symptom | Fix |
| :--- | :--- |
| Scraper node: *connection refused* | Start the service: `systemctl --user start folklore-scraper` |
| Scraper node: *timeout* | ufw rule missing: `sudo ufw allow from 172.16.0.0/12 to any port 8099 proto tcp` |
| Gemini node: *401 / 403* | Header Auth credential missing or wrong API key |
| Sheets node: document/credential error | Spreadsheet ID or OAuth credential not set yet |
| Runs fine but 0 rows | Every pool story is already recorded in `folklore-scraper-seen.json` (repo dir, gitignored). Delete that file to re-deliver the whole pool on the next run, or add more pages to `CATEGORY_PAGES` for fresh topics |

### Google Sheets topic tracker

Every processed story is appended to a spreadsheet so you can see at a glance
which folklore topics have been covered and when.

**Column mapping (header row must match exactly)**

The **Log topic to Sheets** node appends three fields by header name — your
sheet's first row must use these exact column names:

| Sheet column (row 1 header) | Filled with | Example |
| :--- | :--- | :--- |
| `Timestamp` | When the run processed the story — `{{ $now.format('yyyy-MM-dd HH:mm:ss') }}` | `2026-09-23 09:14:02` |
| `Title` | The story title from the scraper (`Tidy fields` → `title`) | `Banshee` |
| `URL` | The Wikipedia source URL (`Tidy fields` → `url`) | `https://en.wikipedia.org/wiki/Banshee` |

Extra columns (e.g. `Status`, `Script link`, `Posted?`) are fine to add —
they'll simply stay empty unless you map them in the node.

**1. Create the spreadsheet**

- Go to [sheets.new](https://sheets.new), name it e.g. `ai-folklore topics`.
- Rename the first tab to **`Topics`** (must match the node's sheet name).
- Add a header row: `Timestamp | Title | URL`.

**2. Grab the spreadsheet ID**

From the sheet's URL, copy the part between `/d/` and `/edit`:

```
https://docs.google.com/spreadsheets/d/<THIS_PART_IS_THE_ID>/edit
```

**3. Point the node at it**

- Open the **Log topic to Sheets** node → **Document** → paste the ID
  (replace the `YOUR_SPREADSHEET_ID` placeholder).
- **Sheet** should say `Topics`.

**4. Create the credential**

- In the node, **Credential → Create new** → *Google Sheets OAuth2 API*.
- n8n in Docker: you must add Google OAuth **redirect URLs** first
  (*Settings → n8n API → OAuth Redirect URLs* in the n8n UI, or set the
  `N8N_OAUTH2_REDIRECT_URL` env var) — then n8n shows the exact redirect URL
  to paste into your [Google Cloud console](https://console.cloud.google.com/)
  OAuth client. Enable the **Google Sheets API** for that project.
- Finish the **Connect to Google** sign-in popup.
- Detailed docs: https://docs.n8n.io/integrations/builtin/credentials/google/

**5. Test**

Execute the workflow once, then check the `Topics` tab — a new row with
`Timestamp | Title | URL` should appear for each story processed.

> Don't want Sheets? Delete the **Log topic to Sheets** node and reconnect
> `Tidy fields` → `Script to file` — nothing else changes.

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
folklore_scraper.py               # the scraper (push / pull-API / file modes)
make/blueprint.json               # importable Make.com scenario (webhook → Gemini → Gmail draft)
n8n/workflow.json                 # importable n8n workflow (schedule → pull → Gemini → Telegram)
.github/workflows/daily_scrape.yml # daily GitHub Actions run (6:30AM PHT)
```

## Daily automation (GitHub Actions)

`.github/workflows/daily_scrape.yml` runs the scraper **every day at 6:30 AM PHT**:

1. Scrape up to 3 new stories (dedupe via the committed seen-file).
2. POST each to your webhooks — set repo secrets **`AI_MAKE_URL`** and/or
   **`AI_N8N_URL`** (Settings → Secrets and variables → Actions).
3. Commit the updated seen/cache state back to the repo, so dedupe persists
   across runs (the Actions runner is ephemeral — without this, every run
   would re-deliver the same stories).

Manual test run: **Actions → Daily folklore story push → Run workflow**.

> Note: on GitHub's free plan, scheduled workflows in public repos run fine;
> they're automatically disabled after 60 days of repo inactivity — any commit
> (including the bot's own state commits) keeps it alive.

## License

[MIT](LICENSE) — use it, fork it, build your own folklore machine.
