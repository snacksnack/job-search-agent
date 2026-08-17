"""Aggregator discovery feeds (RC1-276): 8 fetchers, mocked responses."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline

TERMS = [t.lower() for t in pipeline.AGG_DEFAULT_TERMS]

REMOTIVE = {"jobs": [
    {"id": 1, "title": "Senior Technical Program Manager", "company_name": "Acme",
     "candidate_required_location": "USA Only", "url": "https://remotive.com/remote-jobs/pm/1",
     "description": "<p>Own programs.</p>", "publication_date": "2026-08-15T08:00:00",
     "salary": "$180k"},
    {"id": 2, "title": "Graphic Designer", "company_name": "Nope",
     "url": "https://remotive.com/remote-jobs/design/2", "description": "x"},
]}

REMOTEOK = [
    {"legal": "API terms blob"},   # first element is metadata, not a posting
    {"id": "3", "position": "Forward Deployed Engineer", "company": "Beta",
     "location": "Worldwide", "url": "https://remoteok.com/remote-jobs/3",
     "description": "<p>Deploy.</p>", "date": "2026-08-14T00:00:00+00:00",
     "salary_min": 150000, "salary_max": 200000},
    {"id": "4", "position": "Accountant", "company": "Nope",
     "url": "https://remoteok.com/remote-jobs/4", "description": "x"},
]

HIMALAYAS = {"jobs": [
    {"title": "Solutions Engineer", "companyName": "Gamma",
     "locationRestrictions": ["United States"], "applicationLink": "https://himalayas.app/companies/gamma/jobs/se",
     "description": "<p>Pre-sales.</p>", "pubDate": 1755200000,
     "minSalary": 140000, "maxSalary": 170000},
]}

MUSE_PAGE0 = {"results": [
    {"id": 5, "name": "Senior Program Manager", "company": {"name": "Delta"},
     "locations": [{"name": "Flexible / Remote"}],
     "refs": {"landing_page": "https://www.themuse.com/jobs/delta/senior-program-manager"},
     "contents": "<p>Drive delivery.</p>", "publication_date": "2026-08-13T00:00:00Z"},
]}

JOBICY = {"jobs": [
    {"id": 6, "jobTitle": "Technical Account Manager", "companyName": "Epsilon",
     "jobGeo": "USA", "url": "https://jobicy.com/jobs/6",
     "jobDescription": "<p>Own accounts.</p>", "pubDate": "2026-08-12 09:30:00",
     "annualSalaryMin": 130000, "annualSalaryMax": 160000},
]}

WORKINGNOMADS = [
    {"title": "Delivery Manager", "company_name": "Zeta", "locations": "USA",
     "url": "https://www.workingnomads.com/jobs/delivery-manager-zeta",
     "description": "<p>Deliver.</p>", "pub_date": "2026-08-11T00:00:00"},
    {"title": "Nurse", "company_name": "Nope", "url": "x", "description": "x"},
]

WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Eta Corp: Technical Program Manager</title>
    <region>Anywhere in the World</region>
    <link>https://weworkremotely.com/remote-jobs/eta-corp-tpm</link>
    <description>&lt;p&gt;Coordinate programs.&lt;/p&gt;</description>
    <pubDate>Fri, 15 Aug 2026 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Nope Inc: Copywriter</title>
    <link>https://weworkremotely.com/remote-jobs/nope-copywriter</link>
    <description>x</description>
  </item>
</channel></rss>"""

ADZUNA = {"results": [
    {"id": "7", "title": "Technical Program Manager", "company": {"display_name": "Theta"},
     "location": {"display_name": "Remote, US"}, "redirect_url": "https://www.adzuna.com/land/ad/7",
     "description": "Truncated JD ...", "created": "2026-08-10T00:00:00Z",
     "salary_min": 150000.0, "salary_max": 190000.0},
]}


class AggregatorFetcherTests(unittest.TestCase):
    def setUp(self):
        self._orig_get = pipeline.http_get_json
        self._orig_text = pipeline.http_get_text

    def tearDown(self):
        pipeline.http_get_json = self._orig_get
        pipeline.http_get_text = self._orig_text

    def test_remotive_maps_all_items(self):
        pipeline.http_get_json = lambda url, timeout=20: REMOTIVE
        out = pipeline.fetch_agg_remotive({})
        self.assertEqual(len(out), 2)                        # mapping only; filter is in gather
        r = out[0]
        self.assertEqual((r["company"], r["location"]), ("Acme", "USA Only"))
        self.assertEqual(r["postedDate"], "2026-08-15")
        self.assertNotIn("<", r["description"])

    def test_remoteok_skips_metadata_blob(self):
        pipeline.http_get_json = lambda url, timeout=20: REMOTEOK
        out = pipeline.fetch_agg_remoteok({})
        self.assertEqual(len(out), 2)                        # metadata blob skipped
        self.assertEqual(out[0]["title"], "Forward Deployed Engineer")
        self.assertEqual(out[0]["salaryMax"], 200000)

    def test_himalayas_epoch_date_and_locations(self):
        pipeline.http_get_json = lambda url, timeout=20: HIMALAYAS
        out = pipeline.fetch_agg_himalayas({})
        self.assertEqual(out[0]["location"], "United States")
        self.assertEqual(out[0]["postedDate"], "2025-08-14")    # epoch converted
        self.assertEqual(out[0]["salaryMin"], 140000)

    def test_themuse_paginates_until_empty(self):
        calls = []
        def fake(url, timeout=20):
            calls.append(url)
            return MUSE_PAGE0 if "page=0" in url else {"results": []}
        pipeline.http_get_json = fake
        out = pipeline.fetch_agg_themuse({"pages": 3})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["company"], "Delta")
        self.assertEqual(len(calls), 2)                      # stopped at first empty page

    def test_jobicy_maps_salary(self):
        pipeline.http_get_json = lambda url, timeout=20: JOBICY
        out = pipeline.fetch_agg_jobicy({})
        self.assertEqual(out[0]["salaryMin"], 130000)
        self.assertEqual(out[0]["postedDate"], "2026-08-12")

    def test_workingnomads_maps_all(self):
        pipeline.http_get_json = lambda url, timeout=20: WORKINGNOMADS
        out = pipeline.fetch_agg_workingnomads({})
        self.assertEqual([r["title"] for r in out], ["Delivery Manager", "Nurse"])
        self.assertEqual(out[0]["remoteStatus"], "remote")

    def test_title_prefilter_helper(self):
        self.assertTrue(pipeline._title_hit("Sr. Technical Program Manager", TERMS))
        self.assertFalse(pipeline._title_hit("Graphic Designer", TERMS))

    def test_weworkremotely_parses_company_title_and_rfc822_date(self):
        fetched = []
        def fake_text(url, timeout=20):
            fetched.append(url)
            return WWR_RSS
        pipeline.http_get_text = fake_text
        out = pipeline.fetch_agg_weworkremotely({"categories": ["remote-project-management-jobs"]})
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0]["company"], out[0]["title"]),
                         ("Eta Corp", "Technical Program Manager"))
        self.assertEqual(out[0]["postedDate"], "2026-08-15")
        self.assertIn("remote-project-management-jobs.rss", fetched[0])

    def test_weworkremotely_bad_xml_raises_valueerror(self):
        pipeline.http_get_text = lambda url, timeout=20: "not xml at all <"
        with self.assertRaises(ValueError):
            pipeline.fetch_agg_weworkremotely({"categories": ["x"]})

    def test_adzuna_skipped_without_keys(self):
        os.environ.pop("ADZUNA_APP_ID", None)
        os.environ.pop("ADZUNA_APP_KEY", None)
        self.assertIsNone(pipeline.fetch_agg_adzuna({}))

    def test_adzuna_maps_and_flags_truncated(self):
        os.environ["ADZUNA_APP_ID"] = "id"
        os.environ["ADZUNA_APP_KEY"] = "key"
        try:
            pipeline.http_get_json = lambda url, timeout=20: ADZUNA if "/1?" in url else {"results": []}
            out = pipeline.fetch_agg_adzuna({})
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["descriptionTruncated"])
            self.assertEqual(out[0]["salaryMin"], 150000)
            self.assertEqual(out[0]["remoteStatus"], "remote")
        finally:
            del os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"]


class AggregatorPipelineTests(unittest.TestCase):
    """End-to-end: an enabled method:api search entry flows into run()."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_get = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        search = {"schemaVersion": 2, "watchlist": [], "searches": [
            {"id": "agg-remotive", "name": "Remotive", "source": "remotive",
             "platform": "remotive", "method": "api", "enabled": True, "params": {}},
            {"id": "agg-jobicy", "name": "Jobicy", "source": "jobicy",
             "platform": "jobicy", "method": "api", "enabled": True, "params": {}},
            {"id": "li", "name": "LinkedIn", "source": "linkedinKeyword",
             "platform": "linkedin", "method": "browser", "enabled": True},   # ignored
        ]}
        pipeline.DATA = write_data_dir(self._tmp.name, search=search)

        today = pipeline.TODAY
        remotive_fresh = {"jobs": [dict(REMOTIVE["jobs"][0],
                                        publication_date=today + "T08:00:00")]}
        def fake(url, timeout=20):
            if "remotive.com" in url:
                return remotive_fresh
            raise urllib.error.HTTPError(url, 503, "down", None, io.BytesIO(b""))
        pipeline.http_get_json = fake

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_get
        self._tmp.cleanup()

    def test_feed_roles_ingested_and_health_recorded(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pipeline.run(dry_run=False, max_age_days=3)
        self.assertEqual(rc, 0)
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        roles = jobs["roles"]
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual((r["company"], r["source"]), ("Acme", "remotive"))
        self.assertEqual(r["sourceUrl"], "https://remotive.com/remote-jobs/pm/1")
        self.assertEqual(r["atsUrl"], "")                    # ATS link comes via --resolve-ats

        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        by_src = {s.get("aggregator"): s for s in log["sources"] if "aggregator" in s}
        self.assertEqual(by_src["remotive"]["status"], "ok")
        self.assertEqual(by_src["remotive"]["postings"], 1)
        self.assertEqual(by_src["jobicy"]["status"], "error")
        self.assertEqual(by_src["jobicy"]["error"], "HTTP 503")
        self.assertEqual(log["sourceHealth"], {"ok": 1, "empty": 0, "failed": 1, "skipped": 0})
        out = buf.getvalue()
        self.assertIn("FETCH FAILED  jobicy (feed): HTTP 503", out)


if __name__ == "__main__":
    unittest.main()
