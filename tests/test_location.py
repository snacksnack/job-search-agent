"""Location rule: NYC-metro variants, upstate exclusion, US remote scope, hybrid."""
import unittest

import _fixtures  # noqa: F401
from _fixtures import make_profile
import pipeline


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def _ok(self, location, remote_status="", remote_notes=""):
        role = {"location": location, "remoteStatus": remote_status, "remoteNotes": remote_notes}
        return pipeline.location_ok(role, self.p)[0]

    def test_nyc_metro_variants_included(self):
        for loc in ["New York", "New York City", "New York, NY", "NYC", "Manhattan",
                    "Brooklyn", "Queens, NY", "The Bronx", "Staten Island",
                    "Long Island City, NY", "Brooklyn, New York", "Greater New York"]:
            self.assertTrue(self._ok(loc), f"expected include for {loc!r}")

    def test_nyc_metro_with_onsite_or_hybrid_included(self):
        for loc in ["New York, NY (Onsite)", "Brooklyn - Hybrid", "Manhattan (in-office)"]:
            self.assertTrue(self._ok(loc), f"expected include for {loc!r}")

    def test_upstate_not_false_matched_by_ny_regex(self):
        for loc in ["albany, ny", "buffalo, ny", "rochester, ny", "syracuse, ny", "newark, nj"]:
            self.assertIsNone(pipeline.NY_METRO_RE.search(loc), f"{loc!r} wrongly matched NY metro")

    def test_upstate_onsite_excluded(self):
        for loc in ["Albany, NY (Onsite)", "Buffalo, NY - Hybrid", "Rochester, NY (in-office)"]:
            self.assertFalse(self._ok(loc), f"expected exclude for {loc!r}")

    def test_remote_us_included(self):
        for loc in ["Remote - US", "Remote, US", "Remote (United States)", "Remote - USA",
                    "Remote - North America", "Remote"]:
            self.assertTrue(self._ok(loc, remote_status="remote"), f"expected include for {loc!r}")

    def test_foreign_remote_excluded(self):
        for loc in ["Remote - Netherlands", "Remote - UK", "Remote - Germany", "Remote - India"]:
            ok, reason = pipeline.location_ok(
                {"location": loc, "remoteStatus": "remote", "remoteNotes": ""}, self.p)
            self.assertFalse(ok, f"expected exclude for {loc!r}")
            self.assertIn("locationNonUS", reason)

    def test_us_remote_with_foreign_city_kept(self):
        self.assertTrue(self._ok("US-Remote, London, England UK", remote_status="remote"))

    def test_hybrid_outside_metro_excluded(self):
        self.assertFalse(self._ok("Austin, TX (Hybrid)"))
        self.assertFalse(self._ok("Onsite San Francisco", remote_status="onsite"))

    def test_us_cities_not_flagged_nonus(self):
        for loc in ["Austin, TX", "San Francisco, CA", "Chicago, IL"]:
            # bare US city, no remote/hybrid keyword -> inclusive default (not a non-US exclusion)
            ok, reason = pipeline.location_ok(
                {"location": loc, "remoteStatus": "", "remoteNotes": ""}, self.p)
            self.assertTrue(ok)
            self.assertIsNone(reason)

    def test_nationwide_only_location_not_read_as_onsite(self):
        """RC1-586: LinkedIn renders a US-remote posting as a bare "United States"
        when its Remote filter established remoteness and there is no city. The
        cascade found no "remote" token, fell through to normalize()'s derived
        remoteStatus of "onsite", and rejected the role as locationHybrid --
        silently dropping 10 qualifying roles on 2026-10-31, Docker's Principal
        TPM, Forward Deployed Engineering (81%) among them."""
        for loc in ["United States", "united states", "US", "U.S.", "USA",
                    "United States of America", "Nationwide"]:
            ok, reason = pipeline.location_ok(
                {"location": loc, "remoteStatus": "onsite", "remoteNotes": ""}, self.p)
            self.assertTrue(ok, f"expected include for {loc!r} (got {reason})")

    def test_nationwide_only_with_explicit_onsite_note_still_excluded(self):
        """The scope string alone can't rule a role out, but an explicit
        arrangement in remoteNotes still does."""
        ok, reason = pipeline.location_ok(
            {"location": "United States", "remoteStatus": "onsite",
             "remoteNotes": "Hybrid, 3 days a week in our Austin office"}, self.p)
        self.assertFalse(ok)
        self.assertIn("locationHybrid", reason)

    def test_country_qualified_city_still_judged_on_the_city(self):
        """Only a location that is *nothing but* a nationwide scope gets the pass:
        "Milpitas, California, United States" is still an onsite posting."""
        ok, reason = pipeline.location_ok(
            {"location": "Milpitas, California, United States", "remoteStatus": "onsite",
             "remoteNotes": ""}, self.p)
        self.assertFalse(ok)
        self.assertIn("locationHybrid", reason)


class NormalizeRemoteStatusTests(unittest.TestCase):
    """normalize() derives remoteStatus from the location string when a source
    doesn't supply one. A country name is an eligibility scope, not a worksite."""

    def test_nationwide_only_location_is_unknown_not_onsite(self):
        for loc in ["United States", "USA", "Nationwide"]:
            role = pipeline.normalize({"title": "TPM", "company": "X", "location": loc},
                                      "linkedinKeyword")
            self.assertEqual(role["remoteStatus"], "unknown", loc)

    def test_city_location_is_still_onsite(self):
        role = pipeline.normalize({"title": "TPM", "company": "X", "location": "Milpitas, CA"},
                                  "linkedinKeyword")
        self.assertEqual(role["remoteStatus"], "onsite")

    def test_explicit_tokens_still_win(self):
        for loc, expected in [("Remote - United States", "remote"),
                              ("United States (Hybrid)", "hybrid"),
                              ("", "unknown")]:
            role = pipeline.normalize({"title": "TPM", "company": "X", "location": loc},
                                      "linkedinKeyword")
            self.assertEqual(role["remoteStatus"], expected, loc)


if __name__ == "__main__":
    unittest.main()
