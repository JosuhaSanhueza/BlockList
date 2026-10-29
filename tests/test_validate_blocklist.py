from validate_blocklist import check_line


class TestCheckLine:
    def test_valid_rule_no_errors(self):
        errors, domain = check_line("||poki.com^", 1, set())
        assert errors == []
        assert domain == "poki.com"

    def test_blank_and_comment_lines_ignored(self):
        errors, domain = check_line("", 1, set())
        assert errors == [] and domain is None

        errors, domain = check_line("# comentario", 1, set())
        assert errors == [] and domain is None

    def test_invalid_syntax_missing_prefix(self):
        errors, domain = check_line("poki.com^", 1, set())
        assert len(errors) == 1
        assert domain is None

    def test_invalid_syntax_missing_suffix(self):
        errors, domain = check_line("||poki.com", 1, set())
        assert len(errors) == 1
        assert domain is None

    def test_duplicate_domain_detected(self):
        seen = {"poki.com"}
        errors, domain = check_line("||poki.com^", 2, seen)
        assert any("duplicado" in e for e in errors)

    def test_whitelisted_domain_flagged_critical(self):
        errors, domain = check_line("||google.com^", 1, set())
        assert any("CRÍTICO" in e for e in errors)

    def test_whitelisted_subdomain_flagged_critical(self):
        errors, domain = check_line("||mail.google.com^", 1, set())
        assert any("CRÍTICO" in e for e in errors)

    def test_invalid_domain_format_flagged(self):
        errors, domain = check_line("||not a domain!^", 1, set())
        assert any("Formato de dominio no válido" in e for e in errors)

    def test_path_rule_rejected(self):
        # El DNS no ve rutas: una regla así no bloquea nada.
        for rule in ("||sites.google.com/view/game/*$document", "||sites.google.com/view/classroom6x/*^"):
            errors, domain = check_line(rule, 1, set())
            assert len(errors) == 1 and "ruta" in errors[0]
            assert domain is None

    def test_path_rule_without_prefix_rejected(self):
        errors, domain = check_line("sites.google.com/view/game/*$document", 1, set())
        assert len(errors) == 1

    def test_www_prefix_rejected(self):
        errors, domain = check_line("||www.friv2010.com^", 1, set())
        assert any("www." in e for e in errors)
        assert domain == "www.friv2010.com"


def test_rejects_infrastructure_and_whole_hostings():
    from validate_blocklist import check_line
    # Hosting/CDN completo: se bloquea por subdominio.
    for rule in ("||github.io^", "||cloudfront.net^", "||vercel.app^"):
        errors, _ = check_line(rule, 1, set())
        assert errors and "compartido" in errors[0], rule
    assert check_line("||juego.github.io^", 1, set())[0] == []
    # Infraestructura protegida.
    for rule in ("||msauth.net^", "||aadcdn.msauth.net^", "||sentry.io^"):
        assert check_line(rule, 1, set())[0], rule


def test_fastly_services():
    from validate_blocklist import check_line
    # El servicio de Fastly se bloquea con cualquiera de sus dos nombres...
    for rule in ("||slope.global.ssl.fastly.net^", "||slope.freetls.fastly.net^"):
        assert check_line(rule, 1, set())[0] == [], rule
    # ...pero nunca el sufijo entero ni la infraestructura de Fastly.
    for rule in ("||global.ssl.fastly.net^", "||freetls.fastly.net^", "||fastly.net^",
                 "||reddit.map.fastly.net^", "||t.sni.global.fastly.net^",
                 "||a.b.global.ssl.fastly.net^"):
        assert check_line(rule, 1, set())[0], rule


def test_popular_sites_need_explicit_approval():
    from validate_blocklist import check_line
    errors, _ = check_line("||office.com^", 1, set())
    assert errors and "top 10.000" in errors[0]
    # Aprobado explícitamente como sitio de juegos.
    assert check_line("||poki.com^", 1, set())[0] == []


def test_www_only_domains():
    from validate_blocklist import check_line
    # msn.com no se bloquea completo (servicios de Windows): sí www.msn.com.
    assert check_line("||www.msn.com^", 1, set())[0] == []
    assert check_line("||www.friv.com^", 1, set())[0]
