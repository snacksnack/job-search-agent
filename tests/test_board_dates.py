"""Date-added display + sort hooks on both board views (RC1-280)."""
import unittest

import _fixtures  # noqa: F401
import render


def _jobs():
    return {"roles": [
        {"id": "acme-a", "company": "Acme", "title": "Senior TPM", "url": "http://a",
         "matchPercent": 90, "foundDate": "2026-08-15", "postedDate": "2026-08-14",
         "rationale": "r"},
        {"id": "beta-b", "company": "Beta", "title": "Solutions Engineer", "url": "http://b",
         "matchPercent": 80, "rationale": "r"},   # legacy role without foundDate
    ]}


class BoardDateTests(unittest.TestCase):
    def test_card_shows_added_date_and_data_attr(self):
        html = render.render_html(_jobs(), {"jobs": {}})
        self.assertIn('data-added="2026-08-15"', html)
        self.assertIn('<span class="mk">added</span>2026-08-15', html)
        self.assertIn('data-added=""', html)               # legacy role: attr present, empty
        self.assertIn('id="sortSelect"', html)             # board sort control shipped
        self.assertIn('value="added-desc"', html)

    def test_table_has_sortable_added_column(self):
        html = render.render_table_html(_jobs(), {"jobs": {}})
        self.assertIn('<th data-sort="added"', html)
        self.assertIn('<td class="c-added">2026-08-15</td>', html)
        self.assertIn('<td class="c-added">—</td>', html)  # legacy role renders a dash
        self.assertIn('data-added="2026-08-15"', html)


if __name__ == "__main__":
    unittest.main()
