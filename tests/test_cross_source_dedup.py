"""Company+title dedup for postings re-discovered from another source (RC1-296)."""
import contextlib
import io
import json
import tempfile
import unittest

import _fixtures  # noqa: F401
from _fixtures import write_data_dir
import pipeline

OLD_DESC = "Drive cross-functional delivery across engineering teams. " * 12
NEW_DESC = ("Drive cross-functional delivery across engineering teams and own the "
            "platform roadmap. Salary transparency added. " * 12)

TITLE = "Senior Technical Program Manager"
GH_URL = "https://job-boards.greenhouse.io/acme/jobs/3"
LI_URL = "https://www.linkedin.com/jobs/view/4001"


def _gh_job(title, desc, jid=3, location="Remote - US"):
    return {"id": jid, "title": title,
            "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{jid}",
            "updated_at": pipeline.TODAY + "T10:00:00Z",
            "location": {"name": location}, "content": f"<p>{desc}</p>"}


def _linkedin_save(title, desc, location="Remote - US", **extra):
    """A role already on the board from a LinkedIn save: `li-` id, listing url, no ATS link."""
    r = {"id": f"li-acme-{pipeline.slugify(title)}", "company": "Acme", "title": title,
         "url": LI_URL, "sourceUrl": LI_URL, "atsUrl": "",
         "source": "linkedin", "appearedInSources": ["linkedin"],
         "location": location, "matchPercent": 72, "foundDate": "2026-08-01",
         "fullDescription": desc,
         "skillMatch": {"matched": ["Python", "AWS"], "gaps": [], "rationale": "cached",
                        "assessedBy": "opus-skillmatch-2026-08-01", "assessedAt": "2026-08-01"}}
    r.update(extra)
    return r


class SamePostingLocationTests(unittest.TestCase):
    def test_wordings_of_the_same_place_match(self):
        for a, b in (("New York, NY", "New York"), ("Remote - US", "Remote"),
                     ("New York NY", "New York, NY"), ("Remote - US", "Remote, US")):
            self.assertTrue(pipeline.same_posting_location(a, b), f"{a!r} vs {b!r}")
            self.assertTrue(pipeline.same_posting_location(b, a), f"{b!r} vs {a!r}")

    def test_different_places_do_not_match(self):
        for a, b in (("New York, NY", "Austin, TX"), ("Remote - US", "Remote - Canada"),
                     ("CA", "Chicago, IL")):
            self.assertFalse(pipeline.same_posting_location(a, b), f"{a!r} vs {b!r}")
            self.assertFalse(pipeline.same_posting_location(b, a), f"{b!r} vs {a!r}")

    def test_unknown_location_is_compatible(self):
        self.assertTrue(pipeline.same_posting_location("", "New York, NY"))
        self.assertTrue(pipeline.same_posting_location("New York, NY", None))


class CrossSourceDedupTests(unittest.TestCase):
    def setUp(self):
        self._orig_data = pipeline.DATA
        self._orig_http = pipeline.http_get_json
        self._tmp = tempfile.TemporaryDirectory()
        self.search = {"schemaVersion": 2, "searches": [], "watchlist": [
            {"company": "Acme", "ats": "greenhouse", "slug": "acme"}]}

    def tearDown(self):
        pipeline.DATA = self._orig_data
        pipeline.http_get_json = self._orig_http
        self._tmp.cleanup()

    def _setup(self, stored_roles, live_jobs, inbox=None):
        jobs = {"schemaVersion": 2, "roles": stored_roles, "meta": {}}
        pipeline.DATA = write_data_dir(self._tmp.name, jobs=jobs, search=self.search)
        pipeline.http_get_json = lambda url, timeout=20: {"jobs": live_jobs}
        if inbox:
            box = pipeline.DATA / "inbox"
            box.mkdir()
            (box / "saves.json").write_text(json.dumps(inbox), encoding="utf-8")

    def _run(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = pipeline.run(dry_run=False, max_age_days=2)
        self.assertEqual(rc, 0)
        roles = json.loads((pipeline.DATA / "jobs.json").read_text())["roles"]
        log = json.loads((pipeline.DATA / "search-log.json").read_text())["runs"][-1]
        return roles, log, buf.getvalue()

    def test_ats_rediscovery_merges_into_the_linkedin_row(self):
        # The exact shape from the ticket: same job, `li-` id + listing url on the
        # board, canonical slug id + ATS url incoming. Neither id- nor url-dedup can
        # see it, so before RC1-296 this appended a second row.
        self._setup([_linkedin_save(TITLE, OLD_DESC)], [_gh_job(TITLE, NEW_DESC)])
        roles, log, out = self._run()
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual(r["id"], f"li-acme-{pipeline.slugify(TITLE)}")   # stored row kept
        self.assertEqual(r["atsUrl"], GH_URL)                            # apply link gained
        self.assertEqual(r["url"], GH_URL)
        self.assertEqual(r["sourceUrl"], LI_URL)                         # listing url kept
        self.assertEqual(r["appearedInSources"], ["linkedin", "greenhouse"])
        self.assertIn("Salary transparency added.", r["fullDescription"])
        self.assertEqual(r["changedDate"], pipeline.TODAY)
        self.assertEqual(log["counts"]["mergedCrossSource"], 1)
        self.assertEqual(log["counts"]["qualified"], 0)
        self.assertIn("Cross-source dedup: 1 posting(s)", out)

    def test_merge_tolerates_differently_worded_locations(self):
        self._setup([_linkedin_save(TITLE, OLD_DESC, location="New York")],
                    [_gh_job(TITLE, NEW_DESC, location="New York, NY")])
        roles, log, _ = self._run()
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["atsUrl"], GH_URL)
        self.assertEqual(roles[0]["location"], "New York, NY")

    def test_sibling_posting_in_another_metro_is_not_merged(self):
        # Same company+title, genuinely different posting: never collapse the two
        # into one row -- and don't append it either, matching how the id-collision
        # case has always treated a sibling listing.
        self._setup([_linkedin_save(TITLE, OLD_DESC, location="New York, NY")],
                    [_gh_job(TITLE, NEW_DESC, location="Austin, TX")])
        roles, log, _ = self._run()
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual(r["url"], LI_URL)                 # untouched
        self.assertEqual(r["location"], "New York, NY")
        self.assertEqual(r["fullDescription"], OLD_DESC)
        self.assertNotIn("mergedCrossSource", log["counts"])

    def test_different_job_at_the_same_company_still_added(self):
        self._setup([_linkedin_save(TITLE, OLD_DESC)],
                    [_gh_job("Solutions Architect", NEW_DESC, jid=7)])
        roles, _, _ = self._run()
        self.assertEqual(len(roles), 2)
        self.assertEqual({r["title"] for r in roles}, {TITLE, "Solutions Architect"})

    def test_two_feeds_in_one_run_yield_one_row(self):
        # Nothing stored yet: the ATS sweep and the inbox both carry this posting in
        # the same batch, under different ids and urls.
        self._setup([], [_gh_job(TITLE, NEW_DESC)],
                    inbox=[{"id": "li-acme-x", "company": "Acme", "title": TITLE,
                            "url": LI_URL, "source": "linkedin",
                            "location": "Remote - US", "fullDescription": NEW_DESC}])
        roles, log, _ = self._run()
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["id"], pipeline.slugify("Acme", TITLE))
        self.assertEqual(log["counts"]["qualified"], 1)


if __name__ == "__main__":
    unittest.main()
