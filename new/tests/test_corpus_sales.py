import unittest
from pathlib import Path

from agentic_sales.corpus.families import NG_SALES, SALES_GENERAL
from agentic_sales.corpus.sales import conversion_reference, leadgen_reference, retention_reference
from agentic_sales.corpus.store import CorpusStore
from agentic_sales.language.analysis import detect_register, extract_signals

INDEX, RAW = Path("data/index/corpus.db"), Path("data/corpora/raw")


@unittest.skipUnless(INDEX.exists(), "build the index first")
class SalesCorpora(unittest.TestCase):
    def setUp(self):
        self.store = CorpusStore(INDEX, RAW)
        self.addCleanup(self.store.close)

    def test_conversion_tactics_for_negotiation_turns_only(self):
        block = conversion_reference(self.store, "abeg reduce last price na", {"negotiation"})
        self.assertIn("[conversion]", block)
        self.assertNotIn("₦", block)  # methodology only: never corpus prices
        self.assertEqual(conversion_reference(self.store, "good morning o", {"greeting"}), "")

    def test_retention_playbook_for_recovery_purpose(self):
        block = retention_reference(self.store, "abandoned_lead_recovery")
        self.assertIn("[retention]", block)

    def test_leadgen_channel_playbooks(self):
        blocks = leadgen_reference(self.store, "whatsapp broadcast channel sales", limit=2)
        self.assertTrue(blocks)
        self.assertTrue(all(b.startswith("[leadgen]") for b in blocks))

    def test_sales_domains_stay_separated(self):
        for h in self.store.search(SALES_GENERAL, "last price", limit=3):
            self.assertEqual(h.domain, SALES_GENERAL)
        for h in self.store.search(NG_SALES, "outbound channel", limit=3):
            self.assertEqual(h.domain, NG_SALES)

    def test_negotiation_turn_gets_conversion_reference(self):
        from agentic_sales.corpus.context import build_reference

        text = "abeg wetin be your last price for this one"
        ref = build_reference(self.store, text, detect_register(text), extract_signals(text))
        self.assertIn("[conversion]", ref)


class CorpusComposerTest(unittest.TestCase):
    def test_playbook_injected_without_changing_template_output(self):
        from agentic_sales.config.business import BusinessConfig
        from agentic_sales.core.types import TenantContext
        from agentic_sales.leads.models import Lead
        from agentic_sales.leads.retention import CorpusComposer, TemplateComposer

        seen = {}

        class Spy:
            def compose(self, purpose, lead, facts, cfg):
                seen.update(facts)
                return TemplateComposer().compose(purpose, lead, facts, cfg)

        store = CorpusStore(INDEX, RAW) if INDEX.exists() else None
        self.addCleanup(lambda: store.close() if store else None)
        comp = CorpusComposer(Spy(), store)
        cfg = BusinessConfig("Shop", "retail")
        lead = Lead(id=1, customer_key="web:u", source="web")
        out = comp.compose("abandoned_lead_recovery", lead, {}, cfg)
        plain = TemplateComposer().compose("abandoned_lead_recovery", lead, {}, cfg)
        self.assertEqual(out, plain)  # templates ignore the playbook; output unchanged
        if store is not None:
            self.assertIn("playbook", seen)
        comp_none = CorpusComposer(Spy(), None)
        self.assertEqual(comp_none.compose("abandoned_lead_recovery", lead, {}, cfg), plain)


if __name__ == "__main__":
    unittest.main()
