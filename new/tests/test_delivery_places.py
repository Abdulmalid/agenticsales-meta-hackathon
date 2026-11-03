"""Delivery prices for named places, and stock labels the agent can tell apart (a colour is not a version)."""
import tempfile
import unittest
from pathlib import Path

from agentic_sales.core.types import TenantContext
from agentic_sales.inventory.store import InventoryStore, parse_places, places_text, split_variant
from agentic_sales.memory.store import TenantMemory


class Places(unittest.TestCase):
    def test_a_plain_amount_is_one_price_for_every_other_state(self):
        self.assertEqual(parse_places("4,500"), (450_000, {}))
        self.assertEqual(parse_places("₦7k"), (700_000, {}))
        self.assertEqual(parse_places(""), (None, {}))

    def test_a_list_names_places_and_other_is_the_price_for_the_rest(self):
        other, places = parse_places("Ilorin (3,500), Kogi (15,000), Sokoto - 10,000; Port Harcourt N6000, Other 7,000")
        self.assertEqual(other, 700_000)
        self.assertEqual(places, {"Ilorin": 350_000, "Kogi": 1_500_000, "Sokoto": 1_000_000, "Port Harcourt": 600_000})
        self.assertEqual(parse_places("Ilorin 3500"), (None, {"Ilorin": 350_000}))                # the n in Ilorin is not a naira sign
        self.assertEqual(parse_places(places_text(other, places)), (other, places))                  # what the console shows reads back the same

    def test_text_that_is_neither_is_refused_with_a_reason(self):
        for bad in ("Ilorin", "soon", "Kogi 99,999,999"):
            with self.assertRaises(ValueError):
                parse_places(bad)

    def test_places_are_stored_per_product_and_shown_to_the_agent(self):
        inv = InventoryStore(TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp())))
        inv.set_fees("IP15", 500_000, 700_000)
        inv.set_places("IP15", {"Ilorin": 350_000})
        info = inv.info("IP15")
        self.assertEqual((info.fee_local_kobo, info.fee_other_kobo, info.places), (500_000, 700_000, {"Ilorin": 350_000}))
        self.assertEqual(inv.all_info()["IP15"].places, {"Ilorin": 350_000})
        inv.forget("IP15")
        self.assertEqual(inv.info("IP15").places, {})


class Colours(unittest.TestCase):
    def test_a_version_is_not_a_colour(self):
        self.assertEqual(split_variant("LLA in White"), ("LLA", "White"))
        self.assertEqual(split_variant("burgundy"), ("", "burgundy"))
        self.assertEqual(split_variant("Space Black"), ("", "Space Black"))
        self.assertEqual(split_variant("eSim"), ("eSim", ""))
        self.assertEqual(split_variant("42"), ("42", ""))

    def test_the_agent_is_told_which_labels_are_colours_and_which_are_not(self):
        inv = InventoryStore(TenantMemory(TenantContext("shop-a"), Path(tempfile.mkdtemp())))
        inv.set_levels("IP17", None, {"burgundy": 70, "white": 12, "LLA": 24, "LLA in White": 4, "LLA in Blue": 3, "eSim": 50, "eSim in Green": 22}, actor="t", reason="manual")
        line = inv.prompt_line("IP17")
        self.assertIn("Colours: burgundy, white, Blue, Green", line)
        self.assertIn("NOT colours: LLA, eSim", line)
        inv.set_levels("SHOE", None, {"41": 2, "42": 3}, actor="t", reason="manual")
        self.assertNotIn("Colours", inv.prompt_line("SHOE"))                                          # sizes are left as they were


try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Api(unittest.TestCase):
    def test_the_owner_types_places_with_prices_and_the_console_reads_them_back(self):
        from agentic_sales.language.analyzer import Analyzer
        from agentic_sales.models.base import ModelRouter
        from tests.test_scheduler import BIZ
        root = Path(tempfile.mkdtemp())
        auth = AuthStore(root)
        key = auth.create_tenant("shop-a", BIZ, plan="growth")
        staff = auth.issue_key("shop-a", "staff")
        c = TestClient(create_app(root, Runtimes(root, None, ModelRouter(), Analyzer(None)), auth))
        H = {"Authorization": f"Bearer {key}"}
        text = "Ilorin (3,500), Kogi (15,000), Other 7,000"
        self.assertEqual(c.put("/v1/inventory/IP15", headers={"Authorization": f"Bearer {staff}"}, json={"fee_other_text": text}).status_code, 403)
        self.assertEqual(c.put("/v1/inventory/IP15", headers=H, json={"fee_other_text": "Ilorin"}).status_code, 422)
        self.assertEqual(c.put("/v1/inventory/IP15", headers=H, json={"fee_lagos_kobo": 500_000, "fee_other_text": text}).status_code, 200)
        row = next(p for p in c.get("/v1/inventory", headers=H).json()["products"] if p["sku"] == "IP15")
        self.assertEqual((row["fee_other_kobo"], row["fee_places"]), (700_000, {"Ilorin": 350_000, "Kogi": 1_500_000}))
        self.assertEqual(row["fee_other_text"], "Ilorin 3,500, Kogi 15,000, Other 7,000")
        self.assertEqual(c.put("/v1/inventory/IP15", headers=H, json={"fee_other_text": "4,500"}).status_code, 200)              # back to one price
        row = next(p for p in c.get("/v1/inventory", headers=H).json()["products"] if p["sku"] == "IP15")
        self.assertEqual((row["fee_other_kobo"], row["fee_places"]), (450_000, {}))


if __name__ == "__main__":
    unittest.main()
