"""foundDate is stamped from the system clock, never from the payload (RC1-311)."""
import contextlib
import datetime
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline

DESC = "Drive cross-functional delivery across engineering teams. " * 12
STALE = "2026-08-21"          # what a session started days ago believes today is


def _gh_job(jid, title, desc=DESC, location="Remote - US"):
    return {"id": jid, "title": title,
            "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{jid}",
            "updated_at": pipeline.TODAY + "T10:00:00Z",
            "location": {"name": location}, "content": f"<p>{desc}</p>"}


class NormalizeFoundDateTests(unittest.TestCase):
    def test_inbox_supplied_found_date_is_ignored(self):
        raw = {"title": "Senior Technical Program Manager", "company": "Acme",
               "url": "https://www.linkedin.com/jobs/view/4012345678",
               "foundDate": STALE, "postedDate": STALE}
        role = pipeline.normalize(raw, "linkedin")
        self.assertEqual(role["foundDate"], pipeline.TODAY)
        self.assertEqual(role["postedDate"], STALE)   # postedDate IS the payload's to set

    def test_today_tracks_the_system_clock(self):
        self.assertEqual(pipeline.TODAY, datetime.date.today().isoformat())


class FoundDateWarningTests(unittest.TestCase):
    def _role(self, **extra):
        r = {"company": "Acme", "title": "Senior TPM", "foundDate": pipeline.TODAY}
        r.update(extra)
        return r

    def test_clean_board_warns_about_nothing(self):
        roles = [self._role(), self._role(foundDate="2026-01-04")]
        self.assertEqual(pipeline.found_date_warnings(roles[:1], roles), [])

    def test_new_role_not_stamped_today_warns(self):
        new = [self._role(foundDate=STALE)]
        w = pipeline.found_date_warnings(new, new, today="2026-08-24")
        self.assertEqual(len(w), 1)
        self.assertIn("new role stamped foundDate='2026-08-21'", w[0])
        self.assertIn("clock says 2026-08-24", w[0])

    def test_future_dated_stored_role_warns(self):
        roles = [self._role(foundDate="2026-09-01")]
        w = pipeline.found_date_warnings([], roles, today="2026-08-24")
        self.assertEqual(len(w), 1)
        self.assertIn("ahead of the system clock (2026-08-24)", w[0])

    def test_unparseable_date_warns_without_raising(self):
        roles = [self._role(foundDate="yesterday"), self._role(foundDate=17)]
        w = pipeline.found_date_warnings([], roles, today="2026-08-24")
        self.assertEqual(len(w), 2)
        self.assertTrue(all("unparseable foundDate" in line for line in w))

    def test_missing_date_on_legacy_role_is_not_a_warning(self):
        roles = [self._role(foundDate=None), {"company": "Beta", "title": "SE"}]
        self.assertEqual(pipeline.found_date_warnings([], roles, today="2026-08-24"), [])

    def test_report_truncates_a_flood_but_returns_every_warning(self):
        ignored = [("Acme", f"Senior TPM {i}", STALE) for i in range(25)]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            w = pipeline.report_found_dates([], [], ignored)
        out = buf.getvalue()
        self.assertEqual(len(w), 25)                       # search-log keeps all of them
        self.assertEqual(out.count("  foundDate  ignored"), pipeline.DATE_WARNINGS_SHOWN)
        self.assertIn("and 15 more", out)

    def test_ignored_inbox_date_is_reported(self):
        w = pipeline.found_date_warnings(
            [], [], [("Acme", "Senior TPM", STALE)], today="2026-08-24")
        self.assertEqual(len(w), 1)
        self.assertIn("ignored inbox-supplied foundDate='2026-08-21'", w[0])
        self.assertIn("Acme — Senior TPM", w[0])


class RunIntegrationTests(unittest.TestCase):
    """The end-to-end shape: a back-dated inbox drop lands on today and is named."""

    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _run(self, inbox_items, stored_roles=()):
        search = {"schemaVersion": 2, "searches": [], "watchlist": []}
        pipeline.DATA = write_data_dir(
            self._tmp.name, search=search,
            jobs={"schemaVersion": 2, "roles": list(stored_roles), "meta": {}})
        inbox = pipeline.DATA / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / f"linkedin-{STALE}.json").write_text(json.dumps(inbox_items),
                                                      encoding="utf-8")
        pipeline.http_get_json = lambda url, timeout=20: {}
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = pipeline.run(dry_run=False, max_age_days=400)
        self.assertEqual(rc, 0)
        roles = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]
        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        return roles, log, buf.getvalue()

    def test_backdated_inbox_role_is_stamped_today_and_reported(self):
        roles, log, out = self._run([{
            "title": "Senior Technical Program Manager", "company": "Acme",
            "url": "https://www.linkedin.com/jobs/view/4012345678",
            "location": "Remote, US", "description": DESC,
            "foundDate": STALE, "postedDate": pipeline.TODAY,
        }])
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["foundDate"], pipeline.TODAY)
        self.assertIn("Date check: 1 foundDate warning(s)", out)
        self.assertIn("ignored inbox-supplied foundDate", out)
        self.assertEqual(len(log["foundDateWarnings"]), 1)

    def test_clean_inbox_drop_prints_no_date_check(self):
        roles, log, out = self._run([{
            "title": "Senior Technical Program Manager", "company": "Acme",
            "url": "https://www.linkedin.com/jobs/view/4012345678",
            "location": "Remote, US", "description": DESC,
            "postedDate": pipeline.TODAY,
        }])
        self.assertEqual(roles[0]["foundDate"], pipeline.TODAY)
        self.assertNotIn("Date check:", out)
        self.assertNotIn("foundDateWarnings", log)

    def test_hand_edited_future_date_on_a_stored_role_surfaces_next_run(self):
        future = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        stored = [{"id": "beta-1", "company": "Beta", "title": "Solutions Engineer",
                   "url": "https://beta.example/jobs/1", "matchPercent": 80,
                   "foundDate": future, "fullDescription": DESC}]
        _, log, out = self._run([], stored_roles=stored)
        self.assertIn("ahead of the system clock", out)
        self.assertEqual(len(log["foundDateWarnings"]), 1)


if __name__ == "__main__":
    unittest.main()
