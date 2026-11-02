import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agentic_sales.language.analyzer import Analyzer
from agentic_sales.models.base import ModelRouter
from agentic_sales.server.app import create_app
from agentic_sales.server.auth import AuthStore
from agentic_sales.server.runtime import Runtimes
from agentic_sales.webpages import legal


class LegalPages(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.c = TestClient(create_app(root, Runtimes(root, None, ModelRouter(), Analyzer(None)), AuthStore(root)))

    def test_the_three_pages_the_platforms_require_are_public(self):
        for path, phrase in (("privacy", "What we collect"), ("terms", "Acceptable use"), ("data-deletion", "If you messaged a business")):
            r = self.c.get(f"/legal/{path}")                                   # no key needed
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(phrase, r.text)
            self.assertIn("text/html", r.headers["content-type"])
            self.assertEqual(r.headers["x-content-type-options"], "nosniff")
            self.assertIn("default-src 'none'", r.headers["content-security-policy"])
            for other in ("/legal/privacy", "/legal/terms", "/legal/data-deletion"):
                self.assertIn(f'href="{other}"', r.text)                       # each page links to the others

    def test_unknown_pages_are_not_found_and_the_routes_stay_out_of_the_api_schema(self):
        self.assertEqual(self.c.get("/legal/secrets").status_code, 404)
        self.assertEqual(self.c.get("/legal/privacy/extra").status_code, 404)
        self.assertEqual(self.c.get("/legal/%2e%2e%2fv1%2fme").status_code, 404)
        self.assertFalse([p for p in self.c.get("/openapi.json").json()["paths"] if p.startswith("/legal")])

    def test_the_operator_sets_the_name_and_contact_and_markup_cannot_be_injected(self):
        with mock.patch.dict("os.environ", {"LEGAL_ENTITY": "Ayma <b>Technologies</b>", "LEGAL_CONTACT_EMAIL": 'privacy@ayma.test"><script>x</script>'}):
            text = self.c.get("/legal/data-deletion").text
        self.assertIn("Ayma &lt;b&gt;Technologies&lt;/b&gt;", text)
        self.assertNotIn("<script>", text)
        self.assertIn("mailto:privacy@ayma.test&quot;&gt;&lt;script&gt;", text)

    def test_without_a_contact_email_the_pages_say_where_to_look_instead_of_a_blank(self):
        with mock.patch.dict("os.environ", {"LEGAL_CONTACT_EMAIL": ""}):
            self.assertIn("the contact details published on our website", legal.privacy())
            self.assertNotIn("mailto:", legal.data_deletion())


if __name__ == "__main__":
    unittest.main()
