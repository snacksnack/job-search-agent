"""Interview-prep viewing: markdown converter + render_prep_page branches (RC1-103)."""
import tempfile
import unittest
from pathlib import Path

import _fixtures  # noqa: F401  (path setup)
import render


class MarkdownTests(unittest.TestCase):
    def test_headings(self):
        h = render.md_to_html("# Title\n## Sub")
        self.assertIn("<h1>Title</h1>", h)
        self.assertIn("<h2>Sub</h2>", h)

    def test_bold_italic_code_link(self):
        h = render.md_to_html("**b** and *i* and `c` and [x](https://e.com)")
        self.assertIn("<strong>b</strong>", h)
        self.assertIn("<em>i</em>", h)
        self.assertIn("<code>c</code>", h)
        self.assertIn('<a href="https://e.com" target="_blank" rel="noopener">x</a>', h)

    def test_unordered_and_ordered_lists(self):
        ul = render.md_to_html("- one\n- two")
        self.assertIn("<ul>", ul)
        self.assertEqual(ul.count("<li>"), 2)
        ol = render.md_to_html("1. a\n2. b")
        self.assertIn("<ol>", ol)

    def test_paragraph_and_escaping(self):
        h = render.md_to_html("a <script> & b")
        self.assertIn("<p>", h)
        self.assertNotIn("<script>", h)        # escaped
        self.assertIn("&lt;script&gt;", h)

    def test_code_fence(self):
        h = render.md_to_html("```\nx = 1\n```")
        self.assertIn("<pre><code>", h)
        self.assertIn("x = 1", h)


class PrepPageTests(unittest.TestCase):
    def setUp(self):
        self._orig = render.PREP_DIR
        self._tmp = tempfile.TemporaryDirectory()
        render.PREP_DIR = Path(self._tmp.name) / "interview-prep"

    def tearDown(self):
        render.PREP_DIR = self._orig
        self._tmp.cleanup()

    def _write_pack(self, role_id, md):
        d = render.PREP_DIR / role_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"prep-{role_id}.md").write_text(md, encoding="utf-8")

    def test_existing_pack_renders_200(self):
        self._write_pack("acme-tpm", "# Prep\n- STAR story one")
        self.assertTrue(render.has_prep("acme-tpm"))
        code, html = render.render_prep_page("acme-tpm")
        self.assertEqual(code, 200)
        self.assertIn("<h1>Prep</h1>", html)
        self.assertIn("STAR story one", html)

    def test_missing_pack_friendly_200(self):
        self.assertFalse(render.has_prep("nope-role"))
        code, html = render.render_prep_page("nope-role")
        self.assertEqual(code, 200)              # friendly page, not a raw 404
        self.assertIn("No interview prep yet", html)

    def test_unsafe_id_404(self):
        code, _ = render.render_prep_page("../../etc/passwd")
        self.assertEqual(code, 404)

    def test_has_prep_rejects_traversal(self):
        self.assertFalse(render.has_prep("../secrets"))


if __name__ == "__main__":
    unittest.main()
