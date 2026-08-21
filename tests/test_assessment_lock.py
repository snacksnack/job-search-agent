"""Human/LLM skill-match assessments survive a JD change (RC1-297)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import make_profile, write_data_dir
import pipeline
import skill_match

OLD_DESC = "Drive cross-functional delivery across engineering teams. " * 12
# Deliberately neutral rewording: it carries no new domain or seniority signal, so
# every part of the score except the assessed fit is expected to hold still.
NEW_DESC = ("Drive cross-functional delivery across engineering teams and coordinate "
            "the launch calendar. Compensation range published. " * 12)

# A real assessment that found little: 1 match against 8 gaps, so the assessed fit
# sits far below the neutral baseline an unassessed role gets. Deleting it is what
# made scores jump.
POOR_FIT = {"matched": ["Python"],
            "gaps": ["Go", "Rust", "Kubernetes", "Terraform", "Kafka", "Spark", "gRPC", "C++"],
            "rationale": "Thin overlap with the stack this team runs.",
            "assessedBy": "opus-skillmatch-2026-08-19", "assessedAt": "2026-08-19"}


class AssessmentProvenanceTests(unittest.TestCase):
    def test_stamped_assessments_are_real(self):
        for sm in ({"assessedBy": "sonnet"}, {"model": "recovered-from-board"},
                   {"assessmentLocked": True}, POOR_FIT):
            self.assertTrue(pipeline.is_real_assessment(sm), sm)

    def test_unstamped_or_missing_is_not(self):
        for sm in ({"matched": ["Python"], "gaps": []}, {}, None, "sonnet"):
            self.assertFalse(pipeline.is_real_assessment(sm), sm)

    def test_flag_keeps_a_real_assessment(self):
        role = {"skillMatch": dict(POOR_FIT)}
        self.assertEqual(pipeline.flag_stale_assessment(role), "locked")
        self.assertEqual(role["skillMatch"], POOR_FIT)
        self.assertTrue(role["reassessSuggested"])

    def test_flag_drops_an_unstamped_one(self):
        role = {"skillMatch": {"matched": ["Python"], "gaps": []}}
        self.assertEqual(pipeline.flag_stale_assessment(role), "cleared")
        self.assertNotIn("skillMatch", role)
        self.assertNotIn("reassessSuggested", role)

    def test_flag_is_a_no_op_without_a_cached_match(self):
        role = {"id": "a"}
        self.assertEqual(pipeline.flag_stale_assessment(role), "")
        self.assertNotIn("reassessSuggested", role)


class IngestAssessmentLockTests(unittest.TestCase):
    """The re-seen path in pipeline.run(): a changed JD must not cost an assessment."""

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

    def _stored(self, desc, **extra):
        r = {"id": "acme-3", "company": "Acme", "title": "Senior Technical Program Manager",
             "url": "https://job-boards.greenhouse.io/acme/jobs/3",
             "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/3", "sourceUrl": "",
             "location": "Remote - US", "foundDate": "2026-08-01", "fullDescription": desc,
             "skillMatch": dict(POOR_FIT)}
        r["matchPercent"] = pipeline.score(r, make_profile())[0]
        r.update(extra)
        return r

    def _run(self, stored, desc, state=None):
        jobs = {"schemaVersion": 2, "roles": [stored], "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs, search=self.search, state=state)
        pipeline.http_get_json = lambda url, timeout=20: {"jobs": [{
            "id": 3, "title": "Senior Technical Program Manager",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/3",
            "updated_at": pipeline.TODAY + "T10:00:00Z",
            "location": {"name": "Remote - US"}, "content": f"<p>{desc}</p>"}]}
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(pipeline.run(dry_run=False, max_age_days=2), 0)
        roles = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]
        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        return roles[0], log, buf.getvalue()

    def test_changed_jd_keeps_the_assessment_and_its_score(self):
        stored = self._stored(OLD_DESC)
        before = stored["matchPercent"]
        r, log, _ = self._run(stored, NEW_DESC)
        self.assertIn("Compensation range published.", r["fullDescription"])  # JD still refreshed
        self.assertEqual(r["skillMatch"], POOR_FIT)                       # assessment intact
        self.assertTrue(r["reassessSuggested"])
        self.assertEqual(r["matchPercent"], before)                       # no heuristic regression
        self.assertEqual(log["changedRoles"]["reassessing"], 1)

    def test_wiping_the_assessment_would_have_inflated_the_score(self):
        # Guards the point of the ticket rather than the mechanism: this is the jump
        # the old `ex.pop("skillMatch")` produced on every JD change.
        r, _, _ = self._run(self._stored(OLD_DESC), NEW_DESC)
        unassessed = {k: v for k, v in r.items() if k != "skillMatch"}
        heuristic = pipeline.score(unassessed, make_profile())[0]
        self.assertGreater(heuristic - r["matchPercent"], 15)

    def test_unstamped_cached_match_is_still_dropped(self):
        stored = self._stored(OLD_DESC, skillMatch={"matched": ["Python"], "gaps": []})
        r, log, _ = self._run(stored, NEW_DESC)
        self.assertNotIn("skillMatch", r)
        self.assertNotIn("reassessSuggested", r)
        self.assertEqual(log["changedRoles"]["reassessing"], 1)

    def test_unchanged_jd_does_not_flag_anything(self):
        r, log, _ = self._run(self._stored(OLD_DESC), OLD_DESC)
        self.assertEqual(r["skillMatch"], POOR_FIT)
        self.assertNotIn("reassessSuggested", r)
        self.assertNotIn("changedRoles", log)

    def test_decided_role_is_untouched_as_before(self):
        state = {"schemaVersion": 1, "jobs": {"acme-3": {"status": "applied"}}}
        r, log, _ = self._run(self._stored(OLD_DESC), NEW_DESC, state=state)
        self.assertEqual(r["skillMatch"], POOR_FIT)
        self.assertNotIn("reassessSuggested", r)      # no re-assessment churn on decided roles
        self.assertEqual(log["changedRoles"]["decided"],
                         ["Acme — Senior Technical Program Manager"])


class ReassessQueueTests(unittest.TestCase):
    """A flagged role has to be re-offered for assessment, or the flag means nothing."""

    def setUp(self):
        self._orig_data, self._orig_jobs = skill_match.DATA, skill_match.JOBS_PATH
        self._tmp = tempfile.TemporaryDirectory()
        base = {"company": "Acme", "title": "Solutions Engineer", "location": "Remote - US",
                "fullDescription": "desc", "matchPercent": 80}
        roles = [
            {"id": "fresh", **base},                                   # never assessed
            {"id": "settled", **base, "skillMatch": dict(POOR_FIT)},   # assessed, JD unchanged
            {"id": "stale", **base, "skillMatch": dict(POOR_FIT),      # assessed, JD moved
             "reassessSuggested": True},
        ]
        data = write_data_dir(self._tmp.name, jobs={"schemaVersion": 2, "roles": roles, "meta": {}})
        skill_match.DATA, skill_match.JOBS_PATH = data, data / "jobs.json"

    def tearDown(self):
        skill_match.DATA, skill_match.JOBS_PATH = self._orig_data, self._orig_jobs
        self._tmp.cleanup()

    def test_flagged_roles_are_pending_again(self):
        self.assertEqual({r["id"] for r in skill_match.list_pending()}, {"fresh", "stale"})

    def test_reassessment_clears_the_flag(self):
        f = Path(self._tmp.name) / "asmt.json"
        f.write_text(json.dumps([{"id": "stale", "matched": ["Python", "AWS"], "gaps": [],
                                  "rationale": "reassessed on the fuller JD"}]))
        applied, unknown = skill_match.apply_assessments(f)
        self.assertEqual((applied, unknown), (1, []))
        role = next(r for r in json.loads(skill_match.JOBS_PATH.read_text())["roles"]
                    if r["id"] == "stale")
        self.assertNotIn("reassessSuggested", role)
        self.assertEqual(role["skillMatch"]["matched"], ["Python", "AWS"])
        self.assertEqual({r["id"] for r in skill_match.list_pending()}, {"fresh"})


if __name__ == "__main__":
    unittest.main()
