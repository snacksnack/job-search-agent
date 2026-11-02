"""RC1-586: the descriptionSkip cascade re-runs when a canonical JD arrives.

run()'s cascade can only judge a posting on the text its discovering source
carried. A LinkedIn find arrives title-only, so description_ok() has nothing to
fire on and a quota-carrying role lands on the board: Grafana Labs "Solutions
Engineer | East Coast | Remote" (explicit OTE) was rejected from the Greenhouse
sweep and accepted from its own thin LinkedIn copy in the same run (2026-10-31).
These lock in the re-check at the two points a fuller JD can arrive --
pipeline.py --reenrich and web_enrich.py --apply -- plus the archive contract
both of them share with refilter().
"""
import contextlib
import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path

from _fixtures import make_profile, write_data_dir
import pipeline
import web_enrich

QUOTA_JD = ("Senior Solutions Engineer. You will carry a quota and close deals "
            "alongside the account team; commission is a core part of your OTE. " * 4)
CLEAN_JD = ("Senior Solutions Engineer. You will scope integrations with enterprise "
            "customers, build reference architectures, and partner with engineering. " * 4)


def _role(**kw):
    base = {
        "id": "r", "company": "Grafana Labs",
        "title": "Solutions Engineer | East Coast | Remote",
        "url": "https://www.linkedin.com/jobs/view/1",
        "location": "Remote - US", "matchPercent": 69,
        "foundDate": pipeline.TODAY,
        "fullDescription": "Solutions Engineer | East Coast | Remote",
    }
    base.update(kw)
    return base


class DescriptionRecheckTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def test_quota_jd_evicts(self):
        reason = pipeline.description_recheck(_role(fullDescription=QUOTA_JD), self.p, set())
        self.assertIsNotNone(reason)
        self.assertIn("descriptionSkip", reason)

    def test_clean_jd_kept(self):
        self.assertIsNone(
            pipeline.description_recheck(_role(fullDescription=CLEAN_JD), self.p, set()))

    def test_decided_role_never_evicted(self):
        """state.json is the user's: a role they already applied to or hid stays
        put even if its full JD now trips a skip."""
        role = _role(fullDescription=QUOTA_JD)
        self.assertIsNone(pipeline.description_recheck(role, self.p, {"r"}))

    def test_user_saved_role_never_evicted(self):
        role = _role(fullDescription=QUOTA_JD, userSaved=True)
        self.assertIsNone(pipeline.description_recheck(role, self.p, set()))

    def test_decided_ids_reads_both_shapes(self):
        state = {"schemaVersion": 1,
                 "jobs": {"a": {"status": "applied"}},
                 "b": {"status": "hidden"},
                 "c": "not-a-dict"}
        self.assertEqual(pipeline.decided_ids(state), {"a", "b"})


class ArchiveEvictedTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()
        pipeline.DATA = write_data_dir(self._tmp.name)

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def test_evicted_role_leaves_board_keeps_record_and_is_logged(self):
        keep = _role(id="keep", fullDescription=CLEAN_JD)
        drop = _role(id="drop", fullDescription=QUOTA_JD,
                     skillMatch={"matched": ["Python"], "gaps": [], "rationale": "r",
                                 "assessedBy": "sonnet", "assessedAt": "2026-10-31"})
        jobs = {"schemaVersion": 2, "roles": [keep, drop], "meta": {}}
        started = datetime.datetime.now().isoformat(timespec="seconds")
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.archive_evicted(jobs, [(drop, "descriptionSkip: quota-carrying role")],
                                     started)

        self.assertEqual([r["id"] for r in jobs["roles"]], ["keep"])

        archived = json.loads((pipeline.DATA / "archive.json").read_text())["roles"]
        self.assertEqual([r["id"] for r in archived], ["drop"])
        self.assertEqual(archived[0]["archivedReason"], "descriptionSkip: quota-carrying role")
        self.assertEqual(archived[0]["archivedDate"], pipeline.TODAY)
        # RC1-297: an assessment is never deleted, only carried into the archive.
        self.assertEqual(archived[0]["skillMatch"]["assessedBy"], "sonnet")

        log = pipeline.DATA / "logs" / f"{pipeline.REJECTS_PREFIX}{pipeline.TODAY}.jsonl"
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([r["id"] for r in rows], ["drop"])
        self.assertEqual(rows[0]["reason"], "descriptionSkip")
        self.assertEqual(rows[0]["detail"], "quota-carrying role")

    def test_appends_to_an_existing_archive(self):
        (pipeline.DATA / "archive.json").write_text(json.dumps(
            {"schemaVersion": 1, "roles": [_role(id="old")], "meta": {}}))
        drop = _role(id="drop", fullDescription=QUOTA_JD)
        jobs = {"schemaVersion": 2, "roles": [drop], "meta": {}}
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.archive_evicted(jobs, [(drop, "descriptionSkip: quota-carrying role")], "now")
        archived = json.loads((pipeline.DATA / "archive.json").read_text())
        self.assertEqual([r["id"] for r in archived["roles"]], ["old", "drop"])
        self.assertEqual(archived["meta"]["count"], 2)

    def test_nothing_evicted_writes_nothing(self):
        jobs = {"schemaVersion": 2, "roles": [_role()], "meta": {}}
        pipeline.archive_evicted(jobs, [], "now")
        self.assertFalse((pipeline.DATA / "archive.json").exists())
        self.assertEqual(len(jobs["roles"]), 1)


class ReenrichRecheckTests(unittest.TestCase):
    """--reenrich is the ATS path: the canonical JD replaces a thin one, so the
    description check gets its first honest look at the posting."""

    def setUp(self):
        self._orig_data, self._orig_enrich = pipeline.DATA, pipeline.enrich_from_ats
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pipeline.DATA, pipeline.enrich_from_ats = self._orig_data, self._orig_enrich
        self._tmp.cleanup()

    def _run(self, roles, jd, state=None, dry_run=False):
        pipeline.DATA = write_data_dir(
            self._tmp.name, jobs={"schemaVersion": 2, "roles": roles, "meta": {}}, state=state)
        pipeline.enrich_from_ats = lambda url: {"description": jd}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            pipeline.reenrich(dry_run=dry_run)
        return out.getvalue()

    def _board(self):
        return [r["id"] for r in json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]]

    def test_quota_jd_from_ats_evicts_the_linkedin_copy(self):
        role = _role(atsUrl="https://boards.greenhouse.io/grafanalabs/jobs/1")
        self._run([role], QUOTA_JD)
        self.assertEqual(self._board(), [])
        archived = json.loads((pipeline.DATA / "archive.json").read_text())["roles"]
        self.assertEqual(archived[0]["archivedReason"], "descriptionSkip: quota-carrying role")

    def test_clean_jd_from_ats_keeps_the_role(self):
        role = _role(atsUrl="https://boards.greenhouse.io/grafanalabs/jobs/1")
        self._run([role], CLEAN_JD)
        self.assertEqual(self._board(), ["r"])
        self.assertFalse((pipeline.DATA / "archive.json").exists())

    def test_decided_role_survives_a_quota_jd(self):
        role = _role(atsUrl="https://boards.greenhouse.io/grafanalabs/jobs/1")
        self._run([role], QUOTA_JD, state={"schemaVersion": 1, "jobs": {"r": {"status": "applied"}}})
        self.assertEqual(self._board(), ["r"])

    def test_dry_run_reports_but_writes_nothing(self):
        role = _role(atsUrl="https://boards.greenhouse.io/grafanalabs/jobs/1")
        out = self._run([role], QUOTA_JD, dry_run=True)
        self.assertIn("archived on full JD", out)
        self.assertEqual(self._board(), ["r"])
        self.assertFalse((pipeline.DATA / "archive.json").exists())


class WebEnrichRecheckTests(unittest.TestCase):
    """web_enrich --apply is the browser path, and had the identical hole."""

    def setUp(self):
        self._orig = (web_enrich.DATA, web_enrich.JOBS_PATH, pipeline.DATA)
        self._tmp = tempfile.TemporaryDirectory()
        data = write_data_dir(self._tmp.name, jobs={
            "schemaVersion": 2, "roles": [_role(atsUrl="", fullDescription="thin")], "meta": {}})
        web_enrich.DATA, web_enrich.JOBS_PATH, pipeline.DATA = data, data / "jobs.json", data

    def tearDown(self):
        web_enrich.DATA, web_enrich.JOBS_PATH, pipeline.DATA = self._orig
        self._tmp.cleanup()

    def _apply(self, jd):
        f = Path(self._tmp.name) / "enr.json"
        f.write_text(json.dumps([{"id": "r", "fullDescription": jd}]))
        with contextlib.redirect_stdout(io.StringIO()):
            return web_enrich.apply_enrichments(str(f))

    def test_quota_jd_read_in_the_browser_evicts(self):
        *_, evicted = self._apply(QUOTA_JD)
        self.assertEqual([r["id"] for r, _ in evicted], ["r"])
        self.assertEqual(json.loads(web_enrich.JOBS_PATH.read_text())["roles"], [])

    def test_clean_jd_read_in_the_browser_keeps_the_role(self):
        *_, evicted = self._apply(CLEAN_JD)
        self.assertEqual(evicted, [])
        self.assertEqual(
            [r["id"] for r in json.loads(web_enrich.JOBS_PATH.read_text())["roles"]], ["r"])


if __name__ == "__main__":
    unittest.main()
