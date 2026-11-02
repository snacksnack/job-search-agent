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

    # Manager-of-team titles must lose even when they contain an always-include
    # substring ("Senior Manager, Sales Engineering" contains "Sales Engineer").
    def test_manager_of_team_excluded_despite_always_include(self):
        ok, reason = pipeline.title_decision(
            "Senior Manager, Sales Engineering - Majors, NY/NJ", self.p)
        self.assertFalse(ok)
        self.assertIn("people-leadership", reason)
        self.assertFalse(self._ok("Sales Engineering Manager"))
        self.assertFalse(self._ok("Manager of Solutions Engineering, East"))

    def test_ic_manager_titles_survive_leadership_overrides(self):
        self.assertTrue(self._ok("Technical Program Manager, Infrastructure"))
        self.assertTrue(self._ok("Sales Engineer"))
        self.assertTrue(self._ok("Senior Solutions Engineer"))

    # "Program Manager, <team>" embeds the "Manager, <team>" leadership shape
    # but is IC — the program/project/product prefix guard must let it through.
    def test_program_manager_of_team_is_not_leadership(self):
        self.assertTrue(self._ok("Program Manager, Sales Engineering"))
        ok, reason = pipeline.title_decision(
            "Technical Program Manager, Sales Engineering", self.p)
        self.assertTrue(ok)

    # Deliberately greedy on the Program Management family: Manager-of-TPM-org
    # titles are not in the override list — the user hides misses manually
    # rather than risk filtering out a match.
    def test_manager_of_program_management_org_included(self):
        self.assertTrue(self._ok("Senior Manager, Technical Program Management"))


class HyphenatedTitleTests(unittest.TestCase):
    """RC1-588: title matching is substring-based, so a hyphen was enough to lose
    a primary target title. "Forward-Deployed Engineer" was rejected as
    titleMismatch, and 5 distinct spellings appear in the rejects history."""

    def setUp(self):
        self.p = make_profile()

    def test_hyphenated_target_titles_included(self):
        for t in ["Forward-Deployed Engineer", "Senior Forward-Deployed Engineer, Federal",
                  "Forward-Deployed  Engineer", "Forward/Deployed Engineer"]:
            self.assertTrue(pipeline.title_decision(t, self.p)[0], t)

    def test_hyphenated_and_spaced_titles_score_the_same(self):
        """The filter and the scorer have to agree, or a rescued title clears the
        cascade and then scores at the no-signal floor."""
        role = lambda t: {"title": t, "fullDescription": "", "tags": []}
        self.assertEqual(pipeline.score(role("Forward-Deployed Engineer"), self.p),
                         pipeline.score(role("Forward Deployed Engineer"), self.p))

    def test_hyphenated_configured_phrases_still_match(self):
        """Normalization is applied to both sides. A phrase carrying its own
        hyphen -- "Manager - Sales Engineering" in leadershipOverrideTitles --
        would be unmatchable if only the incoming title were normalized, letting
        a people-manager role through."""
        self.p["matching"]["leadershipOverrideTitles"] = ["Manager - Sales Engineering"]
        for t in ["Manager - Sales Engineering", "Manager -Sales Engineering",
                  "Manager  -  Sales Engineering"]:
            ok, reason = pipeline.title_decision(t, self.p)
            self.assertFalse(ok, t)
            self.assertIn("people-leadership", reason)

    def test_ic_manager_guard_survives_normalization(self):
        """The "Manager, <team>" override is skipped when Manager is preceded by
        Program/Project/Product, so IC titles survive. Normalizing both sides must
        not disturb that."""
        self.assertTrue(pipeline.title_decision("Program Manager, Sales Engineering",
                                                self.p)[0])
        self.assertFalse(pipeline.title_decision("Manager, Sales Engineering", self.p)[0])


class SeniorityCeilingTests(unittest.TestCase):
    """RC1-589: skipTitleRules run AFTER alwaysIncludeTitles and always-include
    matching is substring-based, so "Director, Forward Deployed Engineering" was
    admitted at 95% -- "Forward Deployed Engineering" contains the always-include
    "Forward Deployed Engineer" and the ceiling never got a look. 16 such roles
    were on the board, two of them above everything else."""

    def setUp(self):
        self.p = make_profile()      # already carries the ceiling category
        # The live profile lists a bare "Program Manager" as an adjacent include;
        # the fixture doesn't, and the rank-suffix carve-out below depends on it.
        self.p["matching"]["secondaryIncludeTitles"]["titles"].append("Program Manager")

    def _ok(self, title):
        return pipeline.title_decision(title, self.p)[0]

    def test_leadership_seats_rejected_even_when_they_contain_a_target_title(self):
        for t in ["Director, Forward Deployed Engineering",
                  "Strategic Solutions Engineering Director",
                  "Head of Solutions Engineering",
                  "VP, Head of Forward Deployed Engineering",
                  "Director, Technical Program Management",
                  "Director, Solutions Engineer Forward Deployed - Splunk"]:
            ok, reason = pipeline.title_decision(t, self.p)
            self.assertFalse(ok, t)
            self.assertIn("people-leadership", reason)

    def test_whole_word_only(self):
        """A rank term must be its own word, or "Directory Services" is a Director."""
        self.assertTrue(self._ok("Technical Program Manager, Directory Services"))

    def test_chief_of_staff_is_a_team_not_a_rank(self):
        """Live titles at 77% and 76%: the IC is a TPM, "Chief of Staff" is the org."""
        self.assertTrue(self._ok("Lead Technical Program Manager - Chief of Staff Services"))
        self.assertTrue(self._ok("Principal Technical Program Manager - Chief of Staff"))

    def test_bank_rank_suffix_is_not_an_office(self):
        """At financial firms the rank is a seniority band TRAILING an IC title.
        The third of these is a role the user saved himself, which is the check on
        the rule."""
        for t in ["XPG Technical Program Manager - Vice President",
                  "Kinexys Program Manager - Vice President",
                  "Technical Project Manager - Strategic Initiatives Office, Vice President"]:
            self.assertTrue(self._ok(t), t)

    def test_rank_leading_the_title_is_still_an_office(self):
        """The carve-out is about position: a rank that LEADS is the seat, whatever
        follows it. This one costs a real 71% role (BNY), named in the PR."""
        ok, reason = pipeline.title_decision("Senior Vice President, Forward Deployed Engineer",
                                             self.p)
        self.assertFalse(ok)
        self.assertIn("people-leadership", reason)

    def test_rank_must_be_terminal_for_the_carve_out(self):
        """A rank buried mid-title is not a trailing band."""
        self.assertFalse(self._ok("Solutions Engineer, Director of Partner Programs"))
        self.assertTrue(self._ok("Solutions Engineer - Vice President"))

    def test_target_title_must_match_as_a_whole_word(self):
        """What separates a real director seat from a bank rank: "engineering" is
        not the word "engineer", so nothing rescues this one."""
        self.assertFalse(self._ok("Solutions Engineering Director"))

    def test_ic_targets_unaffected(self):
        for t in ["Technical Program Manager", "Senior Technical Program Manager",
                  "Forward Deployed Engineer", "Solutions Engineer"]:
            self.assertTrue(self._ok(t), t)

    def test_no_ceiling_category_configured_is_a_no_op(self):
        p = make_profile()
        p["matching"]["skipTitleRules"] = [
            r for r in p["matching"]["skipTitleRules"]
            if "seniority too high" not in (r.get("category") or "").lower()]
        self.assertIsNone(pipeline._seniority_ceiling_hit("director, engineering", p))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.p = make_profile()

    def _score(self, title, desc="", domain="", tags=None, skill_match=None):
        role = {"title": title, "fullDescription": desc, "domain": domain, "tags": tags or []}
        if skill_match is not None:
            role["skillMatch"] = skill_match
        return pipeline.score(role, self.p)

    # Unassessed roles (no skillMatch) use the neutral fit baseline (50).
    def test_program_manager_tier(self):
        # Weights rebalanced 2026-06-11 (title 0.55->0.45, fit 0.35->0.45) and the neutral
        # baseline lowered 70->50 (RC1-524), so an unassessed target-title role floors lower
        # still and a confident skill-match drives ranking above the unknown-fit baseline.
        self.assertEqual(self._score("Technical Program Manager")[0], 69)
        self.assertEqual(self._score("Senior Technical Program Manager")[0], 71)

    def test_project_manager_ranks_below_program_manager(self):
        prog = self._score("Technical Program Manager")[0]
        proj = self._score("Technical Project Manager")[0]
        self.assertLess(proj, prog)

    def test_priority_domain_bonus_and_flag(self):
        pct, is_priority = self._score("Solutions Engineer", desc="Kubernetes platform infrastructure role")
        self.assertTrue(is_priority)
        # Priority domain lifts the score above the same title with no domain signal
        # (baseline-independent: W_DOMAIN carries the bonus regardless of NEUTRAL_FIT).
        plain, _ = self._score("Solutions Engineer")
        self.assertGreater(pct, plain)

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

    def test_real_assessment_ignores_jd_length(self):
        # RC1-525: a role carrying a real assessment (provenance-stamped) scores the same
        # whether or not its JD text is stored -- the JD-length penalty is only for
        # unassessed roles. LinkedIn saves are assessed in-browser but their JD often
        # isn't persisted, so an empty stored JD must not discount a genuine fit.
        sm = {"matched": ["a", "b", "c", "d", "e", "f", "g", "h"], "gaps": ["x"],
              "assessedBy": "sonnet"}
        no_jd = self._score("Solutions Engineer", desc="", skill_match=sm)[0]
        long_jd = self._score("Solutions Engineer", desc="x" * 800, skill_match=sm)[0]
        self.assertEqual(no_jd, long_jd)
        # and that full-confidence fit lifts it well clear of the neutral baseline
        self.assertGreater(no_jd, self._score("Solutions Engineer")[0])

    def test_unassessed_thin_jd_still_discounted(self):
        # The JD-length penalty still applies to a block with no assessment provenance
        # (not a real assessment): a bare matched/gaps map without assessedBy/model.
        sm = {"matched": ["a", "b", "c", "d", "e", "f"], "gaps": []}  # no provenance
        thin = self._score("Solutions Engineer", desc="", skill_match=sm)[0]
        full = self._score("Solutions Engineer", desc="x" * 800, skill_match=sm)[0]
        self.assertLess(thin, full)

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

    def test_quota_carrying_se_skipped(self):
        # Reid's hard-no: a quota-carrying role is dropped even when it is an SE/FDE.
        role = {"title": "Solutions Engineer",
                "fullDescription": "Partner with sales; you carry a quota and help close deals on demos."}
        ok, reason = pipeline.description_ok(role, self.p)
        self.assertFalse(ok)
        self.assertIn("descriptionSkip", reason)

    def test_quota_free_se_kept(self):
        # A pre-sales SE with no quota signals is still fine.
        role = {"title": "Solutions Engineer",
                "fullDescription": "Partner with customers on technical demos, POCs, and integrations."}
        self.assertTrue(pipeline.description_ok(role, self.p)[0])

    def test_no_skips_configured_passes(self):
        p = make_profile()
        p["matching"]["descriptionSkips"] = []
        role = {"title": "X", "fullDescription": "carry a quota; close deals; commission"}
        self.assertTrue(pipeline.description_ok(role, p)[0])

    def test_quota_signals_are_word_bounded(self):
        # "ote" inside "note" and product copy about the *users* closing deals
        # are not quota signals (Perchwell Senior TPM false positive, 2026-10-27).
        role = {"title": "Senior Technical Program Manager",
                "fullDescription": "A platform built for agents to close deals faster. "
                                   "Note: we only consider US-authorized candidates."}
        self.assertTrue(pipeline.description_ok(role, self.p)[0])

    def test_standalone_ote_still_counts(self):
        role = {"title": "Solutions Engineer",
                "fullDescription": "Compensation is $150K base with OTE of $220K; "
                                   "you will carry a quota from day one."}
        ok, reason = pipeline.description_ok(role, self.p)
        self.assertFalse(ok)
        self.assertIn("descriptionSkip", reason)


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
