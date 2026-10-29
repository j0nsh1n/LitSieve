"""Listed-open copy from stored fields: access_state rules."""

from __future__ import annotations

import pytest

from app.services.access import NONE_LISTED, OPEN_LISTED, access_public_dict, access_state


def _info(**kwargs):
    article = {
        "source": kwargs.pop("source", "openalex"),
        "oa_status": kwargs.pop("oa_status", None),
        "best_oa_url": kwargs.pop("best_oa_url", None),
    }
    extra = kwargs.pop("extra", None)
    locations = kwargs.pop("locations", None)
    if extra is not None:
        article["_extra"] = extra
    if locations is not None:
        article["locations"] = locations
    article.update(kwargs)
    return access_state(article)


@pytest.mark.parametrize("status", ["gold", "green", "hybrid", "bronze", "diamond", "Gold"])
def test_openalex_open_status_with_url_is_open_listed(status):
    info = _info(oa_status=status, best_oa_url="https://example.org/paper.pdf")
    assert info.state == OPEN_LISTED
    assert info.url == "https://example.org/paper.pdf"
    assert info.sources == ("OpenAlex",)


def test_openalex_closed_with_url_is_none_listed():
    info = _info(oa_status="closed", best_oa_url="https://example.org/paper.pdf")
    assert info.state == NONE_LISTED
    assert info.url is None


def test_openalex_diamond_counts_as_open():
    info = _info(oa_status="diamond", best_oa_url="http://example.org/oa")
    assert info.state == OPEN_LISTED
    assert info.url == "http://example.org/oa"


@pytest.mark.parametrize("status", ["OPEN", "Open", "open"])
def test_openaire_open_mixed_case_needs_a_url(status):
    listed = _info(
        source="openaire", oa_status=status, best_oa_url="https://example.org/oa",
    )
    assert listed.state == OPEN_LISTED
    missing = _info(source="openaire", oa_status=status)
    assert missing.state == NONE_LISTED
    assert missing.sources == ("OpenAIRE",)


@pytest.mark.parametrize("status", ["CLOSED", "embargo", "RESTRICTED", "Embargo"])
def test_openaire_non_open_access_is_none_listed(status):
    info = _info(
        source="openaire", oa_status=status, best_oa_url="https://example.org/oa",
    )
    assert info.state == NONE_LISTED


def test_doaj_fulltext_location_counts_as_open():
    info = _info(
        source="doaj",
        oa_status=None,
        locations=[{"url": "https://example.org/full.pdf", "kind": "fulltext", "via": "doaj"}],
    )
    assert info.state == OPEN_LISTED
    assert info.url == "https://example.org/full.pdf"
    assert info.sources == ("DOAJ",)


def test_hal_file_stored_as_green_with_url_is_open():
    info = _info(
        source="hal",
        oa_status="green",
        best_oa_url="https://hal.science/hal-1/document",
        locations=[{
            "url": "https://hal.science/hal-1/document", "kind": "file", "via": "hal",
        }],
    )
    assert info.state == OPEN_LISTED
    assert info.url.endswith("/document")


def test_hal_notice_without_file_is_none_listed():
    info = _info(source="hal", oa_status=None, best_oa_url=None, locations=[])
    assert info.state == NONE_LISTED
    assert info.sources == ("HAL",)


def test_zenodo_open_files_are_open_listed():
    info = _info(
        source="zenodo",
        oa_status="green",
        best_oa_url="https://zenodo.org/api/records/1/files/a.pdf",
        locations=[{
            "url": "https://zenodo.org/api/records/1/files/a.pdf",
            "kind": "file",
            "via": "zenodo",
        }],
    )
    assert info.state == OPEN_LISTED


def test_zenodo_restricted_is_none_listed():
    info = _info(source="zenodo", oa_status=None, best_oa_url=None)
    assert info.state == NONE_LISTED
    assert info.sources == ("Zenodo",)


def test_crossref_link_without_licence_never_counts():
    info = _info(
        source="crossref",
        oa_status=None,
        best_oa_url=None,
        locations=[{
            "url": "https://api.elsevier.com/content/article/doi/10?via=crossref",
            "kind": "text-mining",
            "via": "crossref",
        }],
    )
    assert info.state == NONE_LISTED
    assert info.url is None
    assert info.sources == ("CrossRef",)


@pytest.mark.parametrize("license", [
    "https://creativecommons.org/licenses/by/4.0/",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en",
    "https://creativecommons.org/licenses/by/3.0/us/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
])
def test_crossref_link_with_cc_licence_counts(license):
    info = _info(
        source="crossref",
        locations=[{
            "url": "https://example.org/cc.pdf",
            "via": "crossref",
            "license": license,
        }],
    )
    assert info.state == OPEN_LISTED
    assert info.url == "https://example.org/cc.pdf"


@pytest.mark.parametrize("license", [
    "https://notcreativecommons.org/restricted",
    "https://creativecommons.org/",
    "https://example.org/?q=creativecommons.org",
    "see creativecommons.org for details",
    "https://creativecommons.org/licenses/not-a-license/4.0/",
    "https://creativecommons.org/licenses/by/99.99/",
])
def test_crossref_non_licence_text_does_not_count(license):
    info = _info(
        source="crossref",
        locations=[{
            "url": "https://example.org/cc.pdf",
            "via": "crossref",
            "license": license,
        }],
    )
    assert info.state == NONE_LISTED
    assert info.url is None


def test_crossref_bibliographic_licence_is_not_an_entry_licence():
    info = _info(
        source="crossref",
        locations=[{
            "url": "https://api.elsevier.com/content/article/doi/10",
            "via": "crossref",
        }],
        biblio='{"license":"https://creativecommons.org/licenses/by/4.0/"}',
    )
    assert info.state == NONE_LISTED


def test_open_status_without_url_is_none_listed():
    info = _info(oa_status="gold", best_oa_url=None, locations=[])
    assert info.state == NONE_LISTED
    assert info.url is None


def test_missing_and_unknown_status_are_none_listed():
    assert _info(oa_status=None, best_oa_url="https://example.org/x").state == NONE_LISTED
    assert _info(oa_status="", best_oa_url="https://example.org/x").state == NONE_LISTED
    assert _info(oa_status="unknown", best_oa_url="https://example.org/x").state == NONE_LISTED
    assert _info().state == NONE_LISTED


def test_non_http_url_does_not_count():
    info = _info(oa_status="gold", best_oa_url="ftp://example.org/paper.pdf")
    assert info.state == NONE_LISTED
    assert _info(oa_status="gold", best_oa_url="javascript:alert(1)").state == NONE_LISTED
    assert _info(oa_status="gold", best_oa_url="/paper.pdf").state == NONE_LISTED
    assert _info(oa_status="gold", best_oa_url="https://").state == NONE_LISTED


@pytest.mark.parametrize("url", [
    "https:///paper.pdf",
    "https://not a host/paper",
])
def test_malformed_http_url_in_best_oa_url_is_none_listed(url):
    info = _info(oa_status="gold", best_oa_url=url)
    assert info.state == NONE_LISTED
    assert info.url is None


@pytest.mark.parametrize("url", [
    "https:///paper.pdf",
    "https://not a host/paper",
])
def test_malformed_http_url_in_locations_is_none_listed(url):
    info = _info(
        source="doaj",
        locations=[{"url": url, "kind": "fulltext", "via": "doaj"}],
    )
    assert info.state == NONE_LISTED
    assert info.url is None


def test_valid_http_and_https_urls_count():
    https_best = _info(oa_status="gold", best_oa_url="https://example.org/paper.pdf")
    assert https_best.state == OPEN_LISTED
    assert https_best.url == "https://example.org/paper.pdf"
    http_best = _info(oa_status="gold", best_oa_url="http://example.org/oa")
    assert http_best.state == OPEN_LISTED
    assert http_best.url == "http://example.org/oa"
    https_loc = _info(
        source="doaj",
        locations=[{"url": "https://example.org/full.pdf", "kind": "fulltext", "via": "doaj"}],
    )
    assert https_loc.state == OPEN_LISTED
    assert https_loc.url == "https://example.org/full.pdf"
    http_loc = _info(
        source="doaj",
        locations=[{"url": "http://example.org/full.pdf", "kind": "fulltext", "via": "doaj"}],
    )
    assert http_loc.state == OPEN_LISTED
    assert http_loc.url == "http://example.org/full.pdf"


def test_legacy_null_fields_are_none_listed():
    info = access_state({
        "source": "pubmed",
        "oa_status": None,
        "best_oa_url": None,
    })
    assert info.state == NONE_LISTED
    assert info.sources == ("PubMed",)


@pytest.mark.parametrize("locations", [
    "not-json",
    12,
    {"url": "https://example.org/x"},
    [{"url": None}],
    [{"url": 1}],
    [None, "x", {"url": "https://example.org/x", "via": "crossref"}],
])
def test_malformed_locations_never_raise(locations):
    info = _info(oa_status="gold", best_oa_url=None, locations=locations)
    assert info.state == NONE_LISTED
    assert info.url is None


def test_odd_article_shapes_never_raise():
    assert access_state(None).state == NONE_LISTED
    assert access_state("paper").state == NONE_LISTED
    assert access_state([]).state == NONE_LISTED
    assert access_state({"oa_status": {"nested": True}, "best_oa_url": 3}).state == NONE_LISTED
    assert access_state({"_extra": "nope", "source": "openalex"}).state == NONE_LISTED


def test_crossref_keyed_row_uses_merged_openalex_url():
    info = _info(
        source="crossref",
        oa_status="gold",
        best_oa_url="https://openalex.org/oa.pdf",
        locations=[{
            "url": "https://api.elsevier.com/content/article/doi/10",
            "via": "crossref",
        }],
    )
    assert info.state == OPEN_LISTED
    assert info.url == "https://openalex.org/oa.pdf"


def test_access_public_dict_omits_url_when_none_listed():
    none = access_public_dict(_info(source="pubmed"))
    assert none == {"state": NONE_LISTED, "sources": ["PubMed"]}
    listed = access_public_dict(_info(
        oa_status="gold", best_oa_url="https://example.org/oa.pdf",
    ))
    assert listed["state"] == OPEN_LISTED
    assert listed["url"] == "https://example.org/oa.pdf"


def test_empty_source_omits_names():
    info = access_state({})
    assert info.state == NONE_LISTED
    assert info.sources == ()


def test_merged_location_via_adds_source_names():
    info = _info(
        source="openalex",
        oa_status="green",
        best_oa_url="https://example.org/oa.pdf",
        locations=[
            {"url": "https://example.org/oa.pdf", "via": "openalex"},
            {"url": "https://api.elsevier.com/x", "via": "crossref"},
        ],
    )
    assert info.state == OPEN_LISTED
    assert info.sources == ("OpenAlex", "CrossRef")


def test_closed_merged_locations_keep_source_names():
    info = _info(
        source="openalex",
        oa_status="closed",
        locations=[
            {"url": "https://openalex.org/work", "via": "openalex"},
            {"url": "https://api.elsevier.com/x", "via": "crossref"},
        ],
    )
    assert info.state == NONE_LISTED
    assert info.url is None
    assert info.sources == ("OpenAlex", "CrossRef")
    assert access_public_dict(info) == {
        "state": NONE_LISTED,
        "sources": ["OpenAlex", "CrossRef"],
    }
