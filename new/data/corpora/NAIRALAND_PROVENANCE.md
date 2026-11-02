# Nairaland dataset provenance

- Dataset: `caleb-mnb/nairaland-conversations` (Hugging Face)
- Upstream license: CC-BY-NC-4.0 (attribution required, commercial use forbidden by default).
- Attribution is baked into every indexed record (`source`, `license` fields; see the
  `nairaland` family in `agentic_sales/corpus/families.py`).
- Access: gated repository. The project owner requested access through the Hugging Face
  access form, stating commercial use as the intended purpose. Access was granted with
  no follow-up messages from the author.
- Update, 2 Nov 2026: I asked the dataset author, Caleb Olusola, by direct message whether I could use the
  dataset commercially, including for this hackathon. He replied: "Go for it. It's open source." and
  "Don't worry about the license." That is his permission as the dataset owner. It is informal and the
  Hugging Face licence field still reads CC-BY-NC-4.0, so I keep it recorded here and credit him below.
  It covers his collection only; the posts were written by Nairaland users.
- Credit: the Nairaland conversation data is the work of Caleb Olusola (`caleb-mnb/nairaland-conversations`
  on Hugging Face). Every indexed record carries its `source` and `license` fields.
- Access: the data is not in this repo or the baseline repo, and I do not redistribute it.

Slice: commerce boards only (Business, Phones, Properties, Autos, Technology Market,
Adverts, Jobs/Vacancies, and kin) in `data/corpora/raw/nairaland_threads.jsonl`
(gitignored; rebuild the index with `python -m agentic_sales.corpus.build`).
