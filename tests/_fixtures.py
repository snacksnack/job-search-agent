"""Shared test fixtures and path setup.

Importing this module puts `scripts/` and `tests/` on sys.path so the test files
can `import pipeline` / `import skill_match` / `import web_enrich` and
`from _fixtures import ...` regardless of how the suite is launched
(`python3 -m unittest discover tests` or pytest).

The profile fixture mirrors the real data/profile.json *structure* but is
self-contained, so tests don't break when the real profile is tuned.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def make_profile():
    """A minimal but representative profile matching pipeline.py's expectations."""
    return {
        "schemaVersion": 3,
        "candidate": {
            "name": "Test Candidate",
            "yearsExperience": 18,
            "resumePath": "data/resumes/test.docx",
            "technicalBackground": "Python, AWS Lambda, ClickHouse, Prometheus, Grafana, Docker.",
            "skills": {
                "languages": ["Python", "Bash"],
                "cloud": ["AWS", "Lambda", "S3"],
                "data": ["ClickHouse", "PostgreSQL"],
            },
        },
        "preferences": {
            "salaryTarget": 150000,
            "targetTitles": [
                "Technical Program Manager", "Senior Technical Program Manager",
                "Solutions Engineer", "Forward Deployed Engineer",
            ],
            "locationRule": {
                "includeRemoteScope": "US",
                "metroIncludeAnyArrangement": [
                    "New York City", "NYC", "New York, NY", "Brooklyn", "Manhattan",
                    "NY metro", "Greater New York",
                ],
                "excludeOnsiteOrHybridOutsideMetro": True,
            },
        },
        "matching": {
            "alwaysIncludeTitles": [
                "Technical Program Manager", "Senior Technical Program Manager",
                "Solutions Engineer", "Forward Deployed Engineer", "Sales Engineer",
                "Solutions Architect",
            ],
            "secondaryIncludeTitles": {
                "titles": [
                    "Technical Project Manager", "Senior Technical Project Manager",
                    "Staff Technical Project Manager", "Principal Technical Project Manager",
                ],
            },
            "skipTitleRules": [
                {"category": "Sales (non-technical)",
                 "titles": ["Account Executive", "Sales Development Representative"]},
                {"category": "Seniority too high (people-leadership)",
                 "titles": ["Director", "Head of", "VP", "Vice President", "Chief"]},
                {"category": "Product Management (pure)",
                 "titles": ["Product Manager", "Director of Product"]},
            ],
            "skipEmployers": ["Recruiter Aggregator Inc"],
            "descriptionSkips": ["quota-carrying sales role"],
            "priorityDomains": ["platform / infrastructure", "data / ML platforms"],
            "adjacentDomains": ["SaaS", "fintech / data products"],
        },
    }


def write_data_dir(tmp_path, *, profile=None, jobs=None, state=None, search=None,
                   search_log=None):
    """Create a temp data/ dir populated with the given JSON, return the Path."""
    data = Path(tmp_path) / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "profile.json").write_text(json.dumps(profile or make_profile()), encoding="utf-8")
    (data / "jobs.json").write_text(
        json.dumps(jobs or {"schemaVersion": 2, "roles": [], "meta": {}}), encoding="utf-8")
    (data / "state.json").write_text(
        json.dumps(state or {"schemaVersion": 1, "jobs": {}}), encoding="utf-8")
    (data / "search.json").write_text(
        json.dumps(search or {"schemaVersion": 2, "searches": [], "watchlist": []}), encoding="utf-8")
    (data / "search-log.json").write_text(
        json.dumps(search_log or {"schemaVersion": 1, "runs": []}), encoding="utf-8")
    return data
