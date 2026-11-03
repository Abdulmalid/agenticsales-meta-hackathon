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

`nairaland_threads.jsonl` is a small slice (393 threads, 25 per board at most) of Caleb Olusola's dataset `caleb-mnb/nairaland-conversations`, shared here with his permission
(see `../NAIRALAND_PROVENANCE.md`) and with credit to him. Every record keeps its `source`, `thread_url` and `license` fields. Usernames were already pseudonymised by the
dataset; I additionally dropped every thread containing a link, email, phone number or handle. It is not the whole dataset; get that from Hugging Face.
