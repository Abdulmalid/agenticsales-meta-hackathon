import unittest
from pathlib import Path

from agentic_sales.corpus.dialogue import dialogue_reference
from agentic_sales.corpus.families import NG_DIALOGUE
from agentic_sales.corpus.store import CorpusStore

INDEX, RAW = Path("data/index/corpus.db"), Path("data/corpora/raw")
SLICE = RAW / "nairaland_threads.jsonl"


@unittest.skipUnless(INDEX.exists() and SLICE.exists(), "download the Nairaland slice first")
class NairalandDialogue(unittest.TestCase):
    def setUp(self):
        self.store = CorpusStore(INDEX, RAW)
        self.addCleanup(self.store.close)

    def test_slice_is_indexed(self):
        hits = self.store.search(NG_DIALOGUE, "price", limit=3)
        self.assertTrue(hits, "nairaland family empty: rebuild the index")
        self.assertTrue(all(h.domain == NG_DIALOGUE for h in hits))

    def test_negotiation_gets_real_utterances(self):
        block = dialogue_reference(self.store, "abeg last price", {"negotiation"})
        self.assertIn("[dialogue:", block)

    def test_greeting_gets_nothing(self):
        self.assertEqual(dialogue_reference(self.store, "good morning o", {"greeting"}), "")

    def test_attribution_survives_indexing(self):
        hits = self.store.search(NG_DIALOGUE, "price", limit=1)
        self.assertIn("nairaland-conversations", hits[0].record.get("source", ""))
        self.assertIn("CC-BY-NC", hits[0].record.get("license", ""))


if __name__ == "__main__":
    unittest.main()
