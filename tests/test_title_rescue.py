"""Title filter widening + LLM title-rescue pass (RC1-277)."""
import contextlib
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import make_profile, write_data_dir
import pipeline
import title_rescue


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


class TitleDecisionWideningTests(unittest.TestCase):
    def setUp(self):
        self.profile = make_profile()
        m = self.profile["matching"]
        m["skipTitleRules"].append(
            {"category": "Sales (non-technical)", "titles": ["Account Manager"]})
        m["secondaryIncludeTitles"]["titles"] += [
            "Technical Account Manager", "Engagement Manager", "Delivery Lead"]

    def test_singular_solution_engineer_accepted(self):
        ok, _ = pipeline.title_decision("Senior Solution Engineer", self.profile)
        self.assertTrue(ok)          # singular form is not a substring of "Solutions Engineer"
        ok, _ = pipeline.title_decision("Solution Architect, Platform", self.profile)
        self.assertTrue(ok)

    def test_secondary_include_beats_category_skip(self):
        # "Technical Account Manager" contains the skip substring "Account Manager";
        # the explicit secondary include must win.
        ok, _ = pipeline.title_decision("Senior Technical Account Manager", self.profile)
        self.assertTrue(ok)
        # ...but a plain Account Manager still dies on the skip rule.
        ok, reason = pipeline.title_decision("Account Manager, Mid-Market", self.profile)
        self.assertFalse(ok)
        self.assertIn("Sales", reason)

    def test_adjacent_families_rank_below_primary(self):
        tam = {"title": "Technical Account Manager", "fullDescription": "x"}
        tpm = {"title": "Senior Technical Program Manager", "fullDescription": "x"}
        tam_pct, _ = pipeline.score(tam, self.profile)
        tpm_pct, _ = pipeline.score(tpm, self.profile)
        self.assertLess(tam_pct, tpm_pct)


class RescueQueueTests(unittest.TestCase):
    """run() saves fresh title-rejects; title_rescue applies verdicts."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        today = pipeline.TODAY
        search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "Acme", "ats": "greenhouse", "slug": "acme"}]}
        pipeline.DATA = write_data_dir(self._tmp.name, search=search)
        title_rescue.DATA = pipeline.DATA
        title_rescue.QUEUE_PATH = pipeline.DATA / "queue" / "title-rescue.json"
        title_rescue.JOBS_PATH = pipeline.DATA / "jobs.json"

        payload = {"jobs": [
            {"id": 1, "title": "PgM III, Infrastructure",             # nonstandard -> rescueable
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Drive infra programs end to end.</p>"},
            {"id": 2, "title": "Copywriter",                          # rejected, stays rejected
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Write copy.</p>"},
            {"id": 3, "title": "Senior Technical Program Manager",    # passes normally
             "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "updated_at": today + "T10:00:00Z", "location": {"name": "Remote - US"},
             "content": "<p>Drive delivery.</p>"},
        ]}
        pipeline.http_get_json = lambda url, timeout=20: payload

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _queue(self):
        return json.loads((pipeline.DATA / "queue" / "title-rescue.json").read_text())

    def test_pipeline_writes_title_rejects_to_queue(self):
        rc = _quiet(pipeline.run, dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        q = self._queue()
        titles = {r["title"] for r in q["roles"]}
        self.assertEqual(titles, {"PgM III, Infrastructure", "Copywriter"})
        self.assertEqual(q["date"], pipeline.TODAY)
        # the passing role went to jobs.json, not the queue
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        self.assertEqual([r["title"] for r in jobs["roles"]],
                         ["Senior Technical Program Manager"])

    def test_apply_rescues_approved_titles_only(self):
        _quiet(pipeline.run, dry_run=False, max_age_days=2)
        verdict = pipeline.DATA / "verdict.json"
        verdict.write_text(json.dumps({"approved": ["pgm iii, infrastructure"]}))
        rescued, filtered, dup = _quiet(title_rescue.apply_verdicts, verdict)

        self.assertEqual([r["title"] for r in rescued], ["PgM III, Infrastructure"])
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        by_title = {r["title"]: r for r in jobs["roles"]}
        self.assertIn("PgM III, Infrastructure", by_title)
        r = by_title["PgM III, Infrastructure"]
        self.assertTrue(r["titleRescued"])
        self.assertIn("double-check role scope", r["rationale"])
        self.assertNotIn("Copywriter", by_title)              # unapproved stays out
        self.assertEqual(self._queue()["roles"], [])          # queue cleared after verdicts

    def test_apply_is_idempotent_via_dedup(self):
        _quiet(pipeline.run, dry_run=False, max_age_days=2)
        verdict = pipeline.DATA / "verdict.json"
        verdict.write_text(json.dumps({"approved": ["PgM III, Infrastructure"]}))
        _quiet(title_rescue.apply_verdicts, verdict)
        # re-run pipeline: role is now in jobs.json, so it dedups instead of re-queueing;
        # even if re-applied, dedup keeps one copy
        _quiet(pipeline.run, dry_run=False, max_age_days=2)
        _quiet(title_rescue.apply_verdicts, verdict)
        jobs = json.loads((pipeline.DATA / "jobs.json").read_text())
        self.assertEqual(sum(1 for r in jobs["roles"]
                             if r["title"] == "PgM III, Infrastructure"), 1)

    def test_list_pending_dedupes_titles(self):
        _quiet(pipeline.run, dry_run=False, max_age_days=2)
        rows = title_rescue.list_pending()
        self.assertEqual({r["title"] for r in rows}, {"PgM III, Infrastructure", "Copywriter"})
        self.assertEqual(rows[0]["companies"], ["Acme"])

    def test_dry_run_writes_no_queue(self):
        _quiet(pipeline.run, dry_run=True, max_age_days=2)
        self.assertFalse((pipeline.DATA / "queue" / "title-rescue.json").exists())


class RescuedBadgeRenderTests(unittest.TestCase):
    def test_board_and_table_show_rescued_badge(self):
        import render
        jobs = {"roles": [{
            "id": "acme-pgm", "company": "Acme", "title": "PgM III", "url": "http://x",
            "matchPercent": 70, "titleRescued": True, "rationale": "r",
        }]}
        board = render.render_html(jobs, {"jobs": {}})
        self.assertIn("rescued-badge", board)
        table = render.render_table_html(jobs, {"jobs": {}})
        self.assertIn("rescued-tag", table)


if __name__ == "__main__":
    unittest.main()
