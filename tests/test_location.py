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


if __name__ == "__main__":
    unittest.main()
