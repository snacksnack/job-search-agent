"""Content-hash change detection for re-seen postings (RC1-278)."""
import contextlib
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline

OLD_DESC = "Drive cross-functional delivery across engineering teams. " * 12
NEW_DESC = ("Drive cross-functional delivery across engineering teams and own the "
            "platform roadmap. Salary transparency added. " * 12)


def _gh_job(jid, title, desc, location="Remote - US"):
    return {"id": jid, "title": title,
            "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{jid}",
            "updated_at": pipeline.TODAY + "T10:00:00Z",
            "location": {"name": location}, "content": f"<p>{desc}</p>"}


def _stored(jid, title, desc, **extra):
    r = {"id": f"acme-{jid}", "company": "Acme", "title": title,
         "url": f"https://job-boards.greenhouse.io/acme/jobs/{jid}",
         "atsUrl": f"https://job-boards.greenhouse.io/acme/jobs/{jid}", "sourceUrl": "",
         "location": "Remote - US", "matchPercent": 80, "foundDate": "2026-08-01",
         "fullDescription": desc,
         "skillMatch": {"matched": ["Python", "AWS"], "gaps": [], "rationale": "cached",
                        "assessedBy": "sonnet", "assessedAt": "2026-08-01"}}
    r.update(extra)
    return r


class ChangeDetectionTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        self.search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "Acme", "ats": "greenhouse", "slug": "acme"}]}

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _setup(self, stored_roles, live_jobs, state=None):
        jobs = {"schemaVersion": 2, "roles": stored_roles, "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs, search=self.search,
                                       state=state)
        pipeline.http_get_json = lambda url, timeout=20: {"jobs": live_jobs}

    def _run(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = pipeline.run(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        roles = {r["id"]: r for r in json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]}
        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        return roles, log, buf.getvalue()

    def test_changed_jd_updates_clears_skillmatch_and_rescores(self):
        self._setup([_stored(3, "Senior Technical Program Manager", OLD_DESC)],
                    [_gh_job(3, "Senior Technical Program Manager", NEW_DESC)])
        roles, log, out = self._run()
        r = roles["acme-3"]
        self.assertIn("Salary transparency added.", r["fullDescription"])
        self.assertNotIn("skillMatch", r)                      # cleared for re-assessment
        self.assertEqual(r["changedDate"], pipeline.TODAY)
        self.assertEqual(r["contentHash"], pipeline.role_content_hash(r))
        self.assertEqual(log["changedRoles"]["active"],
                         ["Acme — Senior Technical Program Manager"])
        self.assertEqual(log["changedRoles"]["reassessing"], 1)
        self.assertIn("Change detection: 1 re-seen role(s) updated (1 re-assessing)", out)
        self.assertEqual(len(roles), 1)                        # updated, not duplicated

    def test_unchanged_reseen_role_untouched(self):
        self._setup([_stored(3, "Senior Technical Program Manager", OLD_DESC)],
                    [_gh_job(3, "Senior Technical Program Manager", OLD_DESC)])
        roles, log, _ = self._run()
        r = roles["acme-3"]
        self.assertIn("skillMatch", r)
        self.assertNotIn("changedDate", r)
        self.assertNotIn("changedRoles", log)
        self.assertEqual(r["contentHash"], pipeline.role_content_hash(r))  # backfilled

    def test_list_only_empty_desc_does_not_wipe_jd(self):
        # SmartRecruiters/Gem sweeps carry no JD; an empty incoming description must
        # not count as a change or clear the cached assessment.
        stored = _stored(3, "Senior Technical Program Manager", OLD_DESC)
        self._setup([stored], [_gh_job(3, "Senior Technical Program Manager", "")])
        roles, log, _ = self._run()
        r = roles["acme-3"]
        self.assertEqual(r["fullDescription"], OLD_DESC)
        self.assertIn("skillMatch", r)
        self.assertNotIn("changedRoles", log)

    def test_much_shorter_desc_treated_as_partial_fetch(self):
        self._setup([_stored(3, "Senior Technical Program Manager", OLD_DESC)],
                    [_gh_job(3, "Senior Technical Program Manager", "Short snippet.")])
        roles, log, _ = self._run()
        r = roles["acme-3"]
        self.assertEqual(r["fullDescription"], OLD_DESC)       # rich JD kept
        self.assertIn("skillMatch", r)

    def test_salary_change_updates_without_reassessment(self):
        stored = _stored(3, "Senior Technical Program Manager", OLD_DESC, salaryMax=None)
        live = _gh_job(3, "Senior Technical Program Manager", OLD_DESC)
        self._setup([stored], [live])
        # greenhouse fetcher yields salary None; simulate a location change instead
        live["location"] = {"name": "New York, NY (Remote)"}
        roles, log, _ = self._run()
        r = roles["acme-3"]
        self.assertEqual(r["location"], "New York, NY (Remote)")
        self.assertIn("skillMatch", r)                         # desc unchanged -> kept
        self.assertEqual(r["changedDate"], pipeline.TODAY)
        self.assertEqual(log["changedRoles"]["reassessing"], 0)

    def test_decided_role_updates_data_but_is_not_resurfaced(self):
        state = {"schemaVersion": 1, "jobs": {"acme-3": {"status": "applied",
                                                        "appliedDate": "2026-08-05"}}}
        self._setup([_stored(3, "Senior Technical Program Manager", OLD_DESC)],
                    [_gh_job(3, "Senior Technical Program Manager", NEW_DESC)], state=state)
        roles, log, out = self._run()
        r = roles["acme-3"]
        self.assertIn("Salary transparency added.", r["fullDescription"])  # data updated
        self.assertIn("skillMatch", r)                         # no re-assessment churn
        self.assertEqual(log["changedRoles"]["decided"],
                         ["Acme — Senior Technical Program Manager"])
        self.assertEqual(log["changedRoles"]["active"], [])
        self.assertIn("changed (decided)", out)

    def test_new_roles_get_content_hash(self):
        self._setup([], [_gh_job(3, "Senior Technical Program Manager", OLD_DESC)])
        roles, _, _ = self._run()
        r = roles["acme-senior-technical-program-manager"]
        self.assertEqual(r["contentHash"], pipeline.role_content_hash(r))


if __name__ == "__main__":
    unittest.main()
