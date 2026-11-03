# AgenticSales: work done during the Meta Global AI Developer Hackathon

AgenticSales is an AI sales rep for small businesses in Nigeria. It answers customers on Telegram and a public web chat (in English, Pidgin and by voice note), holds prices and payment confirmation in code, and gives the owner a console to run the shop. Every model it runs is a Meta model: Muse Spark (text and vision), Muse Image, Muse Voice Transcribe, and Muse Spark Open through Baseten.

## What this repo holds, and what it does not

This repo holds **only work done during the event** (from 26 Oct 2026): 78 new files, plus the changes I made to 104 existing files.

The code that existed before the event is **not** in this repo. It lives in a separate public repo:

**https://github.com/Abdulmalid/agenticsales-baseline** (commit `e2ddc9c`, the app as it stood on 16 Oct 2026, published as a single commit)

That repo was created on 2 Nov only to host the pre-event code. It contains no event work, and its creation date is not a claim about when the code was written.

| | Where | What |
|---|---|---|
| Before the event | `agenticsales-baseline` | The sales agent pipeline, language layer, leads and fraud logic, payments with gateway-confirmed payment, approvals, content planning, the operator and business consoles, inventory and orders, Facebook / Instagram / X connect |
| During the event | this repo, `new/` | 78 files I wrote from scratch (Meta provider, voice, vision, outreach, books, growth, history, order tracking, Team, and more) with their tests |
| During the event | this repo, `patches/event-changes.patch` | The changes to 104 existing files. It is a standard `git diff`, so every change shows the old line it replaces |

`HACKATHON.md` lists every feature with its commit and date, and says which ones I ran for real and which are only unit-tested.

## How the pieces fit

`setup.sh` (or `setup.ps1` on Windows) clones the baseline at the pinned commit (`e2ddc9c0213e571c3ea2edf3f42a016ccaae7194`), copies `new/` over it, and applies the patch. The result is the full app. I checked that this rebuilds all 182 changed files byte for byte identical to my working copy, and that the backend test suite passes on the rebuilt copy (665 tests, 28 skipped for missing keys or services).

## Run it

**Option A: the hosted demo, no setup.** Web chat: https://agenticsalesrep.duckdns.org/chat/demo (a live shop on my server, running on Meta's Muse models, rate-limited).

**Option B: run it yourself** (Python 3.12 or newer, Node 20 or newer, a Meta Model API key):

```bash
./setup.sh                      # or: powershell -File setup.ps1
cd agenticsales-full
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt        # Windows: .venv/Scripts/python
export META_MODEL_API_KEY=<your key>                       # ignore .env.example: it is the pre-event file and does not list this
python -m agentic_sales.cli tenant-create --id demo --config examples/demo_business.json   # prints the admin key once
python -m agentic_sales.cli serve --port 8000
```

In a second terminal, build the shop's landing page, which turns on the public chat:

```bash
curl -X POST http://127.0.0.1:8000/v1/landing -H "Authorization: Bearer <admin key>"      -H "Content-Type: application/json" -d '{"whatsapp":"2348012345678"}'
```

Then open http://127.0.0.1:8000/chat/demo. For the owner console: `cd web && npm install`, set `BACKEND_URL=http://127.0.0.1:8000` and `SESSION_SECRET=<any long random string>` in `web/.env.local`, run `npm run dev`, and sign in with the admin key.

Tests: from the rebuilt folder, `python -m unittest discover -s tests` (about 18 minutes).

## What I built this week

- Meta Model API provider (Muse Spark, Muse Image) and voice-note transcription, with the real-API findings that came out of running it.
- Photo understanding: a customer's photo is matched to a catalogue product, and payment screenshots are checked but never count as payment.
- Honest identity enforced in code: the rep never claims to be a person, and prices and payment confirmation can't be changed by the model.
- Telegram channel, public web chat, and the legal pages Meta and TikTok require.
- Paystack payments confirmed by signed webhook, instalments, receipts, expense book and profit from confirmed payments.
- Order tracking (customer messages, public tracking page, `track_order` tool), a History page, and several product photos the rep sends in chat.
- Owner tools: bulk and photo-of-the-store-book inventory import, Team roles, Growth tracking, cold email outreach, "while you were away" summary.
- Marketing: Muse Image pictures, composed post videos, Instagram, Threads, TikTok publishing.

## Datasets

A small sample of the project's own Nigerian Pidgin, Nigerian English and Nigerian conversation corpora is in `new/data/corpora/sample/` (about 1,700 records, 9.7 MB, every topic layer). Copy it into `data/corpora/raw/` and run `python -m agentic_sales.corpus.build` to try the local behaviour without the full 900 MB set; the hosted demo runs on the full set. See the README in that folder.

The Nairaland conversation slice is **not in this repo or the baseline repo**. It is the gated Hugging Face dataset `caleb-mnb/nairaland-conversations`, licensed CC-BY-NC-4.0, and I do not redistribute it. Credit: Caleb Olusola, who confirmed on 2 Nov 2026 that I can use it for this project, including commercially. `new/data/corpora/NAIRALAND_PROVENANCE.md` says where it came from, what the licence allows and how I got access. The app runs without it. To use it, request access on Hugging Face, put the file at `data/corpora/raw/nairaland_threads.jsonl` and run `python -m agentic_sales.corpus.build`.

## Assets

This repo contains no Meta logos, no Jolly, and no generated variations of either. Meta's models are named in plain text.

## Honest limits

Instagram and WhatsApp direct messages are built but blocked by Meta's own gates, so they are not part of the demo, which runs on Telegram and the web chat. See `HACKATHON.md`.
