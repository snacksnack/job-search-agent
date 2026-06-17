"""Unit tests for the ATS fetchers, with the network (http_get_json) mocked.

Covers the two providers added in RC1-92 — Workable and SmartRecruiters — at the
fetcher level (field mapping, URL construction, pagination, remote/location
handling) plus enrich_from_ats routing and an end-to-end watchlist sweep that
proves roles flow from these boards into run()."""
import contextlib
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401  (path setup)
from _fixtures import write_data_dir
import pipeline


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# --- Representative public-API payloads (trimmed to the fields the fetchers use) ---
WORKABLE_PAYLOAD = {
    "name": "Acme",
    "jobs": [
        {
            "title": "Senior Technical Program Manager",
            "shortcode": "ABC123",
            "url": "https://apply.workable.com/acme/j/ABC123/",
            "shortlink": "https://apply.workable.com/j/ABC123",
            "telecommuting": True,
            "city": "New York", "state": "New York", "country": "United States",
            "published_on": "2026-06-01", "created_at": "2026-05-20",
            "description": "<p>Drive cross-functional delivery.</p>",
            "requirements": "<ul><li>10y experience</li></ul>",
            "benefits": "<p>Health</p>",
        },
        {
            "title": "Office Manager",
            "shortcode": "ZZZ999",
            "url": "https://apply.workable.com/acme/j/ZZZ999/",
            "telecommuting": False,
            "city": "Austin", "state": "Texas", "country": "United States",
            "published_on": "2026-06-02",
            "description": "<p>Run the office.</p>",
        },
    ],
}

SR_LIST_PAGE = {
    "totalFound": 2,
    "content": [
        {"id": "743999000111", "name": "Solutions Engineer",
         "releasedDate": "2026-06-03T10:00:00.000Z",
         "location": {"city": "New York", "region": "NY", "country": "us", "remote": False}},
        {"id": "743999000222", "name": "Forward Deployed Engineer",
         "releasedDate": "2026-06-04T10:00:00.000Z",
         "location": {"city": "", "region": "", "country": "us", "remote": True}},
    ],
}

SR_DETAIL = {
    "id": "743999000111", "name": "Solutions Engineer",
    "releasedDate": "2026-06-03T10:00:00.000Z",
    "location": {"city": "New York", "region": "NY", "country": "us", "remote": False},
    "jobAd": {"sections": {
        "companyDescription": {"text": "<p>About Acme.</p>"},
        "jobDescription": {"text": "<p>Deploy with customers.</p>"},
        "qualifications": {"text": "<p>Python, APIs.</p>"},
    }},
}


class WorkableFetcherTests(unittest.TestCase):
    def setUp(self):
        self._orig = pipeline.http_get_json
        pipeline.http_get_json = lambda url, timeout=20: WORKABLE_PAYLOAD

    def tearDown(self):
        pipeline.http_get_json = self._orig

    def test_field_mapping_and_remote_location(self):
        rows = pipeline.fetch_workable("acme")
        self.assertEqual(len(rows), 2)
        tpm = rows[0]
        self.assertEqual(tpm["title"], "Senior Technical Program Manager")
        self.assertEqual(tpm["url"], "https://apply.workable.com/acme/j/ABC123/")
        self.assertEqual(tpm["postedDate"], "2026-06-01")
        self.assertIn("Remote", tpm["location"])            # telecommuting -> Remote tag
        self.assertIn("New York", tpm["location"])
        self.assertNotIn("<", tpm["description"])           # HTML stripped
        self.assertIn("Drive cross-functional delivery", tpm["description"])
        self.assertIn("10y experience", tpm["description"]) # requirements concatenated
        self.assertIsNone(tpm["salaryMin"])                 # widget exposes no comp

    def test_non_remote_location_has_no_remote_tag(self):
        rows = pipeline.fetch_workable("acme")
        self.assertNotIn("Remote", rows[1]["location"])


class SmartRecruitersFetcherTests(unittest.TestCase):
    def setUp(self):
        self._orig = pipeline.http_get_json
        pipeline.http_get_json = lambda url, timeout=20: SR_LIST_PAGE

    def tearDown(self):
        pipeline.http_get_json = self._orig

    def test_list_only_mapping_and_url_construction(self):
        rows = pipeline.fetch_smartrecruiters("Acme")
        self.assertEqual(len(rows), 2)
        se = rows[0]
        self.assertEqual(se["title"], "Solutions Engineer")
        self.assertEqual(se["url"], "https://jobs.smartrecruiters.com/Acme/743999000111")
        self.assertEqual(se["postedDate"], "2026-06-03")    # trimmed to date
        self.assertEqual(se["description"], "")             # lazy: no JD at list level
        self.assertIn("New York", se["location"])
        self.assertIn("Remote", rows[1]["location"])        # remote flag honored

    def test_pagination_stops_at_total_found(self):
        calls = []
        pipeline.http_get_json = lambda url, timeout=20: (calls.append(url), SR_LIST_PAGE)[1]
        pipeline.fetch_smartrecruiters("Acme")
        # totalFound=2 and the first page already returns 2 -> exactly one request
        self.assertEqual(len(calls), 1)

    def test_detail_fetch_fills_full_jd(self):
        pipeline.http_get_json = lambda url, timeout=20: SR_DETAIL
        rec = pipeline._smartrecruiters_detail("Acme", "743999000111")
        self.assertNotIn("<", rec["description"])
        self.assertIn("Deploy with customers", rec["description"])
        self.assertIn("About Acme", rec["description"])
        self.assertEqual(rec["url"], "https://jobs.smartrecruiters.com/Acme/743999000111")


class EnrichRoutingTests(unittest.TestCase):
    """enrich_from_ats should route Workable/SmartRecruiters URLs to the right fetcher."""

    def tearDown(self):
        # restore anything we monkeypatched
        import importlib
        importlib.reload(pipeline)

    def test_workable_apply_url(self):
        pipeline.fetch_workable = lambda slug: [
            {"url": f"https://apply.workable.com/{slug}/j/ABC123/", "title": "TPM"}]
        got = pipeline.enrich_from_ats("https://apply.workable.com/acme/j/ABC123/")
        self.assertEqual(got["title"], "TPM")

    def test_workable_legacy_subdomain_url(self):
        pipeline.fetch_workable = lambda slug: [
            {"url": f"https://{slug}.workable.com/j/ABC123", "title": "TPM"}]
        got = pipeline.enrich_from_ats("https://acme.workable.com/j/ABC123")
        self.assertEqual(got["title"], "TPM")

    def test_smartrecruiters_url_with_slug_suffix(self):
        pipeline._smartrecruiters_detail = lambda slug, jid: {
            "title": "SE", "url": f"https://jobs.smartrecruiters.com/{slug}/{jid}"}
        got = pipeline.enrich_from_ats(
            "https://jobs.smartrecruiters.com/Acme/743999000111-solutions-engineer")
        self.assertEqual(got["title"], "SE")

    def test_unparseable_url_returns_none(self):
        self.assertIsNone(pipeline.enrich_from_ats("https://smartrecruiters.com/no-id-here"))


class WatchlistSweepTests(unittest.TestCase):
    """End-to-end: a Workable + SmartRecruiters watchlist routes through ATS_FETCHERS
    and qualified roles land in jobs.json — the RC1-92 acceptance behavior."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "WkCo", "ats": "workable", "slug": "wkco"},
            {"company": "SrCo", "ats": "smartrecruiters", "slug": "SrCo"},
        ]}
        pipeline.DATA = write_data_dir(self._tmp.name, search=search)

        def fake_http(url, timeout=20):
            if "workable.com" in url:
                return WORKABLE_PAYLOAD
            if "smartrecruiters.com" in url:
                return SR_LIST_PAGE
            raise AssertionError(f"unexpected url {url}")
        pipeline.http_get_json = fake_http

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def test_roles_from_both_providers_are_ingested(self):
        rc = _quiet(pipeline.run, dry_run=False, max_age_days=3650)
        self.assertEqual(rc, 0)
        roles = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]
        titles = {r["title"] for r in roles}
        companies = {r["company"] for r in roles}
        # Workable TPM + SmartRecruiters SE/FDE qualify; Workable "Office Manager" is filtered
        self.assertIn("Senior Technical Program Manager", titles)
        self.assertIn("Solutions Engineer", titles)
        self.assertIn("Forward Deployed Engineer", titles)
        self.assertNotIn("Office Manager", titles)
        self.assertEqual(companies, {"WkCo", "SrCo"})
        # SmartRecruiters role carries the constructed ATS url (enrichable later)
        sr = next(r for r in roles if r["company"] == "SrCo")
        self.assertIn("jobs.smartrecruiters.com", sr["url"])


class LazyReenrichFillTests(unittest.TestCase):
    """A list-only SmartRecruiters role (empty description) must get its JD filled by
    the re-enrich pass even when the fetched JD is short (< min_gain) -- regression
    guard for the lazy-fill design RC1-92 introduced."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_enrich = pipeline.enrich_from_ats
        self._tmp = tempfile.TemporaryDirectory()
        jobs = {"schemaVersion": 2, "roles": [{
            "id": "srco-se", "company": "SrCo", "title": "Solutions Engineer",
            "url": "https://jobs.smartrecruiters.com/SrCo/743999000111",
            "atsUrl": "https://jobs.smartrecruiters.com/SrCo/743999000111",
            "sourceUrl": "", "location": "New York, NY", "matchPercent": 60,
            "foundDate": pipeline.TODAY, "fullDescription": "",   # list-only: no JD yet
        }], "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs)
        pipeline.enrich_from_ats = lambda url: {
            "title": "Solutions Engineer", "location": "New York, NY", "url": url,
            "description": "Deploy with customers. Python, APIs.",  # short, < min_gain
            "postedDate": pipeline.TODAY, "salaryMin": None, "salaryMax": None,
        }

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.enrich_from_ats = self._orig_enrich
        self._tmp.cleanup()

    def test_empty_description_is_filled_even_when_short(self):
        _quiet(pipeline.reenrich, dry_run=False)
        role = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"][0]
        self.assertIn("Deploy with customers", role["fullDescription"])
        self.assertGreater(role["matchPercent"], 0)


if __name__ == "__main__":
    unittest.main()
