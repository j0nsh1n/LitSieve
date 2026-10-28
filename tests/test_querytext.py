"""Query punctuation must stay literal or disappear before a provider request."""

import pytest

from app.fetchers.base import FetchError, HttpClient
from app.fetchers.plos import PLOSFetcher
from app.fetchers.querytext import lucene_safe, solr_safe


@pytest.mark.parametrize("char", list('?*~^/\\:[]{}<>!&|') + ["&&", "||"])
def test_lucene_disabled_character_matrix(char):
    assert lucene_safe(f"heart{char}disease") == "heart disease"


@pytest.mark.parametrize("char", list('+-!{}[]^~*?:\\/|&=<>') + ["&&", "||"])
def test_solr_reserved_character_matrix(char):
    expected = "".join("\\" + part for part in char)
    assert solr_safe(f"heart{char}disease") == f"heart{expected}disease"


@pytest.mark.parametrize("safe", [lucene_safe, solr_safe])
@pytest.mark.parametrize(
    "text,expected",
    [
        ('"heart disease" AND (mice OR rats) NOT children',
         '"heart disease" AND (mice OR rats) NOT children'),
        ('"heart disease', 'heart disease'),
        ('"heart disease" AND "mice', '"heart disease" AND mice'),
        ('((heart OR disease)', '(heart OR disease)'),
        ('heart) OR (disease', 'heart OR disease'),
        ('"heart (disease" OR mice', '"heart (disease" OR mice'),
        (" \t café\n心臓 123 αβ \u2003", "café 心臓 123 αβ"),
        ("heart and disease or mice not rats", "heart and disease or mice not rats"),
        ("???", ""),
        ("*:*", ""),
        ('() ""', ""),
        ("", ""),
    ],
)
def test_safe_text_preserves_words_phrases_and_balanced_groups(safe, text, expected):
    assert safe(text) == expected


@pytest.mark.parametrize("char", ["+", "-", "="])
def test_lucene_literal_signs(char):
    assert lucene_safe(f"heart{char}disease") == f"heart\\{char}disease"


@pytest.mark.parametrize("char", list('+-!{}[]^~*?:\\/|&=<>') + ["&&", "||"])
def test_plos_escapes_reserved_characters_after_tokenizing(char):
    term = "heart" + "".join("\\" + part for part in char) + "disease"
    assert PLOSFetcher.solr_query(f"heart{char}disease OR mice") == (
        f"title:({term} OR mice) OR abstract:({term} OR mice)"
    )


def test_plos_retains_tokenizer_operator_parenthesis_and_phrase_handling():
    assert PLOSFetcher.solr_query('(heart disease) OR "stem cell?" AND NOT mice') == (
        'title:(heart AND disease OR "stem cell\\?" AND NOT mice) '
        'OR abstract:(heart AND disease OR "stem cell\\?" AND NOT mice)'
    )
    assert PLOSFetcher.solr_query('"heart (disease)"') == (
        'title:("heart \\(disease\\)") OR abstract:("heart \\(disease\\)")'
    )
    assert PLOSFetcher.solr_query("???") == r"title:(\?\?\?) OR abstract:(\?\?\?)"
    assert PLOSFetcher.solr_query("") == "*:*"


def test_http_client_does_not_retry_bad_query(monkeypatch):
    http = HttpClient(delay=0)
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        raise FetchError("Unreadable query", kind="bad_query")

    monkeypatch.setattr(http.session, "request", request)
    with pytest.raises(FetchError) as caught:
        http.get("https://example.test/search")
    assert caught.value.kind == "bad_query"
    assert calls == [1]
