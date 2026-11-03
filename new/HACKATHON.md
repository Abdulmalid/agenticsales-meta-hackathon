# Meta Global AI Developer Hackathon: what is new, and what we plan to build

Entering as **Indie Developer** (registered as a startup; the organisers allow a registered startup to submit and be judged as indie). Submissions due **4 Nov 2026, 9:00 PM ET**. Judging 4-8 Nov; winners 9 Nov.
Rule we are working under: the pre-existing codebase is not what is judged. New features added from 26 Oct are.
Check the Official Rules for the exact wording on pre-existing work and code access before submitting.

Status key: [x] built and committed, [~] built, not yet run against the real service, [ ] planned, [-] decided against.

## 1. Pre-existing (before 26 Oct, not part of the submission)

The sales agent pipeline, language layer, leads and fraud logic, payments with gateway-verified confirmation, approvals,
content planning, the operator and business consoles, inventory and orders, and Facebook / Instagram / X connect.
See `docs/STATUS.md`.

## 2. Built during the hackathon (27-29 Oct)

- [x] **Meta Model API provider**: Muse Spark text, Muse Image, default when `META_MODEL_API_KEY` is set (`models/meta.py`). Live: the real sales agent ran on Muse Spark (Pidgin replies, price held, a fake payment claim escalated). Found on the real API that Muse Spark reasons silently, so a small token limit returned an empty answer; added `reasoning_effort` (low by default, minimal for signal extraction) plus token headroom. Muse Image not yet run live
- [x] **Voice-note commerce**: WhatsApp-style voice notes fetched, transcribed with Muse Voice Transcribe, handled as text; polite typed-text fallback when unheard (`voice/`). Live: transcription works on the real API for a spoken English sample. Found that the API accepts only mono 16-bit PCM WAV at 16/24 kHz (everything else, including WhatsApp's OGG/Opus, is "Malformed request"), so audio is converted with ffmpeg first (`voice/convert.py`, ffmpeg added to the server image). Real OGG/Opus end to end still to be confirmed
- [x] **Signal extraction and its evaluation on Muse Spark** (`language/`)
- [x] **TikTok connect**: Login Kit OAuth, 24 h token refresh, revoke on disconnect (`connect/`). Live: connected a real sandbox account on 27 Oct (login scope only; video scopes pending the Content Posting product)
- [x] **Instagram Login connect**: owners connect an Instagram professional account directly, no Facebook Page; 60-day token renewed on use; DMs and feed posts through `graph.instagram.com`; the shared webhook accepts Instagram-signed events (`connect/`, `channels/`). [~] never run against Instagram
- [x] **Threads**: connect (OAuth, 60-day token renewed on use) and a Threads publisher, so "post this product" can target Threads with a Threads-specific playbook (`connect/`, `content/`). [~] never run against Threads
- [x] **TikTok publishing**: owner attaches a video to a TikTok post; the publisher runs TikTok's Direct Post flow (creator privacy options, chunked file upload, status polling) through the connected account (`content/publishers.py`). [~] not yet run against TikTok
- [x] **Photo understanding** (`vision/`): a customer's photo is read by Muse Spark vision. It matches a catalogue product by model or printed name (the SKU must exist and confidence must be at least 0.5), recognises a payment screenshot and its fields, and reports any text in the photo as data. The agent gets one machine-read line in the customer's message; prices still come from policy, and a screenshot never counts as payment. Live on the real model: a phone photo -> the iPhone 15 and its policy price; a transfer screenshot -> escalated, fraud MEDIUM; a photo carrying an injection sign was not obeyed. The Playground can attach photos like a customer
- [x] **Found by real testers on the Telegram bot, then fixed**: (1) a long message was silently cut at 2000 characters and Telegram delivers very long text as several messages, so the limit is now 6000 and the parts of one long message are merged and answered once; (2) on long input Muse Spark sometimes spent its whole token budget on hidden reasoning and returned nothing, which handed the customer to a person, so the provider now has a bigger allowance and one automatic retry with minimal reasoning; (3) em dashes, semicolons, stacked exclamation marks and markdown are removed in code from every reply; (4) the same question gave different facts, so the sales model runs at temperature 0.2 with a same-facts rule (0.1 made it lose the customer's Pidgin); (5) the price guard read "800,000 meanwhile" as 800 billion because of the "m", forcing needless rewrites, and the rewrite instruction made the model drop correct prices too
- [x] **Natural voice, honest identity** (`security/identity.py`): the agent does not announce what it is, has a name, texts naturally and does not repeat its pitch every message. It never claims to be a person: if a customer sincerely asks whether they are talking to a person or a bot, the reply must say plainly that it is the business's virtual assistant and that a team member can take over. Enforced in code like prices and payment confirmation (a dodging draft is replaced, a claim to be human is rewritten then handed to a person), because a prompt alone was dodged on the real model ("Na Tunde here, I dey with the sales team"). Voice transcripts are marked as possibly mistaken, since Muse Voice Transcribe mishears Pidgin; Telegram shows "typing..."
- [x] **Telegram channel** (`channels/adapters.py`, `connect/`): a business pastes a BotFather token and is connected (we register the webhook with a secret). Text, voice notes and photos reach the same agent. A third channel that needs no platform approval
- [x] **Public web chat** (`/chat/<business>`): a link anyone can open with no account and no platform approval. Text, photos and browser-recorded voice notes go through the same agent, with per-visitor and per-business rate limits. Verified in Chrome: a Pidgin question, a product photo (matched to the iPhone 15) and real speech as WebM/Opus (transcribed and answered). Built because the Meta DM channels are blocked by Meta's own gates (unpublished app, locked WhatsApp account)
- [x] **Public legal pages** (`/legal/privacy`, `/legal/terms`, `/legal/data-deletion`): required by Meta and TikTok before an app can be published. Finding: Meta's webhook screen says an unpublished app receives only dashboard test webhooks, no production data even from admins/testers, which is why Instagram DMs and the read-receipts we saw never added up
- [~] **Fake-transfer-screenshot check** (`security/receipt_forensics.py`, `vision/reader.py`): Muse Spark reads the session ID, beneficiary and amount off a payment screenshot as bounded data; deterministic checks (a Nigerian instant-transfer session ID is 30 digits with an embedded Lagos-time date) flag an old, future, malformed or hand-typed ID. A finding quietly alerts the owner (a fraud_review approval, Telegram alert) and tells the agent to stay friendly and not release goods; the customer is never accused. Findings never confirm a payment, only the gateway does. Unit-tested; not yet run on a real screenshot
- [x] **While you were away** (`shift.py`, `GET /v1/shift`, Overview card): a summary of what the rep did in the last 12 h / 24 h / 7 d, read from stored messages, orders, approvals and the audit trail, with nothing estimated: customers spoken with, paid orders and revenue, customers who wrote between 10pm and 7am Lagos time, voice notes heard, photos read, payment screenshots held back, drafts fixed by the price and claims guards, what was quietly sent to the owner, and the languages spoken. Aimed at the Best Agentic Use-Case judging (autonomy and usefulness made visible)
- [x] **Instalments, receipts and books (built during the event):** a shop can switch on part payment; the item is held from the first gateway-confirmed payment and delivered only after the full price is paid (the server enforces the minimum first payment and the amounts, the agent cannot). Every confirmed payment gets a printable receipt link and each order an invoice. The owner logs expenses by text or voice note to the Telegram bot ("spent 5k on transport", "/profit week"), and profit is computed only from payments the gateway confirmed.
- [x] **Sales and dialogue corpora**: conversion tactics, retention playbooks for follow-ups, Nairaland commerce dialogue (`corpus/`)
- [x] Deployed to the Oracle VM; Meta webhook handshake verified live

**Update 29 Oct:** Meta's automated support assistant says the Business Manager is under a hard lock that blocks webhook delivery; we have not had that confirmed by a person or seen it in Business Support Home, and its answers have contradicted each other. What we have measured: WhatsApp sends fail with error 131031 (account locked), Meta does reach our WhatsApp callback (200 in the server log), and Instagram message events never arrived in development mode. Neither channel is part of the demo. The demo runs on Telegram and the public web chat. Instagram, WhatsApp, Facebook and TikTok are built and tested against fakes and, where possible, live connect flows, and are listed as pending Meta approval.

Instagram DMs (reported honestly): Instagram Login connect works live, the account is subscribed, and Instagram delivers read-receipts to our webhook, but message events never arrived in development mode (Meta requires the sender to be a Facebook user with an app role linked to the Instagram account). Shelved; Instagram posting does not depend on it. WhatsApp: delivery blocked by Meta error 131031 (account locked), logged in the audit trail.

## 2b. Built during the hackathon (28-31 Oct), by commit

Baseline: the last commit before the event is `be5fc98` (16 Oct). Everything below is dated 27 Oct or later in `git log`. Marks: [x] run for real by the owner or against the real service, [~] built and unit-tested, not yet run for real.

**Agent behaviour (the sales conversation)**
- [x] Plain texting, honest identity, long-message handling (`bbd0089`, 28 Oct); fewer template phrases and dropping replies a customer has already overtaken (`5db1042`, 29 Oct)
- [x] Receipt checks: the amount on a screenshot is compared with what the customer says they paid; the agent says plainly when they do not match and never confirms payment from a receipt (`365f032`, `b242287`, `58fc93a`, 30 Oct; `30fc052`, 31 Oct)
- [x] Haggling: a firm counter on the first over-limit price ask, one approval per haggling customer, narrower escalation (`30fc052`, 31 Oct). Prices stay enforced in code
- [x] Fraud judge degrades to the rules posture on any model failure (`e972ec7`, 30 Oct)
- [~] **Shop talk** (`58d921d`, 31 Oct, `language/trade.py`): the rep understands each trade's words (ROM, UK used, LLA, Face ID, tokunbo, trip of granite, aso ebi, HD lace...) and owners add their own. The words are meaning only. A condition, region, grade, lock or feature is stated about a unit only when its listing says so, otherwise the rep says it will confirm. Checked once against the live Meta model (Pidgin, swap, unlisted features); not yet tried in a real chat

**Owner tools**
- [x] Bulk product import, paged inventory, SKU-collision fix (`c07a56f`, 29 Oct)
- [~] **Inventory from a photo of the store book** (`1daa68f`, 31 Oct, `vision/ledger.py`): Muse vision reads a page, the owner checks and edits every row, then it imports through the normal import. Nothing is saved before the owner confirms. Not yet tried on a real handwritten page
- [x] While you were away summary (`b0052e6`, 29 Oct); instalments, receipts, invoices, expense book and profit from confirmed payments (`5d40fea`, 30 Oct)
- [~] **Team** (`a501089`, 31 Oct): owners add and remove their own staff (never admins); whether staff see the books or publish is the owner's choice; actions are recorded
- [~] **Growth** (`3a3fe87`, 30 Oct): lead origin tracking from Page comments, tracked chat links and a landing form, with results per post, plus the ideal-customer page
- [~] Silent owner alerts on Telegram and cold email outreach (`5138f0e`, 29 Oct)

**Added 1-2 Nov (after a real tester's feedback and the first live Paystack payment)**
- [x] **Paystack test-mode payment run for real** (2 Nov): a payment link made and paid, the signed webhook confirmed the order. Found live: Paystack's firewall answered Python's default User-Agent with 403 "error code 1010", so no link could be made; fixed (`451993a`)
- [~] **Order tracking**: the shop moves a paid order along (packed, on its way, out for delivery, delivered, with courier and tracking code); the customer is messaged on each change, can open a public tracking page (product and timeline only), and the rep answers "where is my order" from the shop's records through a `track_order` tool, never inventing a stage or date
- [~] **History page**: every sale, stock change, delivery update, decision and rep action with the time to the second, read from the real records
- [~] **Several product photos the rep sends in chat** (Telegram, WhatsApp, Instagram, Messenger, web chat) when a customer asks to see a product; the customer's own photo is matched against the shop's photos and the colours it stocks
- [~] **From the tester's list**: the rep answers "is this shop real" itself with true facts (address, registration number, secure Paystack page, refund policy) instead of handing over; stock replies come as a numbered list; the Google Sheet brings only stock and colours and never overwrites typed names or prices; low stock starts at 5; staff cannot decide money (discounts, orders, payment checks) or change delivery fees; cold email carries no link in its body (reply STOP, one-click only in the header), and prospects can be given a title
- [~] **TikTok**: when the account only allows uploads, the video goes to TikTok drafts instead of failing with 403 (`03f8c16`)

**Marketing content (Muse Image and composed video)**
- [x] Pictures that match the post: the planner writes a real picture brief, the image model is given the exact product and the post's message, and the owner can edit the picture idea (`6b32e90`, 31 Oct)
- [x] **Post videos** (`c8328b5`, `274724d`, `dc36f02`, 31 Oct): a vertical video composed from the post script (Muse Image pictures and ffmpeg; Meta has no video or speech API, so the video is silent and shows only the product, no people). Posts as a Facebook video, an Instagram Reel or a Telegram video; the console plays it. Instagram Reel posting was run for real on 31 Oct. The token could not read the Reel's status, so the publisher keeps trying to publish until Instagram says the video is ready
- [x] Replies to public comments on the Facebook Page's posts, with a public-safe filter (`54200f0`, 30 Oct); Facebook Login for Business connect (`ae6751e`, 30 Oct)
- [x] Posting to a Telegram channel (`5db1042`, 29 Oct)

**Channels, models, platform**
- [x] Meta-only models: Muse Spark, Muse Image, voice transcription (`6fb118e`, 27 Oct); Muse Spark reasoning effort and WAV conversion found by running against the real API (`115d243`, 28 Oct); vision (`74f9982`, 28 Oct)
- [x] Muse Spark Open provider for Baseten (`fce82e0`, 29 Oct): **run live.** The server sends photo reading and signal extraction to Muse Spark Open through Baseten (`OPEN_WEIGHTS_TASKS=vision,extractor`). The audit log holds 6 real photo reads on `meta-models/muse-spark-open-1026` between 30 Oct and 2 Nov (Telegram and web chat; confidence 0.92 to 0.99; 5 to 12 s each). Two were product photos that matched no catalogue item; four were payment screenshots. Signal extraction is configured for it too, but the audit log does not record which model did it, so only the photo reads are evidenced
- [x] Public web chat and Telegram (`6fceede`, 28 Oct); public legal pages (`230d904`, 28 Oct)
- [x] Playground "Under the hood" timeline of which Meta model ran each step (`d83cb58`, 28 Oct)
- [x] Connect: one login per platform, TikTok publisher, Threads, Instagram Login (`2a821cf`, `5dab6fa`, `5746ca4`, 27-28 Oct)
- [x] Security pass: SSRF guard on fetched media, webhook flood limit, single-use owner link code, sanitised stored facts, Next.js security headers (`b7a882d`, 31 Oct)
- [x] Console redesign (`4edbfd7`, `7d4cf55`, `3b1b429`, 29-30 Oct)
- [x] Sales and dialogue corpora (`7f71723`, 27 Oct). The Nairaland slice is NC-licensed; see `data/corpora/NAIRALAND_PROVENANCE.md`

**Not part of the demo**: Instagram and WhatsApp direct messages (blocked by Meta, see the 29 Oct update above).

**Pre-existing by date, for the judges**: inventory with per-size stock, Google Sheet sync, orders feed and the Inventory and Orders pages (`68a7f65`, `3166224`, 15 Oct) are before the event and are not claimed. The photo-of-the-store-book import above builds on them but is new.

## 3. Planned features (section 3 was written 27 Oct; items built since are in 2b and are not ticked here)

### A. Verify what exists against the real services (do first; cheapest risk reduction)
- [ ] Muse Spark, Muse Image and Muse Voice Transcribe on the real Meta Model API (payload and endpoint differences are likely)
- [ ] Facebook / Instagram connect end to end (Meta app is loaded on the server; register redirect URI and webhook in the Meta dashboard)
- [ ] TikTok sandbox connect (needs `video.upload` scope visible in the portal, or `TIKTOK_SCOPES=user.info.basic`)
- [ ] WhatsApp number and token entered for a test business; webhook is per business: `/webhooks/<business-id>/whatsapp`
- [ ] Paystack test-mode payment round trip (verified payment releases stock)

### B. Vision (the main new capability)
- [ ] Let model requests carry images (today `ModelRequest` is text only)
- [ ] **Product photo understanding**: customer sends a photo; Muse Spark matches it to the catalogue and answers ("do you have this?")
- [ ] **Receipt signal**: Muse Spark reads amount, bank and reference from a payment screenshot and shows the owner a flag. It is advisory only and feeds the existing fraud layer. It never releases stock and never accuses; only the gateway confirms payment
- [ ] Customer-facing wording for a held payment ("we'll confirm once the bank confirms")

### C. Creative
- [ ] **Studio flyer**: product photo to a branded Muse Image flyer through the existing content agent, with the usual approval gate
- [ ] Optional: SAM 3.1 product cutout before compositing (needs a GPU service; cut first if time is short)
- [ ] Optional: Muse Wonder 4-second motion banner for WhatsApp Status / Reels

### D. Open weights
- [~] Muse Spark Open on Baseten (`OpenWeightsText`, model `meta-models/muse-spark-open-1026`), chosen per task with `OPEN_WEIGHTS_TASKS=conversation,vision,...` plus `BASETEN_API_KEY`; unit-tested and run live for photo reading (see section 2b)
- [ ] Credits: Meta Model API ($150), Baseten ($100), Modal ($100) are claimed by the owner, not by code

### E. Owner-facing intelligence (ideas from reviewing marvyn.io, see section 5)
- [ ] **Ask your business**: plain-language questions over leads, orders, inventory and payments, answered with a small chart and the numbers behind it
- [ ] **Weekly digest and alerts** (needs the scheduler/worker below): stalled leads, low stock, oversold orders, payments awaiting confirmation
- [ ] **30-day plan**: a content and follow-up plan with tasks and owners, approved by the owner, reviewed against results
- [ ] Later / stretch: read-only Meta Ads insights through the Marketing API (needs the use case and App Review)

### F. Demo and submission
- [ ] **"Under the hood" panel** in the Playground: a live timeline of which model ran, what it returned and how long it took, built on the existing audit trace
- [ ] Demo assets: a real Pidgin voice note, a messy product photo, a forged and a genuine receipt, a haggling script
- [ ] 3-minute video (record on 3 Nov): problem, voice + photo + flyer, haggle + held payment, architecture and open weights, impact
- [ ] README / this file kept accurate; submit at least 2 hours before the deadline; check video link is Public or Unlisted

### G. Production hardening (judged as "holds up in production")
- [ ] Scheduler/worker for follow-ups, outbox flush and scheduled posts
- [ ] A domain name we control (the `sslip.io` address changes with the VM; the Oracle trial credit ends about 8 Nov, inside the judging window)
- [ ] Rotate the exposed keys (Gemini, Claude, Vercel token, Meta app secret shared in chat) before real customers
- [ ] Uptime check and error alerts; off-server backups

## 4. Decided against
- [-] **Muse Code generating checkout components on the fly**: payment logic must stay in reviewed code, not generated at runtime
- [-] **"NIBSS ledger" or font-forensics as a verdict**: we have no NIBSS access and image analysis cannot prove forgery. Receipt analysis stays advisory
- [-] **A new repository**: new work is added here and recorded in this file
- [-] Catalogue API and Marketing API ad creation: out of scope for 8 days (catalogue sync from inventory is a possible stretch)

## 5. Notes on marvyn.io

Marvyn is an AI marketing analyst for ads, SEO and analytics (Meta Ads, Google Ads, Shopify, GA4, Search Console). It has no customer-facing chat,
voice, vision, payments or inventory, so it is not a direct competitor. Ideas worth borrowing: asking questions in plain language and getting charts
with cited data, scheduled background checks with alerts, a reviewed 30-day plan, and the rule that nothing ships without human approval
(which our approvals layer already does). Its credit-based pricing is a possible model for AI-reply metering; we already meter by plan.
