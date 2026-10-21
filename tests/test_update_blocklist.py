from update_blocklist import get_root_domain, clean_domain, generate_keyword_variations, WHITELIST


class TestGetRootDomain:
    def test_simple_domain_unchanged(self):
        assert get_root_domain("poki.com") == "poki.com"

    def test_subdomain_consolidates_to_apex(self):
        assert get_root_domain("www.poki.com") == "poki.com"
        assert get_root_domain("a.b.poki.com") == "poki.com"

    def test_shared_hosting_platform_not_consolidated(self):
        # Subdominios de plataformas compartidas deben conservarse tal cual,
        # de lo contrario bloqueamos github.io/gitlab.io enteros.
        assert get_root_domain("66-ez.gitlab.io") == "66-ez.gitlab.io"
        assert get_root_domain("67clicker.bitbucket.io") == "67clicker.bitbucket.io"

    def test_compound_second_level_tld(self):
        # dominios tipo something.co.uk deben conservar las 3 partes
        assert get_root_domain("games.co.uk") == "games.co.uk"
        assert get_root_domain("sub.games.co.uk") == "games.co.uk"


class TestCleanDomain:
    def test_strips_scheme(self):
        assert clean_domain("https://example.com") == "example.com"
        assert clean_domain("http://example.com") == "example.com"

    def test_strips_www(self):
        assert clean_domain("www.example.com") == "example.com"

    def test_strips_path_and_port(self):
        assert clean_domain("example.com/path/to/page") == "example.com"
        assert clean_domain("example.com:8080") == "example.com"

    def test_lowercases(self):
        assert clean_domain("EXAMPLE.COM") == "example.com"


class TestGenerateKeywordVariations:
    def test_includes_original_keyword(self):
        assert "minecraft" in generate_keyword_variations("minecraft")

    def test_hyphen_variations(self):
        variations = generate_keyword_variations("mc-servers")
        assert "mc servers" in variations
        assert "mcservers" in variations

    def test_no_empty_variations(self):
        for kw in ["minecraft", "mc-servers", "juegos-gratis", "unblocked-games"]:
            for v in generate_keyword_variations(kw):
                assert v.strip() != ""


class TestWhitelist:
    def test_critical_infrastructure_present(self):
        # Nunca se debe romper accidentalmente la whitelist quitando estos dominios,
        # o el update_blocklist podría empezar a bloquear buscadores/redes sociales.
        for domain in ("google.com", "github.com", "youtube.com"):
            assert domain in WHITELIST

    def test_no_game_site_in_whitelist(self):
        game_sites = ("poki.com", "crazygames.com", "y8.com", "friv.com")
        for domain in game_sites:
            assert domain not in WHITELIST


def test_get_root_domain_shared_suffixes():
    # it.com, us.com, eu.org... son compartidos: se conserva el subdominio.
    assert get_root_domain("classroom.it.com") == "classroom.it.com"
    assert get_root_domain("www.juego.us.com") == "juego.us.com"
    assert get_root_domain("mess.eu.org") == "mess.eu.org"
    assert get_root_domain("sub.poki.com") == "poki.com"


def test_registrable_shared_suffixes():
    from scripts.adguard_review import registrable
    assert registrable("classroom.it.com") == "classroom.it.com"
    assert registrable("a.b.juego.br.com") == "juego.br.com"


def test_validate_rejects_shared_suffix():
    from validate_blocklist import check_line
    errors, _ = check_line("||it.com^", 1, set())
    assert errors and "compartido" in errors[0]
    errors, _ = check_line("||classroom.it.com^", 1, set())
    assert errors == []


def test_game_signals_distributor_sdk():
    from update_blocklist import game_signals
    html = '<script src="https://html5.api.gamedistribution.com/main.min.js"></script>'
    assert game_signals(html)["sdks"] == ["gamedistribution"]
    assert game_signals('<script src="//game-cdn.poki.com/scripts/v2/poki-sdk.js"></script>')["sdks"] == ["poki"]
    assert game_signals("<p>Just a recipe blog</p>") == {"sdks": [], "engines": [], "game_links": 0, "non_game": False}


def test_game_signals_engines_and_links():
    from update_blocklist import game_signals
    html = ('<script src="Build/WebGL.loader.js"></script><script>createUnityInstance(c)</script>'
            '<a href="/game/slope/">Slope</a><a href="/games/retro-bowl/">Retro Bowl</a>'
            '<script src="https://unpkg.com/@ruffle-rs/ruffle"></script>')
    sig = game_signals(html)
    assert "unity" in sig["engines"] and "ruffle" in sig["engines"]
    assert sig["game_links"] == 2


def test_game_signals_non_game_pages():
    from update_blocklist import game_signals
    assert game_signals("<h1>Play slots for real money - 200 free spins</h1>")["non_game"]
    assert game_signals("<h1>This domain is for sale</h1>")["non_game"]
    assert game_signals("<a>Download Minecraft MOD APK</a>")["non_game"]
    # Una categoría "Casino games" en un portal de juegos no es una página de apuestas.
    assert not game_signals('<a href="/games/casino/">Casino games</a> Solitaire')["non_game"]


def test_www_only_domains_are_kept(tmp_path, monkeypatch):
    # msn.com completo no se bloquea (servicios de Windows): la búsqueda diaria no debe
    # convertir www.msn.com ni zone.msn.com en msn.com al leer o consolidar la lista.
    import update_blocklist as ub
    assert ub.get_root_domain("www.msn.com") == "www.msn.com"
    assert ub.get_root_domain("zone.msn.com") == "zone.msn.com"
    assert ub.get_root_domain("www.friv.com") == "friv.com"

    lst = tmp_path / "GamesBlockList.txt"
    lst.write_text("||www.msn.com^\n||zone.msn.com^\n||www.poki.com^\n", encoding="utf-8")
    monkeypatch.setattr(ub, "BLOCKLIST_FILE", str(lst))
    assert ub.load_existing_domains() == {"www.msn.com", "zone.msn.com", "poki.com"}
