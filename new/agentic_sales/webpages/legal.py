"""The public legal pages the platforms ask for before an app can be published: privacy policy, terms of service and data deletion.

They describe what this system actually does (the sections mirror the code: what is stored, who processes it, how long backups are kept,
how a customer is erased), so keep them in step with the product. The operator sets LEGAL_ENTITY and LEGAL_CONTACT_EMAIL; the text is
a plain-language starting point, not legal advice, and should be reviewed before real customers are served.
"""
from __future__ import annotations

import html
import os

UPDATED = "28 October 2026"

STYLE = """<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#1c1b19;--muted:#6a665e;--line:#e5e1d8;--accent:#0b6b4d}
@media(prefers-color-scheme:dark){:root{--bg:#161512;--fg:#ece9e1;--muted:#a09b90;--line:#2e2c27;--accent:#5fd1a4}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:46rem;margin:0 auto;padding:2rem 1rem 4rem}
h1{font-size:1.7rem;margin:0 0 .25rem}h2{font-size:1.1rem;margin:2rem 0 .4rem}
p,li{margin:.4rem 0}ul{padding-left:1.2rem}.muted{color:var(--muted);font-size:.9rem}
nav{display:flex;gap:1rem;flex-wrap:wrap;margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line);font-size:.95rem}
a{color:var(--accent)}
</style>"""


def _entity() -> str:
    return os.environ.get("LEGAL_ENTITY", "").strip() or "AgenticSales"


def _contact() -> str:
    email = os.environ.get("LEGAL_CONTACT_EMAIL", "").strip()
    return f'<a href="mailto:{html.escape(email, quote=True)}">{html.escape(email)}</a>' if email else "the contact details published on our website"


def _page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)} - {html.escape(_entity())}</title>{STYLE}</head><body><main>"
            f'<h1>{html.escape(title)}</h1><p class="muted">Last updated {UPDATED}</p>{body}'
            '<nav aria-label="Legal"><a href="/legal/privacy">Privacy policy</a><a href="/legal/terms">Terms of service</a>'
            '<a href="/legal/data-deletion">Data deletion</a></nav></main></body></html>')


def privacy() -> str:
    e = html.escape(_entity())
    return _page("Privacy policy", f"""
<p>{e} runs AgenticSales, an AI sales assistant that businesses use to answer their customers' messages. This policy explains what is
collected when you message a business that uses it, and when a business owner connects their accounts to it.</p>

<h2>Who is responsible</h2>
<p>When you message a business on WhatsApp, Instagram, Messenger, TikTok or its website, that business decides why your messages are used
and is responsible for the conversation. {e} processes the conversation on the business's behalf to run the assistant.</p>

<h2>What we collect</h2>
<ul>
<li>The messages you send: text, voice notes and photos, with the time you sent them.</li>
<li>Your identifier on the channel (for example a phone number or an Instagram or Messenger ID) and your display name where the channel provides it.</li>
<li>Details you choose to share to place an order, such as a delivery address, and the status of an order or payment.</li>
<li>For business owners who connect an account: the account name and ID and an access token. Tokens are stored encrypted and are never shown back.</li>
</ul>

<h2>How it is used</h2>
<ul>
<li>To answer your questions, quote the prices the business has set, take orders and follow up on them.</li>
<li>To check payments with the payment provider. A screenshot is never treated as proof of payment.</li>
<li>To spot fraud and abuse, and to show the business its leads and results.</li>
</ul>
<p>We do not sell personal data and we do not use it for advertising.</p>

<h2>AI processing</h2>
<p>Your messages, voice notes and photos are processed by AI models to understand and answer them, including models provided by Meta through
the Meta Model API and other providers the business enables. The assistant can make mistakes. The business can review and take over any conversation.</p>

<h2>Who else receives it</h2>
<ul>
<li>The business you are messaging.</li>
<li>The payment provider (Paystack) when you pay.</li>
<li>Infrastructure and AI providers that process data for us under their own terms.</li>
<li>Authorities, where the law requires it.</li>
</ul>

<h2>How long we keep it</h2>
<p>Conversation and order records are kept while the business uses the service, or until you ask for them to be deleted. Backups are kept for
about two weeks and then removed.</p>

<h2>Security</h2>
<p>Traffic uses HTTPS. Account access tokens and keys are encrypted or hashed at rest, and each business's data is kept separate from every other business's.</p>

<h2>Your rights</h2>
<p>You may ask to see, correct or delete your data, or to object to its use, including under Nigeria's Data Protection Act. See
<a href="/legal/data-deletion">how to request deletion</a>.</p>

<h2>Children</h2>
<p>The service is not meant for children, and we do not knowingly collect their data.</p>

<h2>Changes and contact</h2>
<p>We will update this page when the service changes. Questions: {_contact()}.</p>
""")


def terms() -> str:
    e = html.escape(_entity())
    return _page("Terms of service", f"""
<p>These terms apply to businesses that use AgenticSales ("the service"), provided by {e}, and to people who message those businesses through it.</p>

<h2>The service</h2>
<p>AgenticSales connects a business's WhatsApp, Instagram, Messenger, TikTok, Threads, X and web channels to an AI assistant that answers customers,
quotes prices the business has set, follows up, and drafts social posts for the business to approve.</p>

<h2>Business accounts</h2>
<ul>
<li>You must have the right to connect each account you connect, and to give us the access you grant.</li>
<li>You are responsible for your prices, product claims, stock, delivery and refunds. The assistant works only within the rules and approvals you set.</li>
<li>You must follow the rules of each platform you connect and the law, including rules on messaging and advertising.</li>
<li>Keep your access keys private. Tell us if one is exposed so it can be revoked.</li>
</ul>

<h2>Acceptable use</h2>
<p>Do not use the service to send spam, deceive customers, collect data you are not entitled to, or break a platform's rules. We may suspend an account that does.</p>

<h2>Customers</h2>
<p>You are talking to an AI assistant working for the business. It can be wrong, and a person at the business can step in. Payment is confirmed only by the payment provider.</p>

<h2>Payments</h2>
<p>We do not hold your money. Payments are processed by the payment provider you connect.</p>

<h2>Availability and liability</h2>
<p>The service is provided as it is, without a promise of uninterrupted availability. To the extent the law allows, {e} is not liable for indirect or
consequential loss, and our total liability is limited to the fees paid for the service in the three months before the claim.</p>

<h2>Ending use</h2>
<p>You can disconnect any account at any time in Settings, which removes the stored access. We may suspend or end an account that breaks these terms.</p>

<h2>Governing law and contact</h2>
<p>These terms are governed by the laws of the Federal Republic of Nigeria. Questions: {_contact()}.</p>
""")


def data_deletion() -> str:
    e = html.escape(_entity())
    return _page("Data deletion", f"""
<p>You can ask for the data held about you to be deleted. This applies to people who messaged a business through AgenticSales and to business owners who connected an account.</p>

<h2>If you messaged a business</h2>
<ol>
<li>Send your request to {_contact()}, or ask the business you messaged to pass it on to us.</li>
<li>Tell us the channel and how you appear on it (your phone number, or your Instagram or Messenger name), so we can find the right records.</li>
<li>We erase your conversation history, lead record and any photos or voice-note transcripts we hold for you, and confirm to you when it is done. We aim to do this within 30 days.</li>
</ol>
<p>Some records may be kept where the law requires it, such as proof of a completed payment. Backups age out within about two weeks.</p>

<h2>If you are a business owner</h2>
<p>Disconnect each account in Settings. That revokes our access and removes the stored token. To delete the whole business and its data, write to {_contact()}.</p>

<h2>If you connected through Facebook, Instagram or Threads</h2>
<p>You can also remove {e} from your account's apps and websites settings on that platform, which ends its access immediately.</p>
""")


PAGES = {"privacy": privacy, "terms": terms, "data-deletion": data_deletion}
