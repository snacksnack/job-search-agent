"""Per-posting rejection logging (RC1-294).

The skip breakdown in search-log.json counts rejections by bucket; these tests
cover the JSONL log that says *which* postings were rejected and which rule fired.
"""
import contextlib
import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import make_profile, write_data_dir
import pipeline


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _role(**over):
    r = {"id": "acme-ae", "company": "Acme", "title": "Account Executive",
         "url": "https://example.com/1", "source": "greenhouse:acme",
         "postedDate": pipeline.TODAY}
    r.update(over)
    return r


class RejectRecordTests(unittest.TestCase):
    def test_splits_reason_into_bucket_and_detail(self):
        rec = pipeline.reject_record(_role(), "titleMismatch: Sales (non-technical)", "2026-08-18T07:00:00")
        self.assertEqual(rec["reason"], "titleMismatch")          # what the breakdown counts
        self.assertEqual(rec["detail"], "Sales (non-technical)")  # what the breakdown drops
        self.assertEqual(rec["run"], "2026-08-18T07:00:00")
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(rec["url"], "https://example.com/1")

    def test_reason_without_detail_records_none(self):
        rec = pipeline.reject_record(_role(), "skipEmployer", "2026-08-18T07:00:00")
        self.assertEqual(rec["reason"], "skipEmployer")
        self.assertIsNone(rec["detail"])

    def test_salary_reject_keeps_the_threshold_that_fired(self):
        profile = make_profile()                       # salaryTarget 150000
        role = _role(salaryMin=100000, salaryMax=120000)
        ok, reason = pipeline.salary_ok(role, profile)
        self.assertFalse(ok)
        rec = pipeline.reject_record(role, reason, "run")
        self.assertEqual(rec["reason"], "salaryTooLow")
        self.assertEqual(rec["detail"], "max 120000 < target 150000")


class WriteRejectsLogTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()
        pipeline.DATA = Path(self._tmp.name) / "data"

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def _path(self):
        return pipeline.DATA / "logs" / f"rejects-{pipeline.TODAY}.jsonl"

    def test_second_run_same_day_appends_rather_than_clobbers(self):
        _quiet(pipeline.write_rejects_log, [pipeline.reject_record(_role(), "skipEmployer", "run-1")])
        _quiet(pipeline.write_rejects_log, [pipeline.reject_record(_role(), "skipEmployer", "run-2")])
        lines = [json.loads(x) for x in self._path().read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual([x["run"] for x in lines], ["run-1", "run-2"])

    def test_empty_rejects_writes_no_file(self):
        _quiet(pipeline.write_rejects_log, [])
        self.assertFalse(self._path().exists())

    def test_prunes_to_the_retention_window(self):
        logs = pipeline.DATA / "logs"
        logs.mkdir(parents=True)
        today = datetime.date.fromisoformat(pipeline.TODAY)
        stale = [today - datetime.timedelta(days=n) for n in range(1, 6)]
        for d in stale:
            (logs / f"rejects-{d.isoformat()}.jsonl").write_text("{}\n")
        _quiet(pipeline.write_rejects_log,
               [pipeline.reject_record(_role(), "skipEmployer", "run")], keep_days=3)
        kept = sorted(p.name for p in logs.glob("rejects-*.jsonl"))
        self.assertEqual(len(kept), 3)
        self.assertIn(f"rejects-{pipeline.TODAY}.jsonl", kept)   # today's is never pruned
        self.assertNotIn(f"rejects-{stale[-1].isoformat()}.jsonl", kept)  # oldest goes first

    def test_unwritable_log_does_not_raise(self):
        (pipeline.DATA).mkdir(parents=True)
        (pipeline.DATA / "logs").write_text("not a directory")   # mkdir will fail
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pipeline.write_rejects_log([pipeline.reject_record(_role(), "skipEmployer", "run")])
        self.assertIn("rejects-log warning", out.getvalue())


class RunRejectsLogTests(unittest.TestCase):
    """The log has to reconcile against the counters it explains."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        today = pipeline.TODAY
        old = (datetime.date.fromisoformat(today) - datetime.timedelta(days=30)).isoformat()

        search = {"schemaVersion": 2, "searches": [],
                  "watchlist": [{"company": "Acme", "ats": "greenhouse", "slug": "acme"}]}
        pipeline.DATA = write_data_dir(self._tmp.name, search=search)

        self._payload = {"jobs": [
            {"id": 1, "title": "Senior Technical Program Manager",   # KEEP
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Drive cross-functional delivery.</p>"},
            {"id": 2, "title": "Account Executive, Enterprise",      # titleMismatch
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
             "updated_at": today + "T10:00:00Z", "location": {"name": "New York, NY"},
             "content": "<p>Close deals.</p>"},
            {"id": 3, "title": "Solutions Engineer",                 # locationHybrid
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Hybrid - Austin, TX"},
             "content": "<p>Pre-sales technical work.</p>"},
            {"id": 4, "title": "Forward Deployed Engineer",          # expired
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/4",
             "updated_at": old + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Deploy with customers.</p>"},
        ]}
        pipeline.http_get_json = lambda url, timeout=20: self._payload

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _lines(self):
        path = pipeline.DATA / "logs" / f"rejects-{pipeline.TODAY}.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()]

    def test_every_reject_is_logged_with_its_rule(self):
        _quiet(pipeline.run, dry_run=False, max_age_days=1)
        by_title = {x["title"]: x for x in self._lines()}
        self.assertNotIn("Senior Technical Program Manager", by_title)   # qualified, not a reject
        self.assertEqual(by_title["Account Executive, Enterprise"]["reason"], "titleMismatch")
        self.assertEqual(by_title["Account Executive, Enterprise"]["detail"], "Sales (non-technical)")
        self.assertEqual(by_title["Solutions Engineer"]["reason"], "locationHybrid")
        expired = by_title["Forward Deployed Engineer"]
        self.assertEqual(expired["reason"], "expired")
        self.assertIn("cutoff", expired["detail"])                      # both dates recorded
        self.assertTrue(all(x["url"] for x in self._lines()))           # every line is actionable

    def test_log_reconciles_with_the_skip_breakdown(self):
        _quiet(pipeline.run, dry_run=False, max_age_days=1)
        skipped = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]["counts"]["skipped"]
        tally = {}
        for x in self._lines():
            tally[x["reason"]] = tally.get(x["reason"], 0) + 1
        self.assertEqual(tally, skipped)

    def test_dry_run_writes_no_rejects_log(self):
        _quiet(pipeline.run, dry_run=True, max_age_days=1)
        self.assertFalse((pipeline.DATA / "logs" / f"rejects-{pipeline.TODAY}.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
