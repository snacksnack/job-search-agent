"""Per-source fetch health: ok / empty / error outcomes, rollup, failure streaks."""
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline


def _run_capturing(**kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pipeline.run(**kwargs)
    return rc, buf.getvalue()


def _watch_sources(data_dir):
    log = json.loads((data_dir / "search-log.json").read_text())
    run_entry = log["runs"][-1]
    return run_entry, {s["watchlist"]: s for s in run_entry["sources"] if "watchlist" in s}


class SourceHealthSweepTests(unittest.TestCase):
    """One run over three boards: postings, empty, and a hard HTTP failure."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        today = pipeline.TODAY

        search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "Acme", "ats": "greenhouse", "slug": "acme"},
            {"company": "EmptyCo", "ats": "greenhouse", "slug": "emptyco"},
            {"company": "BadCo", "ats": "greenhouse", "slug": "badco"},
        ]}
        pipeline.DATA = write_data_dir(self._tmp.name, search=search)

        payload = {"jobs": [
            {"id": 3, "title": "Senior Technical Program Manager",
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Drive cross-functional delivery.</p>"},
        ]}

        def fake_http(url, timeout=20):
            if "/acme/" in url:
                return payload
            if "/emptyco/" in url:
                return {"jobs": []}
            raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b""))
        pipeline.http_get_json = fake_http

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def test_three_outcomes_recorded_and_rolled_up(self):
        rc, out = _run_capturing(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        run_entry, by_company = _watch_sources(pipeline.DATA)

        self.assertEqual(by_company["Acme"]["status"], "ok")
        self.assertEqual(by_company["Acme"]["postings"], 1)
        self.assertEqual(by_company["EmptyCo"]["status"], "empty")
        self.assertEqual(by_company["EmptyCo"]["postings"], 0)
        self.assertEqual(by_company["BadCo"]["status"], "error")
        self.assertEqual(by_company["BadCo"]["error"], "HTTP 404")
        self.assertEqual(by_company["BadCo"]["failStreak"], 1)

        self.assertEqual(run_entry["sourceHealth"], {"ok": 1, "empty": 1, "failed": 1})
        self.assertIn("Source health: 1 ok, 1 empty, 1 failed", out)
        self.assertIn("FETCH FAILED  BadCo (greenhouse/badco): HTTP 404", out)
        self.assertIn("EMPTY         EmptyCo", out)
        # one failure is not yet a streak worth nagging about
        self.assertNotIn("runs in a row", out)

    def test_streak_reaches_threshold_and_suggests_reresolution(self):
        prior_fail = {"watchlist": "BadCo", "ats": "greenhouse", "slug": "badco",
                      "status": "error", "error": "HTTP 404"}
        log = {"schemaVersion": 1, "runs": [
            {"date": "2026-08-15", "sources": [dict(prior_fail)], "counts": {}},
            {"date": "2026-08-16", "sources": [dict(prior_fail)], "counts": {}},
        ]}
        (pipeline.DATA / "search-log.json").write_text(json.dumps(log), encoding="utf-8")

        rc, out = _run_capturing(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        _, by_company = _watch_sources(pipeline.DATA)
        self.assertEqual(by_company["BadCo"]["failStreak"], 3)
        self.assertIn("3 runs in a row", out)
        self.assertIn("--resolve-ats", out)


class FailureStreakTests(unittest.TestCase):
    def test_streak_counts_back_from_most_recent_pipeline_run(self):
        fail = {"watchlist": "BadCo", "status": "error", "error": "HTTP 404"}
        ok = {"watchlist": "BadCo", "status": "ok", "postings": 5}
        runs = [
            {"date": "d1", "sources": [dict(fail)]},   # broken by the later success
            {"date": "d2", "sources": [dict(ok)]},
            {"date": "d3", "sources": [dict(fail)]},
            {"date": "d4", "sources": [dict(fail)]},
        ]
        self.assertEqual(pipeline._failure_streaks(runs), {"BadCo": 2})

    def test_legacy_error_strings_and_skill_entries_handled(self):
        runs = [
            # skill-written entry: no watchlist sources -> ignored, streak not broken
            {"date": "d1", "totalNewRolesAdded": 2, "searches": []},
            # pre-2026-08 pipeline format: status is an "error: ..." string
            {"date": "d2", "sources": [{"watchlist": "BadCo", "ats": "lever",
                                        "status": "error: <urlopen error timed out>"}]},
        ]
        self.assertEqual(pipeline._failure_streaks(runs), {"BadCo": 1})

    def test_never_failed_company_has_no_streak(self):
        runs = [{"date": "d1", "sources": [{"watchlist": "Acme", "status": "ok"}]}]
        self.assertEqual(pipeline._failure_streaks(runs), {})


if __name__ == "__main__":
    unittest.main()
