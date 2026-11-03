# Corpus sample (Nigerian Pidgin, Nigerian English, Nigerian conversation)

About 1,700 records from three of the project's research corpora (Nigerian Pidgin 520, Nigerian English 560, Nigerian conversation 588; up to 50 from every topic layer,
evenly spaced), so the local side of the product can be tried without the full set (about 900 MB, kept out of git). These were written by the project's authors; they are LLM-synthesised reference material, not scraped
data. The hosted demo runs on the full corpora.

Use it:

```bash
mkdir -p data/corpora/raw
cp data/corpora/sample/*.jsonl data/corpora/raw/
python -m agentic_sales.corpus.build      # a few seconds; builds data/index/corpus.db
```

The build reports the other corpora as missing. That is expected; the agent still answers and uses what is indexed.

The Nairaland conversation slice is not part of this sample; see `../NAIRALAND_PROVENANCE.md`.
