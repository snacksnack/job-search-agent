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

    def _ok_role(self, title, location, remote_status="remote"):
        return pipeline.location_ok(
            {"title": title, "location": location,
             "remoteStatus": remote_status, "remoteNotes": ""}, self.p)

    def test_title_region_excluded_when_location_says_nothing(self):
        """RC1-587: "Senior Sales Engineer - UK" at location "Remote" satisfies the
        US-remote rule on the location field alone and reached the board three
        times (10-25, 10-30, 10-31). When the location names no place, the title
        is the only location signal there is."""
        for title, loc in [("Senior Sales Engineer - UK", "Remote"),
                           ("Solutions Architect, EMEA", "Remote (Remote)"),
                           ("Technical Program Manager, APAC", ""),
                           ("Delivery Lead - Germany", "Remote")]:
            ok, reason = self._ok_role(title, loc)
            self.assertFalse(ok, f"expected exclude for {title!r} @ {loc!r}")
            self.assertIn("locationNonUS", reason)

    def test_title_region_is_a_territory_when_the_location_names_a_place(self):
        """The same token in a title whose location names a real place is the book
        of accounts the seat covers, not where it sits. Reading the title
        unconditionally would have rejected all of these."""
        for title, loc in [
            ("Senior Solutions Engineer, Enterprise - LATAM", "New York, NY"),
            ("Forward Deployed, Asset Management (EMEA)", "New York City"),
            ("Sales Engineer, LATAM", "Remote - USA (Remote)"),
            ("Solutions Engineer, EMEA", "Austin, TX"),
        ]:
            ok, reason = self._ok_role(title, loc)
            self.assertTrue(ok, f"expected include for {title!r} @ {loc!r} ({reason})")

    def test_title_naming_both_us_and_foreign_regions_kept(self):
        self.assertTrue(self._ok_role("Solutions Engineer, US & EMEA", "Remote")[0])

    def test_new_england_is_not_england(self):
        """"england" matched inside "New England", which would have rejected
        Zscaler's "Senior Sales Engineer - Majors, New England" (RC1-587)."""
        self.assertIsNone(pipeline.NON_US_RE.search("new england"))
        self.assertIsNotNone(pipeline.NON_US_RE.search("london, england uk"))
        self.assertTrue(self._ok_role("Senior Sales Engineer - Majors, New England",
                                      "Remote - Maine, USA; Remote - Vermont, USA")[0])

    def test_canadian_provinces_are_out_of_scope(self):
        """A posting often names only the province: "Ontario - Remote" passed
        because just the cities and "canada" were listed (RC1-587)."""
        for loc in ["Ontario - Remote", "Remote - Quebec", "British Columbia",
                    "Alberta, Canada", "Nova Scotia"]:
            ok, reason = self._ok_role("Technical Program Manager", loc)
            self.assertFalse(ok, f"expected exclude for {loc!r}")
            self.assertIn("locationNonUS", reason)

    def test_ontario_california_is_not_canada(self):
        for loc in ["Ontario, CA", "Ontario, California", "Ontario, OR"]:
            self.assertIsNone(pipeline.NON_US_RE.search(loc.lower()),
                              f"{loc!r} wrongly matched non-US")

    def test_location_names_no_geography(self):
        for loc in ["", "Remote", "Remote (Remote)", "remote - remote", "Anywhere"]:
            self.assertTrue(pipeline._location_names_no_geography(loc), repr(loc))
        for loc in ["Remote - USA (Remote)", "New York, NY", "United States", "US",
                    "Ontario - Remote", "Remote - Maine, USA"]:
            self.assertFalse(pipeline._location_names_no_geography(loc), repr(loc))


if __name__ == "__main__":
    unittest.main()
