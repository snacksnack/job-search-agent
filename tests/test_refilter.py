"""Tests for the --refilter pass (pipeline.refilter).

refilter() re-applies the current filter cascade + scoring to the EXISTING
board and archives roles that no longer qualify, without touching roles the
user has decided on or saved. These lock in that contract.
"""
import contextlib
import io
import json
import tempfile
import unittest

from _fixtures import write_data_dir
import pipeline


def _role(**kw):
    base = {
        "id": "r", "company": "Acme",
        "title": "Senior Technical Program Manager",
        "url": "https://job-boards.greenhouse.io/acme/jobs/1",
        "location": "Remote - US", "matchPercent": 80,
        "foundDate": pipeline.TODAY,
        "fullDescription": "Drive cross-functional delivery across teams.",
    }
    base.update(kw)
    return base


def _refilter(dry_run=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return pipeline.refilter(dry_run=dry_run)


class RefilterTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def _setup(self, roles, state=None):
        pipeline.DATA = write_data_dir(
            self._tmp.name,
            jobs={"schemaVersion": 2, "roles": roles, "meta": {}},
            state=state,
        )

    def _jobs(self):
        return json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]

    def _archive(self):
        p = pipeline.DATA / "archive.json"
        return json.loads(p.read_text())["roles"] if p.exists() else []

    def test_offtarget_archived_ontarget_kept(self):
        self._setup([
            _role(id="tpm", title="Senior Technical Program Manager"),
            _role(id="ae", title="Account Executive, Enterprise",
                  fullDescription="Carry a quota and close deals."),
        ])
        self.assertEqual(_refilter(), 0)
        kept = [r["id"] for r in self._jobs()]
        archived = {r["id"]: r for r in self._archive()}
        self.assertEqual(kept, ["tpm"])
        self.assertIn("ae", archived)
        self.assertTrue(archived["ae"].get("archivedReason"))
        self.assertEqual(archived["ae"].get("archivedDate"), pipeline.TODAY)

    def test_decided_role_in_jobs_map_is_protected(self):
        self._setup(
            [_role(id="ae", title="Account Executive, Enterprise")],
            state={"schemaVersion": 1, "jobs": {"ae": {"status": "applied"}}},
        )
        _refilter()
        self.assertEqual([r["id"] for r in self._jobs()], ["ae"])
        self.assertEqual(self._archive(), [])

    def test_decided_role_as_top_level_key_is_protected(self):
        # Applied roles are stored as a top-level id key, not under "jobs".
        self._setup(
            [_role(id="ae", title="Account Executive, Enterprise")],
            state={"schemaVersion": 1, "jobs": {}, "ae": {"status": "applied"}},
        )
        _refilter()
        self.assertEqual([r["id"] for r in self._jobs()], ["ae"])

    def test_user_saved_role_is_protected(self):
        self._setup([_role(id="ae", title="Account Executive, Enterprise", userSaved=True)])
        _refilter()
        self.assertEqual([r["id"] for r in self._jobs()], ["ae"])

    def test_kept_role_is_rescored(self):
        self._setup([_role(id="tpm", title="Senior Technical Program Manager", matchPercent=0)])
        _refilter()
        kept = self._jobs()[0]
        self.assertGreater(kept["matchPercent"], 0)

    def test_dry_run_writes_nothing(self):
        self._setup([_role(id="ae", title="Account Executive, Enterprise")])
        before = (pipeline.DATA / "jobs.json").read_text()
        self.assertEqual(_refilter(dry_run=True), 0)
        self.assertEqual((pipeline.DATA / "jobs.json").read_text(), before)
        self.assertFalse((pipeline.DATA / "archive.json").exists())

    def test_archived_role_keeps_its_cached_assessment(self):
        sm = {"assessedBy": "test", "matched": ["Python"], "gaps": []}
        self._setup([_role(id="ae", title="Account Executive, Enterprise", skillMatch=sm)])
        _refilter()
        archived = {r["id"]: r for r in self._archive()}
        self.assertIn("ae", archived)
        self.assertEqual(archived["ae"].get("skillMatch"), sm)

    # RC1-649: a legacy Adzuna guess (single figure, Adzuna-only) is moved to
    # salaryEstimate and never archives the role; a posted low range still does.

    def test_adzuna_single_figure_guess_is_kept_and_migrated(self):
        self._setup([_role(id="guess", source="adzuna", appearedInSources=["adzuna"],
                           salaryMin=120000, salaryMax=120000)])
        self.assertEqual(_refilter(), 0)
        kept = {r["id"]: r for r in self._jobs()}
        self.assertIn("guess", kept)
        self.assertIsNone(kept["guess"]["salaryMax"])
        self.assertEqual(kept["guess"]["salaryEstimate"], 120000)

    def test_posted_low_range_still_archived(self):
        self._setup([_role(id="low", source="adzuna", appearedInSources=["adzuna"],
                           salaryMin=110000, salaryMax=130000)])
        self.assertEqual(_refilter(), 0)
        self.assertIn("low", {r["id"] for r in self._archive()})

    def test_single_figure_from_other_source_still_filtered(self):
        self._setup([_role(id="ats", source="greenhouse", appearedInSources=["greenhouse"],
                           salaryMin=120000, salaryMax=120000)])
        self.assertEqual(_refilter(), 0)
        self.assertIn("ats", {r["id"] for r in self._archive()})

    def test_dry_run_does_not_write_migration(self):
        self._setup([_role(id="guess", source="adzuna", appearedInSources=["adzuna"],
                           salaryMin=120000, salaryMax=120000)])
        self.assertEqual(_refilter(dry_run=True), 0)
        self.assertEqual(self._jobs()[0]["salaryMax"], 120000)


if __name__ == "__main__":
    unittest.main()
