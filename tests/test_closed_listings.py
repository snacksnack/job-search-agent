"""Closed-listing detection: diff live boards vs stored roles (RC1-273)."""
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline
import render


def _quiet_run(**kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return pipeline.run(**kwargs)


def _roles():
    return {r["id"]: r for r in json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]}


def _role(company, title, jid, *, url=None, ats=True, closed=False):
    url = url or f"https://job-boards.greenhouse.io/{company.lower()}/jobs/{jid}"
    r = {"id": f"{company.lower()}-{jid}", "company": company, "title": title,
         "url": url, "atsUrl": url if ats else "", "sourceUrl": "" if ats else url,
         "location": "Remote - US", "matchPercent": 80, "foundDate": "2026-08-01",
         "fullDescription": "existing role"}
    if closed:
        r["closed"] = True
        r["closedDate"] = "2026-08-10"
    return r


class ClosedListingTests(unittest.TestCase):
    """Boards: Acme fetches ok (job 3 live, job 9 gone), BadCo fetch FAILS,
    EmptyCo fetches ok but empty."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        today = pipeline.TODAY

        jobs = {"schemaVersion": 2, "roles": [
            _role("Acme", "Senior Technical Program Manager", 3),   # still live
            _role("Acme", "Solutions Engineer", 9),                 # gone from board
            _role("BadCo", "Forward Deployed Engineer", 5),         # fetch fails -> untouched
            _role("EmptyCo", "Technical Program Manager", 7),       # board empty -> closed
            _role("Acme", "Sales Engineer", 11, ats=False,          # source-only -> not diffable
                  url="https://www.linkedin.com/jobs/view/11"),
        ], "meta": {}}
        search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "Acme", "ats": "greenhouse", "slug": "acme"},
            {"company": "BadCo", "ats": "greenhouse", "slug": "badco"},
            {"company": "EmptyCo", "ats": "greenhouse", "slug": "emptyco"},
        ]}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs, search=search)

        payload = {"jobs": [
            {"id": 3, "title": "Senior Technical Program Manager",
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Still open.</p>"},
        ]}

        def fake_http(url, timeout=20):
            if "/acme/" in url:
                return payload
            if "/emptyco/" in url:
                return {"jobs": []}
            raise urllib.error.HTTPError(url, 500, "boom", None, io.BytesIO(b""))
        pipeline.http_get_json = fake_http

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def test_absent_role_closed_present_kept_failed_fetch_untouched(self):
        rc = _quiet_run(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        roles = _roles()

        self.assertNotIn("closed", roles["acme-3"])                  # still on the board
        self.assertTrue(roles["acme-9"]["closed"])                   # absent -> closed
        self.assertEqual(roles["acme-9"]["closedDate"], pipeline.TODAY)
        self.assertNotIn("closed", roles["badco-5"])                 # fetch failed -> guard held
        self.assertTrue(roles["emptyco-7"]["closed"])                # empty board fetched ok -> closed
        self.assertNotIn("closed", roles["acme-11"])                 # source-only -> not diffable

        log = json.loads((pipeline.DATA / "search-log.json").read_text())
        self.assertEqual(log["runs"][-1]["closedListings"],
                         {"companiesDiffed": 2, "closed": 2, "reopened": 0})

    def test_title_slug_match_survives_url_format_drift(self):
        # Stored role has the legacy boards.greenhouse.io url; live board serves
        # job-boards.greenhouse.io. The company+title slug keeps it open.
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        for r in jobs["roles"]:
            if r["id"] == "acme-3":
                r["url"] = r["atsUrl"] = "https://boards.greenhouse.io/acme/jobs/3"
        (pipeline.DATA / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")

        _quiet_run(dry_run=False, max_age_days=2)
        self.assertNotIn("closed", _roles()["acme-3"])

    def test_reopened_when_back_on_board(self):
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        for r in jobs["roles"]:
            if r["id"] == "acme-3":
                r["closed"] = True
                r["closedDate"] = "2026-08-10"
        (pipeline.DATA / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")

        _quiet_run(dry_run=False, max_age_days=2)
        roles = _roles()
        self.assertNotIn("closed", roles["acme-3"])
        self.assertNotIn("closedDate", roles["acme-3"])
        # ...and dedup kept it as one entry rather than re-adding the live posting
        self.assertEqual(sum(1 for rid in roles if rid.startswith("acme") and "jobs/3" in roles[rid]["url"]), 1)

    def test_dry_run_marks_nothing(self):
        before = (pipeline.DATA / "jobs.json").read_text()
        _quiet_run(dry_run=True, max_age_days=2)
        self.assertEqual((pipeline.DATA / "jobs.json").read_text(), before)


class ClosedMaintenanceSkipTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()
        jobs = {"schemaVersion": 2, "roles": [
            _role("Acme", "Solutions Engineer", 9, closed=True),
        ], "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs)

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def test_reenrich_skips_closed(self):
        called = []
        orig = pipeline.enrich_from_ats
        pipeline.enrich_from_ats = lambda url: called.append(url)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                pipeline.reenrich(dry_run=True)
        finally:
            pipeline.enrich_from_ats = orig
        self.assertEqual(called, [])


class ClosedRenderTests(unittest.TestCase):
    def test_board_and_table_mark_closed_and_exclude_from_active(self):
        jobs = {"roles": [
            _role("Acme", "Senior Technical Program Manager", 3),
            _role("Acme", "Solutions Engineer", 9, closed=True),
        ]}
        state = {"jobs": {}}
        board = render.render_html(jobs, state)
        self.assertIn('data-closed="1"', board)
        self.assertIn("closed-card", board)
        self.assertIn("closed-badge", board)
        self.assertIn(">1 closed</button>", board)
        # shown (active) count excludes the closed role
        self.assertIn('id="shownCount">1</span> shown', board)

        table = render.render_table_html(jobs, state)
        self.assertIn("row-closed", table)
        self.assertIn("closed-tag", table)
        self.assertIn(">1 closed</button>", table)


if __name__ == "__main__":
    unittest.main()
