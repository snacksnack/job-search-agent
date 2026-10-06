"""Trusted-source inbox finds bypass the filter cascade (RC1-501).

A LinkedIn save is the user's own decision: it must land on the board even when
the title/location/salary rules would reject it, and it carries a userSaved flag
for the board. Dedup and state.json decisions still apply, and the same find
from a non-trusted source is still filtered.
"""
import contextlib
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import make_profile, write_data_dir
import pipeline

# Deliberately out-of-scope on two axes: no target-title signal, hybrid outside
# the NYC metro. Only the trusted-source path may board it.
OFFBEAT = {
    "title": "Complex Project Manager - Hybrid Cloud & Data",
    "company": "IBM",
    "url": "https://www.linkedin.com/jobs/view/9009001/",
    "location": "Austin, TX (Hybrid)",
    "description": "Coordinate complex client programs. " * 10,
}


def _profile_with_trust():
    profile = make_profile()
    profile["matching"]["trustedSources"] = ["linkedinSaved"]
    return profile


class TrustedSourceTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        pipeline.http_get_json = lambda url, timeout=20: {"jobs": []}

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _setup(self, inbox_find, *, state=None, profile=None):
        pipeline.DATA = write_data_dir(self._tmp.name, profile=profile or _profile_with_trust(),
                                       state=state)
        box = pipeline.DATA / "inbox"
        box.mkdir()
        (box / "saves.json").write_text(json.dumps([inbox_find]), encoding="utf-8")

    def _run(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = pipeline.run(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        roles = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]
        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        return roles, log

    def test_saved_find_boards_despite_failing_every_filter(self):
        self._setup(dict(OFFBEAT, source="linkedinSaved"))
        roles, log = self._run()
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["company"], "IBM")
        self.assertTrue(roles[0]["userSaved"])
        self.assertEqual(log["counts"]["qualified"], 1)
        self.assertEqual(log["counts"]["skipped"], {})

    def test_saved_find_skips_the_age_filter(self):
        stale = dict(OFFBEAT, source="linkedinSaved", postedDate="2020-01-01")
        self._setup(stale)
        roles, _ = self._run()
        self.assertEqual(len(roles), 1)

    def test_same_find_from_untrusted_source_is_still_filtered(self):
        self._setup(dict(OFFBEAT, source="linkedinKeyword"))
        roles, log = self._run()
        self.assertEqual(roles, [])
        self.assertEqual(log["counts"]["qualified"], 0)
        self.assertEqual(sum(log["counts"]["skipped"].values()), 1)

    def test_without_the_config_nothing_is_trusted(self):
        profile = make_profile()
        profile["matching"].pop("trustedSources", None)
        self._setup(dict(OFFBEAT, source="linkedinSaved"), profile=profile)
        roles, _ = self._run()
        self.assertEqual(roles, [])

    def test_decided_role_is_not_resurfaced_by_a_save(self):
        rid = pipeline.slugify(OFFBEAT["company"], OFFBEAT["title"])
        state = {"schemaVersion": 1, "jobs": {rid: {"status": "hidden"}}}
        self._setup(dict(OFFBEAT, source="linkedinSaved"), state=state)
        roles, _ = self._run()
        self.assertEqual(roles, [])


if __name__ == "__main__":
    unittest.main()
