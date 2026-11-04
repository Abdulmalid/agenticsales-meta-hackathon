# AgenticSales: work done during the Meta Global AI Developer Hackathon

AgenticSales is an AI sales rep for small businesses in Nigeria. It answers customers on Telegram and a public web chat (in English, Pidgin and by voice note), holds prices and payment confirmation in code, and gives the owner a console to run the shop. Every model it runs is a Meta model: Muse Spark (text and vision), Muse Image, Muse Voice Transcribe, and Muse Spark Open through Baseten.

## What this repo holds, and what it does not

This repo holds **only work done during the event** (from 26 Oct 2026): 97 new files, plus the changes I made to 107 existing files.

The code that existed before the event is **not** in this repo. It lives in a separate public repo:

**https://github.com/Abdulmalid/agenticsales-baseline** (commit `e2ddc9c`, the app as it stood on 16 Oct 2026, published as a single commit)

That repo was created on 2 Nov only to host the pre-event code. It contains no event work, and its creation date is not a claim about when the code was written.

| | Where | What |
|---|---|---|
| Before the event | `agenticsales-baseline` | The structure only: the console screens, the account-connection forms (links with nothing behind them yet), and early backend code. It did not work end to end: no Meta models, no live payments, no voice, no photo understanding, no posting |
| During the event | this repo, `new/` | 97 files I wrote from scratch (Meta provider, voice, vision, outreach, books, growth, history, order tracking, Team, scheduler, design studio, and more) with their tests |
| During the event | this repo, `patches/event-changes.patch` | The changes to 107 existing files, which is where most of the making-it-work happened. It is a standard `git diff`, so every change shows the old line it replaces |

In short: before the event I had the skeleton of the product. Everything that makes it run end to end, on Meta's models, is from this week.

`HACKATHON.md` lists every feature with its commit and date, and says which ones I ran for real and which are only unit-tested.

## How the pieces fit

`setup.sh` (or `setup.ps1` on Windows) clones the baseline at the pinned commit (`e2ddc9c0213e571c3ea2edf3f42a016ccaae7194`), copies `new/` over it, and applies the patch. The result is the full app. I checked that this rebuilds all 204 changed files byte for byte identical to my working copy, and that the backend test suite passes on the rebuilt copy (751 tests, 28 skipped for missing keys or services). The full run passes on the rebuilt copy.

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
- Design studio (3 Nov): flyers and post images from a plain request. Muse Image paints a picture with no text in it, or the owner's own product photo is used; all lettering is set as sharp vector type; Muse Spark rates the result. Prices come from the catalogue, never from a model. A finished design can be posted from the studio, through the same approval queue as any post.
- Quality benchmark: flyers, pictures and video frames must reach 90/100 (`DESIGN_MIN_SCORE`) from Muse Spark's rating. The art director and picture rater score by named visible defects, so a clean design can reach 90. A design that falls short is remade up to three times, each attempt told what the last got wrong (the last on a drawn backdrop), and the owner sees the reasons and an Improve button. Below the benchmark a post is flagged so it cannot be approved.
- Video in the design studio: four scenes planned by Muse Spark and drawn by Muse Image (the owner's real photo opens and closes it when the product has one), lettered by the studio, every scene rated, the weakest scene decides the score. Posts to Facebook, Instagram, Telegram, TikTok or WhatsApp Status through the same approval queue. The owner can knowingly post a design that is below the benchmark; the post is marked that way in the approval queue. Run for real on the server: four scenes, score 92, 478 KB.
- Payment claims: a customer who says they paid, or pastes the reference, is checked with Paystack by the server before the rep answers, so money that arrived is never answered with "pay through the link" again.
- Scheduler (off by default): send queued messages, follow-ups, import leads from a Google Sheet, score each lead against the owner's ideal customer (Muse Spark Open on Baseten), draft emails for the fits, and make posts with flyers (and optional videos) for products not promoted lately. Nothing is sent or posted without the owner's approval.
- Inventory from a Google Sheet that keeps everything: extra columns become notes, a row with no price is imported unlisted, delivery prices per named place, and cost and supplier columns are never copied.
- Spending limits on expenses, set by the owner, enforced in code.

## Datasets

A small sample of the project's own Nigerian Pidgin, Nigerian English and Nigerian conversation corpora, plus the Nairaland slice, is in `new/data/corpora/sample/` (about 2,100 records, 10.2 MB, every topic layer). Copy it into `data/corpora/raw/` and run `python -m agentic_sales.corpus.build` to try the local behaviour without the full 900 MB set; the hosted demo runs on the full set. See the README in that folder.

The full Nairaland conversation dataset is **not in this repo or the baseline repo**. It is `caleb-mnb/nairaland-conversations` on Hugging Face (gated, CC-BY-NC-4.0). A small scrubbed sample of it (393 threads) is in the sample folder, shared with the author's permission. Credit: Caleb Olusola, who confirmed on 2 Nov 2026 that I can use it for this project, including commercially. `new/data/corpora/NAIRALAND_PROVENANCE.md` says where it came from, what the licence allows and how I got access. The app runs without it. To use it, request access on Hugging Face, put the file at `data/corpora/raw/nairaland_threads.jsonl` and run `python -m agentic_sales.corpus.build`.

## Assets

This repo contains no Meta logos, no Jolly, and no generated variations of either. Meta's models are named in plain text.

## Known gaps

- **The scheduler is built but off by default and has not run on the live server.** It is tested with fakes. The automatic content job and lead scoring have also never run end to end on the live server.
- **The 90 quality benchmark can still be missed.** After the rating was made defect-based, one real flyer scored 90 on its first attempt and one real video scored 92, but this is one sample each. Some designs will fall short and show the owner what was found. The threshold is a server setting (`DESIGN_MIN_SCORE`).
- **Video has no sound.** Meta has no speech or video model, so videos are Muse Image pictures with the script's words on screen.
- **The live server uses a free address on one VM.** A custom domain and a second server are post-event work.
- **Instagram and WhatsApp direct messages** are built but blocked by Meta's own gates, so the demo runs on Telegram and the web chat.
- **Muse Spark Open on Baseten** is evidenced for photo reading (6 live calls, 30 Oct to 2 Nov); the other tasks are only unit-tested against it.
- **Other model vendors' modules** (Anthropic, Gemini) are pre-event files. The server is set to Meta only (`MODEL_PROVIDER=meta`), and nothing built during the event uses them.

## Honest limits

Instagram and WhatsApp direct messages are built but blocked by Meta's own gates, so they are not part of the demo, which runs on Telegram and the web chat. See `HACKATHON.md`.

## License

MIT (see `LICENSE`). The Nairaland sample under `new/data/corpora/` keeps its own terms; see its provenance file.
