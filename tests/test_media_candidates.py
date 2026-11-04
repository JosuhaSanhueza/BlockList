import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from media_candidates import NAME, classify  # noqa: E402


def test_classify():
    assert classify("Hentai Porno Videos", "") == "hentai"
    assert classify("Ver Anime Online Gratis", "") == "anime"
    assert classify("Leer manga en español", "") == "anime"
    assert classify("hentaitruyen.fun — Buy this expired domain", "") is None
    assert classify("Anime Casino en línea", "") is None
    assert classify("Noticias del colegio", "") is None


def test_names_of_the_topic():
    assert NAME.search("animeflv.net")
    assert NAME.search("hentaila.com")
    assert not NAME.search("wikipedia.org")
