"""End-to-end: run() dedup/filter/write and reenrich(), with mocked ATS network."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import make_profile, write_data_dir
import pipeline


def _quiet(fn, *args, **kwargs):
    """Call fn while swallowing its stdout (the pipeline prints progress)."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class RunPipelineTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        today = pipeline.TODAY

        existing = {
            "schemaVersion": 2,
            "roles": [{
                "id": "acme-existing", "company": "Acme", "title": "Solutions Engineer",
                "url": "https://job-boards.greenhouse.io/acme/jobs/1",
                "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/1", "sourceUrl": "",
                "location": "Remote - US", "matchPercent": 84, "foundDate": today,
                "fullDescription": "existing role",
            }],
            "meta": {},
        }
        search = {"schemaVersion": 2, "searches": [],
                  "watchlist": [{"company": "Acme", "ats": "greenhouse", "slug": "acme"}]}
        data = write_data_dir(self._tmp.name, jobs=existing, search=search)
        pipeline.DATA = data

        self._payload = {"jobs": [
            {"id": 1, "title": "Solutions Engineer",  # DUP of existing (same url)
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Dup role.</p>"},
            {"id": 2, "title": "Account Executive, Enterprise",  # title skip
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
             "updated_at": today + "T10:00:00Z", "location": {"name": "New York, NY"},
             "content": "<p>Carry a quota, close deals.</p>"},
            {"id": 3, "title": "Senior Technical Program Manager",  # KEEP
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Drive cross-functional delivery.</p>"},
        ]}
        pipeline.http_get_json = lambda url, timeout=20: self._payload

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def test_run_adds_only_new_qualified_and_dedups(self):
        rc = _quiet(pipeline.run,dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        ids = [r["id"] for r in jobs["roles"]]
        # started with 1; only the TPM (job 3) should be added -> 2 total
        self.assertEqual(len(jobs["roles"]), 2)
        self.assertIn("acme-existing", ids)
        titles = [r["title"] for r in jobs["roles"]]
        self.assertIn("Senior Technical Program Manager", titles)
        self.assertNotIn("Account Executive, Enterprise", titles)  # title-skipped
        # the duplicate greenhouse job 1 did not create a second entry
        self.assertEqual(sum(1 for r in jobs["roles"] if r["url"].endswith("/jobs/1")), 1)

    def test_run_is_idempotent(self):
        _quiet(pipeline.run,dry_run=False, max_age_days=2)
        first = len(json.loads((pipeline.DATA / "jobs.json").read_text())["roles"])
        _quiet(pipeline.run,dry_run=False, max_age_days=2)
        second = len(json.loads((pipeline.DATA / "jobs.json").read_text())["roles"])
        self.assertEqual(first, second)  # nothing new the second time

    def test_dry_run_writes_nothing(self):
        before = (pipeline.DATA / "jobs.json").read_text()
        _quiet(pipeline.run,dry_run=True, max_age_days=2)
        self.assertEqual((pipeline.DATA / "jobs.json").read_text(), before)


class ReenrichTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_enrich = pipeline.enrich_from_ats
        self._tmp = tempfile.TemporaryDirectory()

        jobs = {"schemaVersion": 2, "roles": [{
            "id": "acme-tpm", "company": "Acme", "title": "Senior Technical Program Manager",
            "url": "https://job-boards.greenhouse.io/acme/jobs/9",
            "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/9", "sourceUrl": "",
            "location": "Remote - US", "matchPercent": 50, "foundDate": pipeline.TODAY,
            "fullDescription": "thin snippet",
            "skillMatch": {"matched": ["Python"], "gaps": [], "rationale": "stale",
                           "assessedBy": "sonnet", "assessedAt": "2026-01-01"},
        }], "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs)

        long_desc = "Drive cross-functional delivery across engineering teams. " * 20
        pipeline.enrich_from_ats = lambda url: {
            "title": "Senior Technical Program Manager", "location": "Remote - US",
            "url": url, "description": long_desc, "postedDate": pipeline.TODAY,
            "salaryMin": 180000, "salaryMax": 220000,
        }

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.enrich_from_ats = self._orig_enrich
        self._tmp.cleanup()

    def test_reenrich_updates_desc_and_clears_skillmatch(self):
        rc = _quiet(pipeline.reenrich,dry_run=False)
        self.assertEqual(rc, 0)
        role = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"][0]
        self.assertGreater(len(role["fullDescription"]), 300)
        self.assertEqual(role["salaryMin"], 180000)
        self.assertNotIn("skillMatch", role)            # cleared for re-assessment
        self.assertGreater(role["matchPercent"], 0)     # rescored

    def test_reenrich_dry_run_writes_nothing(self):
        before = (pipeline.DATA / "jobs.json").read_text()
        _quiet(pipeline.reenrich,dry_run=True)
        self.assertEqual((pipeline.DATA / "jobs.json").read_text(), before)


class ResolveAtsTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_fetchers = pipeline.ATS_FETCHERS
        self._tmp = tempfile.TemporaryDirectory()

        # A Cohere Ashby board with one matching TPM posting (+ an unrelated one).
        cohere_board = [
            {"title": "Technical Program Manager, North Delivery & Release Operations",
             "url": "https://jobs.ashbyhq.com/cohere/abc-123",
             "description": "Own release coordination across North. " * 30,
             "salaryMin": 150000, "salaryMax": 200000, "location": "Remote, US"},
            {"title": "Account Executive, Enterprise",
             "url": "https://jobs.ashbyhq.com/cohere/ae-999", "description": "Sales.",
             "salaryMin": None, "salaryMax": None, "location": "New York, NY"},
        ]
        pipeline.ATS_FETCHERS = {
            "ashby": lambda slug: cohere_board if slug == "cohere" else [],
            "greenhouse": lambda slug: [], "lever": lambda slug: [],
            "workable": lambda slug: [], "smartrecruiters": lambda slug: [],
        }

        jobs = {"schemaVersion": 2, "roles": [
            # source-only role that SHOULD resolve to the Ashby posting (note abbreviated title)
            {"id": "cohere-tpm", "company": "Cohere", "title": "TPM, North Delivery & Release Ops",
             "url": "https://www.linkedin.com/jobs/view/1", "sourceUrl": "https://www.linkedin.com/jobs/view/1",
             "atsUrl": "", "location": "New York, NY", "matchPercent": 80, "fullDescription": "thin"},
            # source-only role at Cohere with NO matching posting -> stays unresolved
            {"id": "cohere-cmo", "company": "Cohere", "title": "Chief Marketing Officer",
             "url": "https://www.linkedin.com/jobs/view/2", "sourceUrl": "https://www.linkedin.com/jobs/view/2",
             "atsUrl": "", "location": "Remote", "matchPercent": 55, "fullDescription": "thin"},
            # already has an ATS url -> must be left untouched
            {"id": "acme-tpm", "company": "Acme", "title": "Senior Technical Program Manager",
             "url": "https://job-boards.greenhouse.io/acme/jobs/9",
             "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/9", "sourceUrl": "",
             "location": "Remote - US", "matchPercent": 90, "fullDescription": "x" * 500},
        ], "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs)

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.ATS_FETCHERS = self._orig_fetchers
        self._tmp.cleanup()

    def _roles(self):
        return {r["id"]: r for r in json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]}

    def test_confident_match_attaches_apply_link(self):
        _quiet(pipeline.resolve_ats, dry_run=False)
        r = self._roles()["cohere-tpm"]
        self.assertEqual(r["atsUrl"], "https://jobs.ashbyhq.com/cohere/abc-123")
        self.assertEqual(r["atsResolveStatus"], "resolved")
        self.assertEqual(r["salaryMin"], 150000)            # backfilled
        self.assertGreater(len(r["fullDescription"]), 300)  # canonical JD pulled in

    def test_weak_match_does_not_attach(self):
        _quiet(pipeline.resolve_ats, dry_run=False)
        r = self._roles()["cohere-cmo"]
        self.assertEqual(r.get("atsUrl", ""), "")
        self.assertEqual(r["atsResolveStatus"], "unresolved")

    def test_already_resolved_is_untouched(self):
        before = self._roles()["acme-tpm"]
        _quiet(pipeline.resolve_ats, dry_run=False)
        after = self._roles()["acme-tpm"]
        self.assertEqual(after["atsUrl"], before["atsUrl"])
        self.assertNotIn("atsResolveStatus", after)  # never entered the pending set

    def test_dry_run_writes_nothing(self):
        before = (pipeline.DATA / "jobs.json").read_text()
        _quiet(pipeline.resolve_ats, dry_run=True)
        self.assertEqual((pipeline.DATA / "jobs.json").read_text(), before)


class AtsResolveHelperTests(unittest.TestCase):
    def test_slug_candidates(self):
        self.assertEqual(pipeline.slug_candidates("Grafana Labs"), ["grafanalabs", "grafana-labs", "grafana"])
        self.assertEqual(pipeline.slug_candidates("Cohere"), ["cohere"])

    def test_title_match_expands_abbreviations(self):
        s = pipeline.title_match_score("TPM, North Delivery & Release Ops",
                                       "Technical Program Manager, North Delivery & Release Operations")
        self.assertGreaterEqual(s, pipeline.TITLE_MATCH_THRESHOLD)

    def test_title_match_rejects_unrelated(self):
        s = pipeline.title_match_score("TPM, Product Engineering", "Account Executive, Enterprise")
        self.assertLess(s, pipeline.TITLE_MATCH_THRESHOLD)

    def test_best_title_match_returns_none_below_threshold(self):
        postings = [{"title": "Account Executive", "url": "x"}, {"title": "Sales Manager", "url": "y"}]
        best, _ = pipeline.best_title_match("Senior Technical Program Manager", postings)
        self.assertIsNone(best)


if __name__ == "__main__":
    unittest.main()
