# Test results — `folklore_scraper.py`

All tests below were executed for real on **2026-09-21** against the live
English Wikipedia API. Environment: Arch Linux, Python **3.13.5**, home
internet connection (no proxies), stock `urllib` — no test mocks, no stubs.

## Summary

| # | Test | Result |
|---|------|--------|
| 1 | Batch scrape — file mode, 5 stories | ✅ 5/5 stories in **4.9s** |
| 2 | Payload quality (fields, URL, timestamp, summary size) | ✅ |
| 3 | Dedupe — rerun delivers only NEW stories | ✅ second run: 5/5 different titles |
| 4 | Webhook push (POST per story) | ✅ 200 received, payload shape verified |
| 5 | Pull API — `/health`, `/story`, `/stories` | ✅ |
| 6 | Edge cases — missing page, oversized limit, bad path | ✅ graceful |
| 7 | Rapid-fire rate check — 10 sequential `/story` calls | ✅ 10× HTTP 200 |
| 8 | Concurrency — 5 parallel `/stories` pulls | ✅ 0 dupes, state files valid |

## 1. Batch scrape (file mode)

```
$ python3 folklore_scraper.py scrape --limit 5 --out test-batch.json

Scraped 5 stories:
  • Kumakatok — The Kumakatok ("door knockers") are a group of three robed figures…
  • Tiyanak — The tiyanak (also tianak or tianac) is a vampiric creature in Philippin…
  • Wendigo — Wendigo is a mythological creature or evil spirit originating from Alg…
  • Banshee — A banshee ( Modern Irish bean sí…) is a female spirit in Irish folklore…
  • Wakwak — The Wakwak is a vampiric, bird-like creature in Philippine mythology…

real    0m4.881s        exit=0
```

## 2. Payload quality

Verified with `jq` on the emitted batch:

| Field | Check | Result |
|---|---|---|
| `title` | non-empty, canonical Wikipedia title | ✅ all 5 |
| `summary` | 220–900 chars (pool minimum to trim cap) | ✅ 900 / 491 / 899 / 433 / 896 chars |
| `url` | well-formed `https://en.wikipedia.org/wiki/<Title>` | ✅ all 5 |
| `scraped_at` | ISO timestamp with TZ offset | ✅ `2026-09-21T22:50:01+0800` |
| `source` | `"Wikipedia"` | ✅ |

Mix check: batch contained 3 Philippine + 2 world stories — the shuffle
delivers the intended PH-heavy variety without manual picking.

## 3. Dedupe

Immediately re-ran the same command (no `--fresh`):

```
Scraped 5 stories:
  • Strigoi — …        ← all five different from run 1
  • St. Elmo's fire — …
exit=0
```

Seen-file count grew 0 → 10, zero overlap between runs. `--fresh` deletes the
seen-file and re-delivers (verified during webhook testing).

## 4. Webhook push (Make.com / n8n mode)

POSTed against a local HTTP catcher to inspect the exact bytes:

```
$ python3 folklore_scraper.py scrape --limit 1 --fresh --webhook http://127.0.0.1:8098
  -> http://127.0.0.1:8098… Kapre ✓

Catcher received: {source: ai-folklore-scraper, story: {title: "Kapre", …}}
```

* One POST **per story** (a 5-story run = 5 requests — clean Make run history).
* `Content-Type: application/json`, UTF-8, 200/2xx expected; non-2xx and
  network errors print `✗` and set exit code `2`.

## 5. Pull API (serve mode)

```
$ python3 folklore_scraper.py serve --port 8099
$ curl http://127.0.0.1:8099/health
{"status": "ok", "service": "ai-folklore-scraper"}

$ curl "http://127.0.0.1:8099/story?title=Manananggal" | jq
{"story": {"title": "Manananggal", "summary": "The manananggal (lit. 'remover')…", …}}

$ curl "http://127.0.0.1:8099/stories?limit=2" | jq
{"count": 2, "stories": [{"title": "Kumakatok", …}, {"title": "Banshee", …}]}
```

## 6. Edge cases

| Case | Result |
|---|---|
| `GET /story?title=NonexistentPage12345` | ✅ `404` + `{"error": "no usable Wikipedia page for 'NonexistentPage12345'"}` |
| `GET /stories?limit=999` | ✅ clamped to 50; returns `"count": 0` once the pool is delivered |
| `GET /bogus` | ✅ `404` with usage hint |
| Pool exhausted (`/stories` after all seen) | ✅ HTTP 200, `"count": 0` + note — n8n-safe |

## 7. Rate-check

10 sequential `GET /story?title=Aswang` calls (each hits the Wikipedia API):
**10× HTTP 200**, no 429s, no errors. The scrape path additionally spaces
requests 0.5s apart (`--jitter`).

## 8. Concurrency (matters for public n8n use)

`/stories` performs read-modify-write on `folklore-scraper-seen.json` /
`folklore-scraper-cache.json`. Two overlapping requests could have corrupted
them — fixed with a thread lock (`_STATE_LOCK`) around scrape runs in serve
mode, then re-tested:

```
5 parallel GET /stories?limit=2  →  200 200 200 200 200
seen file:  VALID json, 10 entries (exactly 5×2, no dupes, no lost writes)
cache file: VALID json, 10 entries
```

Note: the lock guards threads *inside one process* (the typical n8n-polling
setup). If you scale to multiple scraper processes, point them at separate
working directories.

## Known limitations (honest list)

* English Wikipedia only; summaries inherit Wikipedia's tone (cleaned to
  plain text, 6 sentences / 900 chars max).
* The pool is finite (34 pages + any title via `/story?title=`); once all are
  delivered, `/stories` returns empty until you edit `CATEGORY_PAGES` or use
  `--fresh`.
* Summaries are factual Wikipedia extracts — the *storytelling* is your AI
  stage's job. That's the intended division of labor.
* Single-user politeness: fine for personal pipelines; don't run hundreds of
  parallel instances against Wikipedia.

## Reproduce

```bash
git clone https://github.com/potaterrr/ai-folklore.git
cd ai-folklore
python3 folklore_scraper.py scrape --limit 5 --out test-batch.json   # test 1–3
python3 folklore_scraper.py scrape --limit 1 --fresh \
    --webhook https://your-hook.example                              # test 4
python3 folklore_scraper.py serve --port 8099                        # tests 5–8
```
