"""Canonical type mappings, DOI shape, and biblio JSON."""

import json

import pytest

from app.services.work_types import (
    TYPE_MAP,
    WORK_TYPES,
    biblio_json,
    build_biblio,
    canonical_work_type,
    normalize_doi,
    provider_type_label,
    trim_openalex,
)

MAPPING_ROWS = [
    (provider, raw, canonical)
    for provider, table in TYPE_MAP.items()
    for raw, canonical in table.items()
]


@pytest.mark.parametrize("provider, raw, expected", MAPPING_ROWS)
def test_every_mapping_row(provider, raw, expected):
    assert expected in WORK_TYPES
    assert canonical_work_type(provider, raw) == expected
    assert canonical_work_type(provider.upper(), raw.upper()) == expected


@pytest.mark.parametrize("provider, raw", [
    ("openalex", None),
    ("openalex", ""),
    ("openalex", "   "),
    ("openalex", "paratext"),
    ("openalex", "editorial"),
    ("openalex", "grant"),
    ("crossref", "peer-review"),
    ("crossref", "component"),
    ("doaj", "book"),
    ("pubmed", "journal-article"),
])
def test_unknown_or_absent_raw_type_is_unknown(provider, raw):
    assert canonical_work_type(provider, raw) == "unknown"


def test_provider_type_keeps_the_raw_value():
    assert provider_type_label("openalex", "book-chapter") == "openalex:book-chapter"
    assert provider_type_label("crossref", None) is None
    assert provider_type_label("", "book") == "book"


@pytest.mark.parametrize("raw, expected", [
    ("10.1234/Ab.CD", "10.1234/ab.cd"),
    ("https://doi.org/10.1234/Ab.CD", "10.1234/ab.cd"),
    ("http://dx.doi.org/10.1016/j.sleh.2025.07.003", "10.1016/j.sleh.2025.07.003"),
    ("doi:10.3735/9781935306627.book-part-157", "10.3735/9781935306627.book-part-157"),
    ("  10.4324/9780203309506  ", "10.4324/9780203309506"),
])
def test_normalize_doi_accepts_bare_and_url_forms(raw, expected):
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "not-a-doi", "10.123", "10.1234", "10.1234/", "doi:foo",
    "https://example.org/10.1234/abc", "10.1234/abc def",
])
def test_normalize_doi_rejects_invalid_values(raw):
    assert normalize_doi(raw) is None


def test_biblio_omits_empty_keys():
    assert build_biblio(publisher="  ", volume=None, isbn=[], editors=[""]) is None
    body = build_biblio(
        publisher="Duke",
        volume="2",
        issue="",
        pages="85-110",
        isbn=["9780822325833", "9780822325833"],
        editors=["Rachel Jacoff"],
        parent_book_id="https://openalex.org/W1",
    )
    assert body == {
        "publisher": "Duke",
        "volume": "2",
        "pages": "85-110",
        "isbn": ["9780822325833"],
        "editors": ["Rachel Jacoff"],
        "parent_book_id": "https://openalex.org/W1",
    }
    assert "issue" not in body
    dumped = biblio_json(body)
    assert json.loads(dumped) == body
    assert dumped.startswith("{")


def test_trim_openalex_drops_the_inverted_abstract():
    trimmed = trim_openalex({
        "id": "https://openalex.org/W1",
        "abstract_inverted_index": {"Hello": [0]},
        "referenced_works": ["https://openalex.org/W2"],
        "concepts": [{"id": "C1"}],
        "authorships": [{"author": {"display_name": "Ada"}, "author_position": "first"}],
        "open_access": {"oa_status": "closed", "is_oa": False},
    })
    assert "abstract_inverted_index" not in trimmed
    assert "referenced_works" not in trimmed
    assert "concepts" not in trimmed
    assert trimmed["authors"] == [{"name": "Ada", "orcid": None, "position": "first"}]
