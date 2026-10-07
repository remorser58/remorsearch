"""Honest public-page reader and research tools for the research mode.

Standard library only. Site knowledge (official routes, mobile twins, login
hosts, search pages, terms restrictions, other AI agents' robots.txt tokens and
marker words) lives in `uxresearch/data/*.json`, never in this package's code.
"""

VERSION = "0.2.0"
RULES_VERSION = "ux-research-rules.2"
PROJECT_URL = "https://github.com/remorser58/Remorsearch_UX_QA_Skill"
ROBOTS_TOKEN = "RemorsearchUXQA"
USER_AGENT = f"{ROBOTS_TOKEN}/{VERSION} (+{PROJECT_URL}; read-only UX research)"
