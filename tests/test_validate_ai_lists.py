import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from validate_ai_lists import AI_LISTS, check_domain, check_file  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_lists_are_valid():
    seen = set()
    for name in AI_LISTS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            assert check_file(f.readlines(), seen) == [], name


def test_ai_sites_are_allowed():
    for domain in ("chatgpt.com", "gemini.google.com", "copilot.cloud.microsoft", "janitorai.com"):
        assert check_domain(domain) is None, domain


def test_infrastructure_and_school_tools_are_rejected():
    for domain in ("google.com", "m365.cloud.microsoft", "docs.google.com", "github.io",
                   "grammarly.com", "canva.com", "gptzero.me", "googleapis.com"):
        assert check_domain(domain), domain


def test_duplicates_between_lists_are_rejected():
    seen = set()
    assert check_file(["||chatgpt.com^"], seen) == []
    assert check_file(["||chatgpt.com^"], seen) != []


def test_bad_syntax_is_rejected():
    assert check_file(["chatgpt.com"], set()) != []
    assert check_file(["||chatgpt.com/foo^"], set()) != []
