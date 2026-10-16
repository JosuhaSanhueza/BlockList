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
