"""RC1-589: --verify-open re-checks long-idle roles against their own ATS board.

mark_closed_listings only diffs roles with an atsUrl at a successfully-fetched
WATCHLIST company, so a role found anywhere else is never looked at again: 695
undecided open roles were older than 30 days, 560 of them at non-watchlist
companies. This pass fetches each role's own board from its apply url.
"""
import contextlib
import io
import json
import tempfile
import unittest

from _fixtures import write_data_dir
import pipeline


def _role(rid, company, title, found, ats_url, **kw):
    base = {"id": rid, "company": company, "title": title, "foundDate": found,
            "atsUrl": ats_url, "url": ats_url, "location": "Remote - US",
            "matchPercent": 80, "fullDescription": "x" * 400}
    base.update(kw)
    return base


OLD = "2026-01-01"          # far older than stale_days
NEW = pipeline.TODAY


class VerifyOpenTests(unittest.TestCase):
    def setUp(self):
        self._orig_data, self._orig_fetchers = pipeline.DATA, dict(pipeline.ATS_FETCHERS)
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.ATS_FETCHERS.clear()
        pipeline.ATS_FETCHERS.update(self._orig_fetchers)
        self._tmp.cleanup()

    def _run(self, roles, boards, state=None, **kw):
        pipeline.DATA = write_data_dir(
            self._tmp.name, jobs={"schemaVersion": 2, "roles": roles, "meta": {}}, state=state)

        def fetch(slug, _boards=boards):
            if slug not in _boards:
                raise ValueError(f"board {slug} not found")
            return _boards[slug]
        pipeline.ATS_FETCHERS["greenhouse"] = fetch
        with contextlib.redirect_stdout(io.StringIO()) as out:
            pipeline.verify_open(**kw)
        return out.getvalue()

    def _stored(self):
        return {r["id"]: r for r in json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]}

    def test_vanished_role_is_closed_and_live_one_is_left_alone(self):
        gone = _role("gone", "Kong", "Staff Forward Deployed Engineer", OLD,
                     "https://job-boards.greenhouse.io/kong/jobs/1")
        live = _role("live", "Kong", "Technical Program Manager", OLD,
                     "https://job-boards.greenhouse.io/kong/jobs/2")
        self._run([gone, live], {"kong": [
            {"url": "https://job-boards.greenhouse.io/kong/jobs/2",
             "title": "Technical Program Manager"}]})
        stored = self._stored()
        self.assertTrue(stored["gone"]["closed"])
        self.assertEqual(stored["gone"]["closedDate"], pipeline.TODAY)
        self.assertIsNone(stored["live"].get("closed"))

    def test_a_reposted_req_under_a_new_id_is_not_closed(self):
        """RC1-588's lesson: the stored url 404s because the req was reposted with
        a new ATS id. The company+title slug fallback is what keeps it alive, and
        why this pass diffs the board instead of probing the stored url."""
        r = _role("repost", "SingleStore", "Forward Deployment Engineer- Greater NYC", OLD,
                  "https://job-boards.greenhouse.io/singlestore/jobs/7793656")
        self._run([r], {"singlestore": [
            {"url": "https://job-boards.greenhouse.io/singlestore/jobs/8329211",
             "title": "Forward Deployment Engineer- Greater NYC "}]})
        self.assertIsNone(self._stored()["repost"].get("closed"))

    def test_a_failed_board_fetch_never_closes_its_roles(self):
        r = _role("x", "Transcarent", "Technical Program Manager", OLD,
                  "https://job-boards.greenhouse.io/transcarent/jobs/1")
        out = self._run([r], {})          # every fetch raises
        self.assertIsNone(self._stored()["x"].get("closed"))
        self.assertIn("board fetch", out)

    def test_fresh_and_decided_roles_are_skipped(self):
        fresh = _role("fresh", "Kong", "Technical Program Manager", NEW,
                      "https://job-boards.greenhouse.io/kong/jobs/9")
        applied = _role("applied", "Kong", "Solutions Engineer", OLD,
                        "https://job-boards.greenhouse.io/kong/jobs/8")
        self._run([fresh, applied], {"kong": []},
                  state={"schemaVersion": 1, "jobs": {"applied": {"status": "applied"}}})
        stored = self._stored()
        self.assertIsNone(stored["fresh"].get("closed"))
        self.assertIsNone(stored["applied"].get("closed"))

    def test_roles_with_no_resolvable_ats_url_are_reported_not_closed(self):
        r = _role("li", "Meta", "Technical Program Manager", OLD, "")
        r["url"] = "https://www.linkedin.com/jobs/view/1"
        out = self._run([r], {"kong": []})
        self.assertIsNone(self._stored()["li"].get("closed"))
        self.assertIn("no resolvable ATS url", out)

    def test_board_limit_defers_work_without_touching_it(self):
        roles = [_role(f"a{i}", "Kong", f"Technical Program Manager {i}", OLD,
                       f"https://job-boards.greenhouse.io/kong/jobs/{i}") for i in range(2)]
        roles.append(_role("b", "Other", "Technical Program Manager", OLD,
                           "https://job-boards.greenhouse.io/other/jobs/1"))
        out = self._run(roles, {"kong": [], "other": []}, board_limit=1)
        self.assertIn("deferring 1", out)
        # kong has the most stale roles, so it is the board that gets fetched
        stored = self._stored()
        self.assertTrue(stored["a0"]["closed"])
        self.assertIsNone(stored["b"].get("closed"))

    def test_dry_run_writes_nothing(self):
        r = _role("gone", "Kong", "Technical Program Manager", OLD,
                  "https://job-boards.greenhouse.io/kong/jobs/1")
        self._run([r], {"kong": []}, dry_run=True)
        self.assertIsNone(self._stored()["gone"].get("closed"))


if __name__ == "__main__":
    unittest.main()
