import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import multi_hunt as m  # noqa: E402


def test_shared_hosts_and_spam_are_skipped():
    assert not m.plausible("github.io")
    assert not m.plausible("best-roblox-games-horror-reddit.pages.dev")
    assert m.plausible("slope-game.pages.dev")
    assert m.plausible("igry.ru")


def test_gambling_and_ip_names_are_skipped():
    assert not m.plausible("1xbet.ru")
    assert not m.plausible("casino-online.com.br")
    assert not m.plausible("10.0.0.1.sslip.io")
    assert not m.plausible("rali777br.com")
    assert not m.plausible("389wingames.com.br")


def test_titles_that_are_not_game_sites():
    for title in ("Онлайн казино", "Apostas esportivas", "Domain for sale", "Новости игр", "Baixar jogos APK", "389win Slots Online", "Plataforma de Jogos - Bônus de R$388", "Free Online Games - A Guide", "Loading..."):
        assert m.NOT_A_GAME_SITE.search(title), title
    for title in ("Игры онлайн бесплатно", "Jogos online grátis", "Juegos de carros"):
        assert not m.NOT_A_GAME_SITE.search(title), title


def test_generated_names():
    names = set(m.generated_names(m.PROFILES["pt"]))
    assert "jogosonline.com.br" in names
    assert not any("--" in n or n.startswith("-") for n in names)


def test_covered_checks_parent_domains():
    known = {"jogos.com.br", "poki.com"}
    assert m.covered("www.poki.com", known)
    assert m.covered("jogos.com.br", known)
    assert not m.covered("igry.ru", known)
