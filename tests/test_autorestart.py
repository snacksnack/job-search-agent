"""Auto-restart-on-code-change in serve.py (RC1-281)."""
import time
import unittest
from unittest import mock

import _fixtures  # noqa: F401  (path setup)
import serve


class FakeServer:
    def __init__(self):
        self.shutdown_called = False

    def shutdown(self):
        self.shutdown_called = True


class AutoRestartTests(unittest.TestCase):
    def setUp(self):
        serve._restart_pending.clear()

    def tearDown(self):
        serve._restart_pending.clear()

    def _wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_unchanged_code_does_not_restart(self):
        server = FakeServer()
        serve._restart_if_stale(server)
        self.assertFalse(serve._restart_pending.is_set())
        self.assertFalse(server.shutdown_called)

    def test_changed_mtime_triggers_shutdown_once(self):
        server = FakeServer()
        stale = tuple(0 for _ in serve._WATCHED)
        with mock.patch.object(serve, "_MTIMES_AT_START", stale):
            serve._restart_if_stale(server)
            self.assertTrue(serve._restart_pending.is_set())
            self.assertTrue(self._wait_for(lambda: server.shutdown_called))

            # A second request while the restart is pending must not spawn
            # another shutdown (idempotence guard).
            second = FakeServer()
            serve._restart_if_stale(second)
            time.sleep(0.05)
            self.assertFalse(second.shutdown_called)

    def test_watches_serve_and_render(self):
        names = {p.name for p in serve._WATCHED}
        self.assertEqual(names, {"serve.py", "render.py"})


if __name__ == "__main__":
    unittest.main()
