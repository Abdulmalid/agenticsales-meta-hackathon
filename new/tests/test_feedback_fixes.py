"""Fixes from a tester's list: the sheet only brings stock and colours, staff cannot decide money, the history page, several product photos the
rep can send, photo matching against the shop's own pictures, a worried customer answered by the rep, lists in replies, and a quieter cold email."""
import base64
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from agentic_sales.server.app import create_app
    from agentic_sales.server.auth import AuthStore
    from agentic_sales.server.runtime import Runtimes
    HAVE_API = True
except ImportError:
    HAVE_API = False

from agentic_sales.config.business import BusinessConfig, Product, naira
from agentic_sales.core.types import TenantContext
from agentic_sales.inventory import sheet
from agentic_sales.inventory.store import LOW_STOCK, InventoryStore
from agentic_sales.language.analyzer import Analyzer
from agentic_sales.language.humanize import humanize
from agentic_sales.memory.store import TenantMemory
from agentic_sales.models.base import Message, ModelRequest, ModelResponse, ModelRouter
from agentic_sales.tools.registry import Status
from tests.test_backend import FakeGateway
from tests.test_inventory_api import BIZ

JPEG = b"\xff\xd8\xff" + b"j" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 200


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class SheetOnlyBringsStock(unittest.TestCase):
    def test_what_the_owner_typed_is_not_overridden_but_stock_and_colours_are(self):
        mem = TenantMemory(TenantContext("t1"), Path(tempfile.mkdtemp()))
        cfg, inv = BusinessConfig("Shop", "phones", products=[Product("IP17", "iPhone 17", naira(1_900_000), naira(1_800_000), "Typed in the console")]), InventoryStore(mem)
        text = "Product Name,Price (₦),Stock Quantity,Available Sizes/Colors\niPhone 17,1500000,,\"Blue (22), White (32)\"\nPixel 9,900000,4,\n"
        rep = sheet.apply(sheet.parse(text), cfg, inv, stock_only=True)
        iphone = cfg.product("IP17")
        self.assertEqual((iphone.name, iphone.price_kobo, iphone.description), ("iPhone 17", naira(1_900_000), "Typed in the console"))
        self.assertEqual(inv.info("IP17").variants, {"Blue": 22, "White": 32})                  # the colours and counts did come from the sheet
        self.assertEqual(rep.created, ["Pixel 9"])                                               # a product that is new still needs its row to exist
        self.assertEqual(next(p for p in cfg.products if p.name == "Pixel 9").price_kobo, naira(900_000))
        self.assertEqual(rep.updated, [])

    def test_a_file_import_still_updates_prices_because_the_owner_chose_it(self):
        mem = TenantMemory(TenantContext("t2"), Path(tempfile.mkdtemp()))
        cfg, inv = BusinessConfig("Shop", "phones", products=[Product("IP17", "iPhone 17", naira(1_900_000), naira(1_800_000), "")]), InventoryStore(mem)
        sheet.apply(sheet.parse("Product Name,Price (₦),Stock Quantity\niPhone 17,1500000,3\n"), cfg, inv, archive_missing=False, track=False)
        self.assertEqual(cfg.product("IP17").price_kobo, naira(1_500_000))

    def test_running_low_starts_at_five(self):
        mem = TenantMemory(TenantContext("t3"), Path(tempfile.mkdtemp()))
        inv = InventoryStore(mem)
        inv.set_levels("A", 5, None, actor="t", reason="manual")
        inv.set_levels("B", 6, None, actor="t", reason="manual")
        self.assertEqual(LOW_STOCK, 5)
        self.assertTrue(inv.info("A").low)
        self.assertFalse(inv.info("B").low)


class ListsInReplies(unittest.TestCase):
    def test_several_counts_stay_a_list_and_a_stray_marker_is_still_dropped(self):
        listed = humanize("Here is what we have for iPhone 17:\n1. LLA, 24 units\n2. LLA in White, 4 units\n3. LLA in Blue, 3 units")
        self.assertEqual(listed.splitlines()[1:], ["1. LLA, 24 units", "2. LLA in White, 4 units", "3. LLA in Blue, 3 units"])
        self.assertEqual(humanize("* We have it in stock.").strip(), "We have it in stock.")
        self.assertEqual(humanize("- one\n- two").splitlines(), ["- one", "- two"])


@unittest.skipUnless(HAVE_API, "needs fastapi + httpx (use the project .venv)")
class Api(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = AuthStore(self.root)
        self.admin = self.auth.create_tenant("shoes", BIZ, plan="growth")
        self.staff = self.auth.issue_key("shoes", "staff")
        self.runtimes = Runtimes(self.root, None, ModelRouter(), Analyzer(None))
        self.c = TestClient(create_app(self.root, self.runtimes, self.auth))
        self.rt = self.runtimes.get("shoes")
        self.pay = self.rt.orchestrator.payments
        self.pay.gateway = FakeGateway()
        self.rt.memory.remember("web:u1", "name", "Ada", "test")

    def H(self, key=None):
        return {"Authorization": f"Bearer {key or self.admin}"}

    def sale(self):
        r = self.pay.create_order_link("web:u1", "BOOT", 1, "a@b.co")
        self.pay.gateway.paid[r.reference] = ("success", naira(45_000), "NGN")
        self.pay.confirm(r.reference)
        return r.reference

    # ---- staff cannot decide money ------------------------------------------------------------------------------
    def test_staff_can_hand_a_customer_over_but_cannot_decide_a_discount_or_change_delivery_fees(self):
        money = self.rt.memory.request_approval("t", "web:u1", "discount", {"sku": "BOOT"}, ("below floor",))
        person = self.rt.memory.request_approval("t", "web:u1", "human_handoff", {"reason": "asked for a person"}, ("asked",))
        self.assertEqual(self.c.post(f"/v1/approvals/{money}/decision", headers=self.H(self.staff), json={"approve": True}).status_code, 403)
        self.assertEqual(self.c.post(f"/v1/approvals/{person}/decision", headers=self.H(self.staff), json={"approve": True}).status_code, 200)
        self.assertEqual(self.c.post(f"/v1/approvals/{money}/decision", headers=self.H(), json={"approve": False}).status_code, 200)
        self.assertEqual(self.c.put("/v1/inventory/BOOT", headers=self.H(self.staff), json={"fee_lagos_kobo": 1}).status_code, 403)
        self.assertEqual(self.c.put("/v1/inventory/BOOT", headers=self.H(self.staff), json={"total": 9}).status_code, 200)

    # ---- history -----------------------------------------------------------------------------------------------
    def test_history_lists_the_sale_and_the_stock_change_with_the_time_to_the_second_newest_first(self):
        self.c.put("/v1/inventory/BOOT", headers=self.H(), json={"total": 10})
        ref = self.sale()
        self.c.post(f"/v1/orders/{ref}/delivery", headers=self.H(), json={"stage": "shipped", "carrier": "GIG"})
        page = self.c.get("/v1/history", headers=self.H(self.staff)).json()
        kinds = {e["kind"] for e in page["items"]}
        self.assertTrue({"sales", "stock", "delivery"} <= kinds, kinds)
        sold = next(e for e in page["items"] if e["kind"] == "sales" and e["text"].startswith("Sold"))
        self.assertIn("Leather boot", sold["text"])
        self.assertIn("Ada", sold["text"])
        self.assertRegex(sold["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")                         # to the second
        self.assertEqual([e["ts"] for e in page["items"]], sorted((e["ts"] for e in page["items"]), reverse=True))
        only = self.c.get("/v1/history?kind=stock", headers=self.H()).json()["items"]
        self.assertTrue(only and {e["kind"] for e in only} == {"stock"})
        self.assertEqual(self.c.get("/v1/history").status_code, 401)

    def test_history_pages_back_in_time(self):
        for _ in range(3):
            self.sale()
        first = self.c.get("/v1/history?limit=2", headers=self.H()).json()
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["next_before"])
        older = self.c.get(f"/v1/history?limit=50&before={first['next_before']}", headers=self.H()).json()["items"]
        self.assertTrue(all(e["ts"] < first["next_before"] for e in older))

    # ---- several product photos the rep can send ---------------------------------------------------------------
    def test_a_product_can_have_five_photos_and_the_public_links_serve_only_those(self):
        for data in (JPEG, PNG, JPEG, JPEG, PNG):
            self.assertEqual(self.c.post("/v1/products/BOOT/images", headers=self.H(), json={"data": b64(data)}).status_code, 200)
        self.assertEqual(self.c.post("/v1/products/BOOT/images", headers=self.H(), json={"data": b64(JPEG)}).status_code, 422)     # a sixth is refused
        self.assertEqual(self.c.get("/v1/inventory", headers=self.H()).json()["products"][0]["image_count"], 5)
        two = self.c.get("/pi/shoes/BOOT/2")
        self.assertEqual((two.status_code, two.headers["content-type"], two.content), (200, "image/png", PNG))
        self.assertEqual(self.c.get("/pi/shoes/BOOT/6").status_code, 404)
        self.assertEqual(self.c.get("/pi/shoes/NOPE/1").status_code, 404)
        self.assertEqual(self.c.get("/pi/other/BOOT/1").status_code, 404)
        self.assertEqual(self.c.delete("/v1/products/BOOT/images/1", headers=self.H()).json()["count"], 4)        # the next photo becomes the main one
        self.assertEqual(self.c.get("/pi/shoes/BOOT/1").content, PNG)

    def test_the_rep_attaches_the_shops_own_photos_and_never_invents_a_link(self):
        from agentic_sales.tools.builtin import _show_photos
        from agentic_sales.tools.registry import TurnState

        self.c.post("/v1/products/BOOT/images", headers=self.H(), json={"data": b64(JPEG)})
        self.c.post("/v1/products/BOOT/images", headers=self.H(), json={"data": b64(PNG)})

        class Ctx:
            cfg = self.rt.cfg
            turn = TurnState()
            photos = staticmethod(lambda sku: [f"https://shop.test/pi/shoes/{sku}/{n}" for n in (1, 2)])
        res = _show_photos(Ctx, {"sku": "BOOT"})
        self.assertEqual((res.status, res.data["sent"]), (Status.OK, 2))
        self.assertEqual(Ctx.turn.images, ["https://shop.test/pi/shoes/BOOT/1", "https://shop.test/pi/shoes/BOOT/2"])
        self.assertEqual(_show_photos(Ctx, {"sku": "NOPE"}).status, Status.ERROR)
        Ctx.photos = staticmethod(lambda sku: [])
        self.assertEqual(_show_photos(Ctx, {"sku": "BOOT"}).data["sent"], 0)                    # no photo yet: say so, send nothing

    def test_photo_links_follow_the_reply_to_telegram_and_a_failed_photo_never_undoes_the_text(self):
        from agentic_sales.core.types import Channel, InboundMessage
        from agentic_sales.agents.orchestrator import TurnResult

        sent = []

        class Adapter:
            def send_image(self, to, url, secrets):
                sent.append((to, url))
                if len(sent) == 2:
                    from agentic_sales.channels.adapters import ChannelError
                    raise ChannelError("nope")
        msg = InboundMessage(Channel.TELEGRAM, "u1", "u1", "show me")
        res = TurnResult("here", "abcd1234abcd1234", images=["https://x/1", "https://x/2", "https://x/3"])
        self.rt._send_photos(Adapter(), msg, res)
        self.assertEqual(sent, [("u1", "https://x/1"), ("u1", "https://x/2")])                   # it stopped at the first failure, and did not raise

    # ---- matching a customer's photo against the shop's photos -------------------------------------------------
    def test_a_customer_photo_is_compared_with_the_shops_own_photos_and_the_colours_it_stocks(self):
        from agentic_sales.vision.reader import PhotoReader

        seen = []

        class Model:
            name = "fake"

            def complete(self, req: ModelRequest):
                seen.append(req)
                return ModelResponse('{"kind": "product", "sku": "BOOT", "confidence": 0.9, "description": "a brown boot", "visible_text": ""}', "fake")
        reading = PhotoReader(Model()).read(JPEG, self.rt.cfg.products, [("BOOT", PNG)], {"BOOT": ["41", "42"]})
        req = seen[0]
        self.assertEqual(len(req.images), 2)                                                      # the customer's, then the shop's
        self.assertIn("Reference photo 1 (image 2) shows SKU BOOT", req.system)
        self.assertIn("stocked in: 41, 42", req.system)
        self.assertEqual(reading.sku, "BOOT")
        PhotoReader(Model()).read(JPEG, self.rt.cfg.products)
        self.assertEqual(len(seen[1].images), 1)                                                  # no photos from the shop: as before

    def test_the_runtime_offers_only_active_products_photos_and_stays_under_the_size_cap(self):
        self.c.post("/v1/products/BOOT/images", headers=self.H(), json={"data": b64(JPEG)})
        self.rt.inventory.set_levels("BOOT", None, {"41": 2}, actor="t", reason="manual")
        refs, colours = self.rt._photo_references()
        self.assertEqual(refs, [("BOOT", JPEG)])
        self.assertEqual(colours, {"BOOT": ["41"]})
        self.rt.cfg.product("BOOT").in_stock = False
        self.assertEqual(self.rt._photo_references(), ([], {}))

    # ---- a worried customer is answered, not handed over --------------------------------------------------------
    def test_the_rep_is_given_true_proof_to_answer_is_this_shop_real(self):
        from agentic_sales.agents.sales import build_system
        from agentic_sales.language.analysis import detect_register, extract_signals, plan_style
        from agentic_sales.tools.builtin import default_registry
        from agentic_sales.tools.commerce import register_commerce_tools

        cfg = BusinessConfig(business_name="PhoneHub", industry="phones", address="12 Allen Avenue, Ikeja", cac_number="RC123456", refund_policy="7 days if unopened",
                             products=[Product("A", "Phone", 1, 1)])
        tools = default_registry()
        register_commerce_tools(tools)
        r = detect_register("is this legit?")
        s = build_system(cfg, "web", r, extract_signals("is this legit?"), plan_style(r, [], cfg.brand_voice), "", tools, {})
        for text in ("Trust:", "12 Allen Avenue, Ikeja", "RC123456", "7 days if unopened", "never to a personal one", "worries the shop is not real"):
            self.assertIn(text, s)
        self.assertIn("are NOT reasons", s)
        self.assertIn("worried customer asking whether the shop is real", s)

    # ---- the cold email -----------------------------------------------------------------------------------------
    def test_an_outreach_person_can_be_given_a_title_before_the_email_is_sent(self):
        o = self.rt.outreach
        o.import_prospects([{"email": "ada@example.com", "name": "Ada", "company": "Obi Stores", "note": "runs a phone shop"}], "business_contact", True)
        pid = o.list()[0]["id"]
        r = self.c.put(f"/v1/outreach/prospects/{pid}/details", headers=self.H(),
                       json={"name": "Ada Obi", "company": "Obi Stores", "title": "Procurement manager", "note": "buys in bulk"})
        self.assertEqual(r.status_code, 200, r.text)
        row = o.list()[0]
        self.assertEqual((row["name"], row["title"], row["note"]), ("Ada Obi", "Procurement manager", "buys in bulk"))
        self.assertEqual(self.c.put("/v1/outreach/prospects/999/details", headers=self.H(), json={}).status_code, 404)
        self.assertEqual(self.c.put(f"/v1/outreach/prospects/{pid}/details", headers=self.H(self.staff), json={}).status_code, 403)
        o.con.execute("UPDATE prospects SET status='sent' WHERE id=?", (pid,))
        self.assertEqual(self.c.put(f"/v1/outreach/prospects/{pid}/details", headers=self.H(), json={"name": "x"}).status_code, 422)   # too late to change who it went to


if __name__ == "__main__":
    unittest.main()
