"""Inbound voice notes: fetch audio attachments and transcribe them to text.

WhatsApp / Instagram / Messenger voice notes arrive as audio attachments.
`media.fetch_audio` downloads the bytes with the tenant's own credentials;
`transcribe.MetaVoice` turns them into text via Muse Voice Transcribe
(`muse-voice-transcribe-1.0`) on the Meta Model API. The transcript then
flows through the normal pipeline (analysis -> lead -> fraud -> sales agent),
so a voice note gets the same policy-enforced handling as typed text.
"""
