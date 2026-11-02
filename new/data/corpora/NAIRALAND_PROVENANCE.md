# Nairaland dataset provenance

- Dataset: `caleb-mnb/nairaland-conversations` (Hugging Face)
- Upstream license: CC-BY-NC-4.0 (attribution required, commercial use forbidden by default).
- Attribution is baked into every indexed record (`source`, `license` fields; see the
  `nairaland` family in `agentic_sales/corpus/families.py`).
- Access: gated repository. The project owner requested access through the Hugging Face
  access form, stating commercial use as the intended purpose. Access was granted with
  no follow-up messages from the author.
- What this means: access was granted, but the license was NOT changed. Until the author
  explicitly grants commercial rights (reply message or relicense), treat this slice as
  **access-permitted, NC-licensed**: safe for research/eval and hackathon demonstration,
  NOT cleared for commercial production. Seek an explicit commercial grant before it rides
  in any revenue-serving deployment.
- Token hygiene: the Hugging Face access token was used once for the download and is not
  stored anywhere in this repository.

Slice: commerce boards only (Business, Phones, Properties, Autos, Technology Market,
Adverts, Jobs/Vacancies, and kin) in `data/corpora/raw/nairaland_threads.jsonl`
(gitignored; rebuild the index with `python -m agentic_sales.corpus.build`).
