"""Title filtering, salary/description rules, scoring tiers, and URL/normalize."""
import unittest

import _fixtures  # noqa: F401  (path setup + fixtures)
from _fixtures import make_profile
import pipeline


class TitleDecisionTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def _ok(self, title):
        return pipeline.title_decision(title, self.p)[0]

    def test_program_manager_included(self):
        self.assertTrue(self._ok("Technical Program Manager"))
        self.assertTrue(self._ok("Senior Technical Program Manager"))

    def test_solutions_engineer_included(self):
        self.assertTrue(self._ok("Solutions Engineer"))

    def test_project_manager_included_as_secondary(self):
        self.assertTrue(self._ok("Technical Project Manager"))
        self.assertTrue(self._ok("Senior Technical Project Manager"))

    def test_plain_project_manager_excluded(self):
        self.assertFalse(self._ok("Project Manager"))
        self.assertFalse(self._ok("IT Project Manager"))

    def test_sales_titles_excluded(self):
        self.assertFalse(self._ok("Account Executive"))
        self.assertFalse(self._ok("Account Executive, Enterprise"))

    def test_people_leadership_excluded(self):
        self.assertFalse(self._ok("Director of Engineering"))
        self.assertFalse(self._ok("VP of Platform"))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def _score(self, title, desc="", domain="", tags=None, skill_match=None):
        role = {"title": title, "fullDescription": desc, "domain": domain, "tags": tags or []}
        if skill_match is not None:
            role["skillMatch"] = skill_match
        return pipeline.score(role, self.p)

    # Unassessed roles (no skillMatch) use the neutral fit baseline (70).
    def test_program_manager_tier(self):
        # Weights rebalanced 2026-06-11 (title 0.55->0.45, fit 0.35->0.45): an unassessed
        # target-title role floors lower so a confident skill-match drives ranking more.
        self.assertEqual(self._score("Technical Program Manager")[0], 78)
        self.assertEqual(self._score("Senior Technical Program Manager")[0], 80)

    def test_project_manager_ranks_below_program_manager(self):
        prog = self._score("Technical Program Manager")[0]
        proj = self._score("Technical Project Manager")[0]
        self.assertLess(proj, prog)

    def test_priority_domain_bonus_and_flag(self):
        pct, is_priority = self._score("Solutions Engineer", desc="Kubernetes platform infrastructure role")
        self.assertTrue(is_priority)
        self.assertGreaterEqual(pct, 80)

    def test_fit_drives_score(self):
        # Same title/domain; the skill match (matched vs gaps) should move the score a lot.
        # Fit confidence now scales with JD length, so a real assessment carries a real JD.
        jd = "We are hiring a Solutions Engineer for our platform team. " * 12
        good = self._score("Solutions Engineer", desc=jd,
                           skill_match={"matched": ["a", "b", "c", "d", "e", "f", "g", "h"], "gaps": ["x"]})[0]
        poor = self._score("Solutions Engineer", desc=jd,
                           skill_match={"matched": [], "gaps": ["x", "y", "z", "w"]})[0]
        self.assertGreater(good, poor)
        self.assertGreater(good - poor, 15)  # fit is a meaningful share of the score

    def test_zero_matched_role_drops_below_neutral(self):
        # A title-strong role with an all-gaps assessment must rank below the same
        # role left unassessed (neutral baseline) -- this is the Amplitude bug fix.
        neutral = self._score("Solutions Engineer")[0]
        all_gaps = self._score("Solutions Engineer",
                               skill_match={"matched": [], "gaps": ["a", "b", "c", "d"]})[0]
        self.assertLess(all_gaps, neutral)

    def test_people_management_penalty_lowers_score(self):
        base = self._score("Technical Program Manager")[0]
        penalized = self._score("Technical Program Manager", desc="You will manage a team of engineers.")[0]
        self.assertLess(penalized, base)

    def test_experience_penalty_when_role_wants_more_years(self):
        base = self._score("Technical Program Manager")[0]
        penalized = self._score("Technical Program Manager", desc="Requires 25 years of experience.")[0]
        self.assertLess(penalized, base)

    def test_score_bounds(self):
        for title in ("Technical Program Manager", "Technical Project Manager", "Solutions Engineer"):
            pct = self._score(title)[0]
            self.assertGreaterEqual(pct, 0)
            self.assertLessEqual(pct, 100)


class SalaryRuleTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()  # salaryTarget 150000

    def test_target_within_range_ok(self):
        ok, _ = pipeline.salary_ok({"salaryMin": 130000, "salaryMax": 175000}, self.p)
        self.assertTrue(ok)

    def test_range_below_target_skipped(self):
        ok, reason = pipeline.salary_ok({"salaryMin": 100000, "salaryMax": 140000}, self.p)
        self.assertFalse(ok)
        self.assertIn("salaryTooLow", reason)

    def test_unknown_salary_qualifies(self):
        self.assertTrue(pipeline.salary_ok({"salaryMin": None, "salaryMax": None}, self.p)[0])

    def test_target_equals_max_ok(self):
        self.assertTrue(pipeline.salary_ok({"salaryMin": 120000, "salaryMax": 150000}, self.p)[0])


class DescriptionSkipTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def test_quota_heavy_sales_skipped(self):
        role = {"title": "Account Manager",
                "fullDescription": "Carry a quota and hit your sales quota; close deals every quarter."}
        ok, reason = pipeline.description_ok(role, self.p)
        self.assertFalse(ok)
        self.assertIn("descriptionSkip", reason)

    def test_presales_se_with_quota_words_kept(self):
        role = {"title": "Solutions Engineer",
                "fullDescription": "Partner with sales; you may carry a quota and help close deals on demos."}
        self.assertTrue(pipeline.description_ok(role, self.p)[0])

    def test_no_skips_configured_passes(self):
        p = make_profile()
        p["matching"]["descriptionSkips"] = []
        role = {"title": "X", "fullDescription": "carry a quota; close deals; commission"}
        self.assertTrue(pipeline.description_ok(role, p)[0])


class EmployerRuleTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def test_skip_employer(self):
        self.assertFalse(pipeline.employer_ok("Recruiter Aggregator Inc", self.p))

    def test_normal_employer_ok(self):
        self.assertTrue(pipeline.employer_ok("Anthropic", self.p))


class UrlAndNormalizeTests(unittest.TestCase):
    def test_classify_ats_url(self):
        src, ats = pipeline.classify_urls("https://job-boards.greenhouse.io/acme/jobs/123")
        self.assertEqual(src, "")
        self.assertTrue(ats.endswith("/123"))

    def test_classify_source_url(self):
        src, ats = pipeline.classify_urls("https://www.linkedin.com/jobs/view/999")
        self.assertEqual(ats, "")
        self.assertIn("linkedin", src)

    def test_slugify(self):
        self.assertEqual(pipeline.slugify("Acme Corp", "Senior TPM!"), "acme-corp-senior-tpm")

    def test_normalize_builds_role_schema(self):
        raw = {"title": "Solutions Engineer", "company": "Acme",
               "url": "https://job-boards.greenhouse.io/acme/jobs/5",
               "location": "Remote - US", "description": "Build things."}
        role = pipeline.normalize(raw, "greenhouse")
        self.assertEqual(role["company"], "Acme")
        self.assertEqual(role["atsUrl"], raw["url"])
        self.assertEqual(role["sourceUrl"], "")
        self.assertEqual(role["remoteStatus"], "remote")
        self.assertTrue(role["id"])  # slug generated


if __name__ == "__main__":
    unittest.main()
