"""Tests for the --rescore pass (pipeline.rescore).

rescore() recomputes matchPercent for every existing role against the current
scoring, writing nothing else -- no cascade, no archiving, no re-assessment.
These lock in that contract (RC1-526): a scoring change lands on the whole
board, off-target roles are not archived, and cached assessments are untouched.
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
        "location": "Remote - US", "matchPercent": 0,
        "foundDate": pipeline.TODAY,
        "fullDescription": "Drive cross-functional delivery across teams.",
    }
    base.update(kw)
    return base


def _rescore(dry_run=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return pipeline.rescore(dry_run=dry_run)


class RescoreTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def _setup(self, roles):
        pipeline.DATA = write_data_dir(
            self._tmp.name,
            jobs={"schemaVersion": 2, "roles": roles, "meta": {}},
        )

    def _jobs(self):
        return json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]

    def test_stale_score_recomputed(self):
        self._setup([_role(id="tpm", matchPercent=0)])
        self.assertEqual(_rescore(), 0)
        self.assertGreater(self._jobs()[0]["matchPercent"], 0)

    def test_offtarget_role_kept_not_archived(self):
        # Unlike --refilter, rescore never archives: an off-target role stays on the
        # board (just re-scored), and no archive.json is written.
        self._setup([_role(id="ae", title="Account Executive, Enterprise",
                           fullDescription="Carry a quota and close deals.")])
        _rescore()
        self.assertEqual([r["id"] for r in self._jobs()], ["ae"])
        self.assertFalse((pipeline.DATA / "archive.json").exists())

    def test_assessment_preserved(self):
        sm = {"matched": ["a", "b", "c"], "gaps": ["x"], "assessedBy": "sonnet"}
        self._setup([_role(id="tpm", skillMatch=sm, matchPercent=0)])
        _rescore()
        self.assertEqual(self._jobs()[0]["skillMatch"], sm)

    def test_dry_run_writes_nothing(self):
        self._setup([_role(id="tpm", matchPercent=0)])
        _rescore(dry_run=True)
        self.assertEqual(self._jobs()[0]["matchPercent"], 0)  # unchanged on disk
