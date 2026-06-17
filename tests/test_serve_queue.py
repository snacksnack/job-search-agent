"""Queue helpers in serve.py (interview-prep mirrors cover-letter)."""
import json
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401  (path setup)
import serve


class InterviewPrepQueueTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        data = Path(self._tmp.name) / "data"
        data.mkdir(parents=True)
        (data / "jobs.json").write_text(json.dumps({"roles": [
            {"id": "r1", "company": "Acme", "title": "Technical Program Manager",
             "atsUrl": "https://job-boards.greenhouse.io/acme/jobs/1"},
        ]}), encoding="utf-8")
        self._orig = (serve.JOBS_PATH, serve.QUEUE_PREP_PATH)
        serve.JOBS_PATH = data / "jobs.json"
        serve.QUEUE_PREP_PATH = data / "queue" / "interview-prep.json"

    def tearDown(self):
        serve.JOBS_PATH, serve.QUEUE_PREP_PATH = self._orig
        self._tmp.cleanup()

    def test_enqueue_appends_pending_request(self):
        n = serve.queue_interview_prep("r1")
        self.assertEqual(n, 1)
        q = json.loads(serve.QUEUE_PREP_PATH.read_text())
        self.assertEqual(len(q["requests"]), 1)
        req = q["requests"][0]
        self.assertEqual(req["id"], "r1")
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["company"], "Acme")
        self.assertTrue(req["url"])  # carried the apply link

    def test_dedup_while_pending(self):
        serve.queue_interview_prep("r1")
        n = serve.queue_interview_prep("r1")
        self.assertEqual(n, 1)  # not double-queued
        q = json.loads(serve.QUEUE_PREP_PATH.read_text())
        self.assertEqual(len(q["requests"]), 1)

    def test_unknown_id_raises_keyerror(self):
        with self.assertRaises(KeyError):
            serve.queue_interview_prep("does-not-exist")

    def test_prep_and_cover_queues_are_separate_files(self):
        self.assertNotEqual(serve.QUEUE_PREP_PATH, serve.QUEUE_PATH)


if __name__ == "__main__":
    unittest.main()
