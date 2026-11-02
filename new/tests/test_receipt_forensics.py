import unittest
from datetime import datetime, timedelta, timezone

from agentic_sales.security import receipt_forensics as rf

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=rf.LAGOS)


def sid(when: datetime, bank="058", seq="123456789012"):
    return bank.ljust(6, "0") + when.strftime("%y%m%d%H%M%S") + seq


class Decoding(unittest.TestCase):
    def test_the_time_inside_a_real_session_id_is_read_in_lagos_time(self):
        s = sid(datetime(2026, 10, 29, 9, 41, 7))
        self.assertEqual(len(s), 30)
        self.assertEqual(rf.decode_session_time(s), datetime(2026, 10, 29, 9, 41, 7, tzinfo=rf.LAGOS))

    def test_ids_that_are_not_30_digits_or_not_a_date_decode_to_nothing(self):
        for bad in ("", "123", "0" * 30, "058" + "999999999999" + "0" * 15):
            self.assertIsNone(rf.decode_session_time(bad), bad)

    def test_spaces_and_dashes_a_screenshot_adds_are_ignored(self):
        s = sid(NOW - timedelta(hours=1))
        spaced = " ".join([s[:6], s[6:18], s[18:]])
        self.assertEqual(rf.normalise_session_id(spaced), s)


class Checks(unittest.TestCase):
    def test_a_fresh_matching_receipt_has_no_findings(self):
        f = rf.check(rf.ReceiptFacts(sid(NOW - timedelta(minutes=20)), "PHONEHUB LAGOS LTD", 80_000_000), NOW.astimezone(timezone.utc),
                     expected_names=("PhoneHub Lagos",), expected_amount_kobo=80_000_000)
        self.assertFalse(f.suspicious, f.problems)

    def test_an_old_future_malformed_or_missing_session_id_is_flagged(self):
        cases = {
            sid(NOW - timedelta(days=3)): "not from today's transfer",
            sid(NOW + timedelta(hours=5)): "future",
            "1234567890": "has 10 digits",
            "": "no session ID",
            "058" + "999999999999" + "0" * 15: "real date",
        }
        for raw, word in cases.items():
            f = rf.check(rf.ReceiptFacts(raw), NOW)
            self.assertTrue(any(word in p for p in f.problems), (raw, f.problems))

    def test_a_different_beneficiary_or_amount_is_flagged_only_when_we_know_what_to_expect(self):
        fresh = sid(NOW - timedelta(minutes=5))
        f = rf.check(rf.ReceiptFacts(fresh, "Chinedu Okafor", 5_000_000), NOW, expected_names=("PhoneHub Lagos",), expected_amount_kobo=80_000_000)
        self.assertEqual(len(f.problems), 2)
        self.assertFalse(rf.check(rf.ReceiptFacts(fresh, "Chinedu Okafor", 5_000_000), NOW).suspicious)       # nothing configured to compare with
        self.assertFalse(rf.check(rf.ReceiptFacts(fresh, "", None), NOW, expected_names=("PhoneHub Lagos",)).suspicious)   # unreadable: not accused


if __name__ == "__main__":
    unittest.main()
