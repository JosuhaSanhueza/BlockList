import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from validate_media_lists import MEDIA_LISTS, check_domain, check_file  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_lists_are_valid():
    seen = set()
    for name in MEDIA_LISTS:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            assert check_file(f.readlines(), seen) == [], name


def test_approved_sites_are_allowed():
    for domain in ("jkanime.net", "crunchyroll.com", "mangadex.org"):
        assert check_domain(domain) is None, domain


def test_protected_and_shared_are_rejected():
    for domain in ("google.com", "github.io", "pixiv.net", "comic-walker.com", "janitorai.com"):
        assert check_domain(domain), domain


def test_duplicates_between_lists_are_rejected():
    seen = set()
    assert check_file(["||jkanime.net^"], seen) == []
    assert check_file(["||jkanime.net^"], seen) != []
