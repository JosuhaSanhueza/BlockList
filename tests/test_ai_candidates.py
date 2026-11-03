import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from ai_candidates import classify, extract_domains, is_covered, page_summary  # noqa: E402


def test_extract_domains_from_readme_and_list():
    text = "[a](https://www.newchat.ai/x) [b](https://github.com/foo)\nother-tool.com\n# comentario"
    assert extract_domains(text) == {"newchat.ai", "other-tool.com"}


def test_is_covered_by_parent_domain():
    known = {"chatgpt.com"}
    assert is_covered("chatgpt.com", known)
    assert is_covered("sora.chatgpt.com", known)
    assert not is_covered("notchatgpt.com", known)


def test_classify():
    assert classify("Luvr AI - Your AI girlfriend", "") == "companion"
    assert classify("Free AI Homework Helper", "") == "tool"
    assert classify("Free ChatGPT online", "") == "tool"
    assert classify("Hospital San Juan", "Atención médica") is None


def test_page_summary():
    body = '<title> Chat &amp; AI </title><meta name="description" content="Ask AI">'
    assert page_summary(body) == ("Chat & AI", "Ask AI")
