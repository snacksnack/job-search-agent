"""Board/table search matches query tokens at word starts, not anywhere (RC1-510).

Two layers:
  * Structural: both rendered pages ship the shared `matchesSearch` predicate and
    no longer use the naive `dataset.search.includes(q)` substring test.
  * Behavioral: the real scripts/assets/search.js is loaded through node and its
    `matchesSearch` is checked against fixtures. Skipped when node is absent so the
    suite stays runnable on a bare python3; CI runners have node.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import _fixtures  # noqa: F401
import render

SEARCH_JS = Path(__file__).resolve().parents[1] / "scripts" / "assets" / "search.js"


def _jobs():
    return {"roles": [
        {"id": "cisco-a", "company": "Cisco", "title": "Senior Engineering Program Manager",
         "url": "http://a", "matchPercent": 90, "location": "San Jose, CA", "rationale": "r"},
        {"id": "acme-b", "company": "Acme", "title": "Staff Engineer",
         "url": "http://b", "matchPercent": 80, "location": "San Francisco, CA", "rationale": "r"},
    ]}


class SearchWiringTests(unittest.TestCase):
    def test_both_views_ship_shared_predicate_and_drop_substring_test(self):
        board = render.render_html(_jobs(), {"jobs": {}})
        table = render.render_table_html(_jobs(), {"jobs": {}})
        for html in (board, table):
            self.assertIn("function matchesSearch", html)   # shared predicate injected
            self.assertIn("matchesSearch(", html)            # filter calls it
            self.assertNotIn("dataset.search.includes(", html)  # naive substring test gone


# Fixtures: blobs are lowercased exactly as render._search_blob produces them.
BEHAVIOR_CASES = [
    # (blob, query, expected)
    ("senior engineering program manager cisco san jose, ca", "cisco", True),   # real Cisco role
    ("staff engineer acme san francisco, ca", "cisco", False),                  # SF non-Cisco excluded
    ("senior engineering program manager acme", "eng", True),                   # prefix within a word
    ("staff engineer acme san francisco, ca", "san francisco", True),           # multi-word matches
    ("staff engineer acme san francisco, ca", "program manager", False),        # both tokens required
    ("roles currently available at acme", "ai", False),                         # "ai" not inside "available"
    ("ai platform engineer openai", "ai", True),                                # "ai" as a word start matches
    ("anything at all", "", True),                                              # empty query shows everything
]

_NODE_HARNESS = (
    "const {matchesSearch}=require(process.argv[1]);"
    "const cases=JSON.parse(process.argv[2]);"
    "const fails=cases.filter(c=>matchesSearch(c[0],c[1])!==c[2]);"
    "if(fails.length){console.error(JSON.stringify(fails));process.exit(1);}"
)


@unittest.skipUnless(shutil.which("node"), "node not installed; skipping JS behavior check")
class SearchBehaviorTests(unittest.TestCase):
    def test_word_boundary_matching(self):
        proc = subprocess.run(
            ["node", "-e", _NODE_HARNESS, str(SEARCH_JS), json.dumps(BEHAVIOR_CASES)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         "matchesSearch disagreed with fixtures:\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
