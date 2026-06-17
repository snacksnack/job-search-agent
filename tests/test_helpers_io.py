"""I/O round-trips for skill_match.py and web_enrich.py (no LLM/browser involved)."""
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import skill_match
import web_enrich


def _role(rid, **kw):
    base = {
        "id": rid, "company": "Acme", "title": "Solutions Engineer",
        "url": "https://job-boards.greenhouse.io/acme/jobs/" + rid,
        "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/" + rid, "sourceUrl": "",
        "location": "Remote - US", "matchPercent": 80, "fullDescription": "desc",
    }
    base.update(kw)
    return base


class SkillMatchIoTests(unittest.TestCase):
    def setUp(self):
        self._orig_data, self._orig_jobs = skill_match.DATA, skill_match.JOBS_PATH
        self._tmp = tempfile.TemporaryDirectory()
        jobs = {"schemaVersion": 2, "roles": [_role("a"), _role("b")], "meta": {}}
        data = write_data_dir(self._tmp.name, jobs=jobs)
        skill_match.DATA, skill_match.JOBS_PATH = data, data / "jobs.json"

    def tearDown(self):
        skill_match.DATA, skill_match.JOBS_PATH = self._orig_data, self._orig_jobs
        self._tmp.cleanup()

    def test_list_pending_returns_unassessed(self):
        rows = skill_match.list_pending()
        self.assertEqual({r["id"] for r in rows}, {"a", "b"})

    def test_apply_then_pending_shrinks(self):
        f = Path(self._tmp.name) / "asmt.json"
        f.write_text(json.dumps([{"id": "a", "matched": ["Python"], "gaps": ["Go"],
                                  "rationale": "ok"}]))
        applied, unknown = skill_match.apply_assessments(str(f))
        self.assertEqual(applied, 1)
        self.assertEqual(unknown, [])
        role = next(r for r in json.loads((skill_match.JOBS_PATH).read_text())["roles"] if r["id"] == "a")
        self.assertEqual(role["skillMatch"]["matched"], ["Python"])
        self.assertEqual(role["skillMatch"]["assessedBy"], "sonnet")
        self.assertEqual({r["id"] for r in skill_match.list_pending()}, {"b"})

    def test_apply_unknown_id_reported(self):
        f = Path(self._tmp.name) / "asmt.json"
        f.write_text(json.dumps([{"id": "nope", "matched": [], "gaps": [], "rationale": ""}]))
        applied, unknown = skill_match.apply_assessments(str(f))
        self.assertEqual(applied, 0)
        self.assertEqual(unknown, ["nope"])


class WebEnrichIoTests(unittest.TestCase):
    def setUp(self):
        self._orig_data, self._orig_jobs = web_enrich.DATA, web_enrich.JOBS_PATH
        self._tmp = tempfile.TemporaryDirectory()
        roles = [
            # A: source-only, thin -> pending
            _role("a", atsUrl="", sourceUrl="https://www.linkedin.com/jobs/view/1",
                  url="https://www.linkedin.com/jobs/view/1", fullDescription="thin",
                  skillMatch={"matched": ["x"], "gaps": [], "rationale": "stale",
                              "assessedBy": "sonnet", "assessedAt": "2026-01-01"}),
            # B: has ATS url -> NOT a web-enrich candidate
            _role("b"),
            # C: source-only but already rich -> not pending
            _role("c", atsUrl="", sourceUrl="https://www.linkedin.com/jobs/view/3",
                  url="https://www.linkedin.com/jobs/view/3", fullDescription="x" * 400),
        ]
        data = write_data_dir(self._tmp.name, jobs={"schemaVersion": 2, "roles": roles, "meta": {}})
        web_enrich.DATA, web_enrich.JOBS_PATH = data, data / "jobs.json"

    def tearDown(self):
        web_enrich.DATA, web_enrich.JOBS_PATH = self._orig_data, self._orig_jobs
        self._tmp.cleanup()

    def test_list_pending_only_source_only_thin(self):
        rows = web_enrich.list_pending()
        self.assertEqual({r["id"] for r in rows}, {"a"})

    def test_apply_updates_and_clears_skillmatch(self):
        long_desc = "Senior Solutions Architect. Requirements: Python, AWS, Kubernetes. " * 10
        f = Path(self._tmp.name) / "enr.json"
        f.write_text(json.dumps([{"id": "a", "fullDescription": long_desc,
                                  "salaryMin": 170000, "salaryMax": 210000, "location": "Remote - US"}]))
        updated, recleared, skipped, unknown = web_enrich.apply_enrichments(str(f))
        self.assertEqual(updated, 1)
        self.assertEqual(recleared, 1)
        role = next(r for r in json.loads((web_enrich.JOBS_PATH).read_text())["roles"] if r["id"] == "a")
        self.assertGreater(len(role["fullDescription"]), 300)
        self.assertEqual(role["enrichedVia"], "web")
        self.assertNotIn("skillMatch", role)

    def test_apply_idempotent_skips_no_gain(self):
        f = Path(self._tmp.name) / "enr.json"
        f.write_text(json.dumps([{"id": "a", "fullDescription": "tiny"}]))  # no material gain
        updated, recleared, skipped, unknown = web_enrich.apply_enrichments(str(f))
        self.assertEqual(updated, 0)
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
