import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import hunt_sources  # noqa: E402
from update_blocklist import hunt_candidate_ok  # noqa: E402


def test_host():
    assert hunt_sources._host("https://www.Juegos.com/x") == "juegos.com"
    assert hunt_sources._host("juegos.com") == "juegos.com"
    assert hunt_sources._host("") == ""


def test_duck_clone():
    assert hunt_sources.is_duck_clone("<title>duck</title><meta content='Study with Quizlet'>")
    assert not hunt_sources.is_duck_clone("<title>Duck Life</title> Quizlet")
    assert not hunt_sources.is_duck_clone("<title>duck</title>")


def test_gambling_is_skipped():
    for d in ("casinoonlineseguro.com", "admiralbet.es", "lagunatoto-1.pages.dev", "pinoqq-akses.pages.dev",
              "games-slot-online.pages.dev", "biru77-panen-jackpot.pages.dev"):
        assert not hunt_candidate_ok(d, "urlscan"), d


def test_free_hostings_need_a_game_name():
    assert hunt_candidate_ok("retrobowlunblocked.pages.dev", "urlscan")
    assert not hunt_candidate_ok("dentalpimentel.pages.dev", "urlscan")
    assert not hunt_candidate_ok("agreed-blue-k0kgbsmb.edgeone.dev", "urlscan")


def test_github_needs_a_game_name():
    assert not hunt_candidate_ok("joachimford.uk", "GitHub")
    assert hunt_candidate_ok("ovo-games.github.io", "GitHub")
    assert hunt_candidate_ok("arcadebloom.com", "urlscan")


def test_ip_names_are_skipped():
    assert not hunt_candidate_ok("k3p4jbcg.198.251.83.251.sslip.io", "urlscan")


def test_spam_pages_and_hosting_names():
    assert not hunt_candidate_ok("best-roblox-games-horror-reddit.pages.dev", "urlscan")
    assert not hunt_candidate_ok("juliangdeveloper.github.io", "urlscan")
    assert not hunt_candidate_ok("gremlin-child-studios.my.canva.site", "urlscan")
    assert hunt_candidate_ok("unblocked-games.my.canva.site", "urlscan")


def test_short_names_need_word_boundaries():
    assert not hunt_candidate_ok("vivacious-red-itzf520j-dpn59chiy80k.edgeone.dev", "urlscan")
    assert hunt_candidate_ok("y8-games.pages.dev", "urlscan")
