"""Cadence-based manual-check reminders for unfetchable boards (RC1-279)."""
import contextlib
import datetime
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline


def _search(cadence="weekly"):
    return {"schemaVersion": 2, "searches": [], "watchlist": [
        {"company": "HashiCorp", "ats": "workday", "cadence": cadence,
         "boardUrl": "https://www.hashicorp.com/en/careers"},
        {"company": "Acme", "ats": "greenhouse", "slug": "acme"},   # fetchable -> no reminder
    ]}


class ManualCheckTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._tmp = tempfile.TemporaryDirectory()
        pipeline.DATA = write_data_dir(self._tmp.name, search=_search())

    def tearDown(self):
        pipeline.DATA = self._orig_data
        self._tmp.cleanup()

    def _state_path(self):
        return pipeline.DATA / pipeline.MANUAL_CHECK_STATE

    def _run(self, search=None, dry_run=False):
        log = {"sources": []}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            due = pipeline.manual_check_reminders(search or _search(), log, dry_run=dry_run)
        return due, log, buf.getvalue()

    def test_never_reminded_is_due_and_stamped(self):
        due, log, out = self._run()
        self.assertEqual([d["company"] for d in due], ["HashiCorp"])
        self.assertEqual(log["manualChecks"][0]["cadence"], "weekly")
        self.assertIn("CHECK  HashiCorp (workday, weekly, last reminded never)", out)
        self.assertIn("never a logged-in browse", out)
        state = json.loads(self._state_path().read_text())
        self.assertEqual(state["HashiCorp"]["lastReminded"], pipeline.TODAY)

    def test_within_cadence_not_due(self):
        self._run()                                   # stamps today
        due, log, out = self._run()
        self.assertEqual(due, [])
        self.assertNotIn("manualChecks", log)

    def test_due_again_after_cadence_elapses(self):
        stale = (datetime.date.fromisoformat(pipeline.TODAY)
                 - datetime.timedelta(days=8)).isoformat()
        self._state_path().write_text(json.dumps({"HashiCorp": {"lastReminded": stale}}))
        due, _, out = self._run()
        self.assertEqual([d["company"] for d in due], ["HashiCorp"])
        self.assertIn(f"last reminded {stale}", out)

    def test_monthly_cadence_respected(self):
        stale = (datetime.date.fromisoformat(pipeline.TODAY)
                 - datetime.timedelta(days=10)).isoformat()
        self._state_path().write_text(json.dumps({"HashiCorp": {"lastReminded": stale}}))
        due, _, _ = self._run(search=_search(cadence="monthly"))
        self.assertEqual(due, [])                     # 10 days < 30

    def test_dry_run_reports_but_does_not_stamp(self):
        due, _, _ = self._run(dry_run=True)
        self.assertEqual(len(due), 1)
        self.assertFalse(self._state_path().exists())
        # so the next real run still reminds
        due2, _, _ = self._run()
        self.assertEqual(len(due2), 1)


if __name__ == "__main__":
    unittest.main()
