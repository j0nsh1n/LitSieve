"""Type-aware RIS, BibTeX, APA and CSV exports (P1.4)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from app.fetchers.crossref import CrossRefFetcher
from app.routes import exports
from app.services.citations import (
    article_to_apa,
    article_to_bibtex,
    article_to_ris,
    citation_model,
    collection_to_apa,
    collection_to_bibtex,
    collection_to_ris,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"


def _csv_rows(text: str):
    return list(csv.reader(io.StringIO(text)))


def _article(**extra):
    row = {
        "article_id": "10.1234/sample",
        "source": "crossref",
        "title": "Sample Title",
        "abstract": "Abstract body.",
        "year": "2021",
        "authors": ["Ada Lovelace"],
        "journal": "Nature",
        "work_type": "journal-article",
    }
    row.update(extra)
    return row


def _biblio(**fields):
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


TYPE_EXPECTATIONS = {
    "journal-article": {
        "ris": ["TY  - JOUR", "JO  - Nature"],
        "bib": ["@article{", "journal = {Nature}"],
        "apa": ["*Nature*."],
        "csv_type": "journal-article",
    },
    "review-article": {
        "ris": ["TY  - JOUR", "JO  - Nature"],
        "bib": ["@article{", "journal = {Nature}"],
        "apa": ["*Nature*."],
        "csv_type": "review-article",
    },
    "book-review": {
        "ris": ["TY  - JOUR", "N1  - Book review", "JO  - Nature"],
        "bib": ["@article{", "note = {Book review}"],
        "apa": ["*Nature*."],
        "csv_type": "book-review",
    },
    "book": {
        "ris": ["TY  - BOOK", "PB  - Example Press"],
        "bib": ["@book{", "publisher = {Example Press}"],
        "apa": ["*Sample Title*.", "Example Press."],
        "csv_type": "book",
        "journal": "",
        "biblio": {"publisher": "Example Press"},
    },
    "edited-book": {
        "ris": ["TY  - EDBOOK", "ED  - Rachel Jacoff", "PB  - Cambridge"],
        "bib": ["@book{", "editor = {Rachel Jacoff}", "publisher = {Cambridge}"],
        "apa": ["Jacoff, R. (Ed.).", "*Sample Title*.", "Cambridge."],
        "csv_type": "edited-book",
        "journal": "",
        "authors": [],
        "biblio": {"publisher": "Cambridge", "editors": ["Rachel Jacoff"]},
    },
    "book-chapter": {
        "ris": ["TY  - CHAP", "T2  - Parent Book", "PB  - Example Press"],
        "bib": ["@incollection{", "booktitle = {Parent Book}"],
        "apa": ["In ", "*Parent Book*"],
        "csv_type": "book-chapter",
        "journal": "Parent Book",
        "container_title": "Parent Book",
        "biblio": {"publisher": "Example Press", "pages": "30-38"},
    },
    "reference-entry": {
        "ris": ["TY  - ENCYC", "T2  - Encyclopaedia"],
        "bib": ["@incollection{", "booktitle = {Encyclopaedia}"],
        "apa": ["In ", "*Encyclopaedia*"],
        "csv_type": "reference-entry",
        "journal": "Encyclopaedia",
        "container_title": "Encyclopaedia",
    },
    "conference-paper": {
        "ris": ["TY  - CPAPER", "T2  - Proceedings"],
        "bib": ["@inproceedings{", "booktitle = {Proceedings}"],
        "apa": ["In *Proceedings*."],
        "csv_type": "conference-paper",
        "journal": "Proceedings",
        "container_title": "Proceedings",
    },
    "dissertation": {
        "ris": ["TY  - THES"],
        "bib": ["@misc{", "note = {Dissertation}"],
        "apa": ["*Sample Title* [Dissertation]."],
        "csv_type": "dissertation",
        "journal": "",
        "provider_type": "eric:Dissertations/Theses - Masters Theses",
    },
    "report": {
        "ris": ["TY  - RPRT", "PB  - Abell Foundation"],
        "bib": ["@techreport{", "publisher = {Abell Foundation}"],
        "apa": ["*Sample Title*.", "Abell Foundation."],
        "csv_type": "report",
        "journal": "",
        "biblio": {"publisher": "Abell Foundation"},
    },
    "preprint": {
        "ris": ["TY  - MANSCPT", "N1  - Preprint"],
        "bib": ["@misc{", "note = {Preprint}"],
        "apa": ["Sample Title [Preprint]."],
        "csv_type": "preprint",
        "journal": "",
    },
    "registry-record": {
        "ris": ["TY  - GEN", "N1  - Trial registry record"],
        "bib": ["@misc{", "note = {Trial registry record}"],
        "apa": ["Sample Title."],
        "csv_type": "registry-record",
        "journal": "",
        "source": "clinicaltrials",
        "article_id": "NCT123",
    },
    "dataset": {
        "ris": ["TY  - DATA"],
        "bib": ["@misc{"],
        "apa": ["Sample Title."],
        "csv_type": "dataset",
        "journal": "",
    },
    "other": {
        "ris": ["TY  - GEN"],
        "bib": ["@misc{"],
        "apa": ["Sample Title."],
        "csv_type": "other",
        "journal": "",
    },
    "unknown": {
        "ris": ["TY  - GEN"],
        "bib": ["@misc{"],
        "apa": ["Sample Title."],
        "csv_type": "unknown",
        "journal": "Nature",
    },
}


def test_export_matrix_key_lines_per_type():
    for work_type, expect in TYPE_EXPECTATIONS.items():
        article = _article(work_type=work_type, journal=expect.get("journal", "Nature"))
        if "container_title" in expect:
            article["container_title"] = expect["container_title"]
        if "biblio" in expect:
            article["biblio"] = _biblio(**expect["biblio"])
        if "authors" in expect:
            article["authors"] = expect["authors"]
        if "provider_type" in expect:
            article["provider_type"] = expect["provider_type"]
        if "source" in expect:
            article["source"] = expect["source"]
        if "article_id" in expect:
            article["article_id"] = expect["article_id"]
        ris = article_to_ris(article)
        bib = article_to_bibtex(article)
        apa = article_to_apa(article)
        for line in expect["ris"]:
            assert line in ris, (work_type, line, ris)
        for line in expect["bib"]:
            assert line in bib, (work_type, line, bib)
        for line in expect["apa"]:
            assert line in apa, (work_type, line, apa)
        csv_body, _, _ = exports._format_ranked_export([article], "csv")
        row = _csv_rows(csv_body)[1]
        assert row[10] == expect["csv_type"], (work_type, row)
        assert "JO  - " not in ris or work_type in {
            "journal-article", "review-article", "book-review",
        }


def test_legacy_null_type_uses_journal_or_generic():
    nature = _article(journal="Nature")
    del nature["work_type"]
    nature_ris = article_to_ris(nature)
    assert "TY  - JOUR" in nature_ris
    assert "JO  - Nature" in nature_ris
    assert "@article{" in article_to_bibtex(nature)

    empty = _article(journal="")
    del empty["work_type"]
    empty_ris = article_to_ris(empty)
    assert "TY  - GEN" in empty_ris
    assert "JO  -" not in empty_ris
    assert "@misc{" in article_to_bibtex(empty)

    openaire = _article(journal="OpenAIRE")
    del openaire["work_type"]
    openaire_ris = article_to_ris(openaire)
    assert "TY  - GEN" in openaire_ris
    assert "JO  -" not in openaire_ris

    unknown = _article(work_type="unknown", journal="Nature")
    unknown_ris = article_to_ris(unknown)
    assert "TY  - GEN" in unknown_ris
    assert "JO  -" not in unknown_ris
    assert "@misc{" in article_to_bibtex(unknown)


def test_legacy_journal_row_matches_pre_type_bytes():
    article = {
        "article_id": "10.1234/ab.cd",
        "source": "crossref",
        "title": "Ocean {Warming} Trends",
        "abstract": "Seas are\nwarming rapidly.",
        "year": "2021",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "journal": "Nature Climate",
    }
    assert article_to_ris(article) == (
        "TY  - JOUR\n"
        "TI  - Ocean {Warming} Trends\n"
        "AU  - Ada Lovelace\n"
        "AU  - Grace Hopper\n"
        "PY  - 2021\n"
        "JO  - Nature Climate\n"
        "AB  - Seas are warming rapidly.\n"
        "DO  - 10.1234/ab.cd\n"
        "UR  - https://doi.org/10.1234/ab.cd\n"
        "ID  - crossref:10.1234/ab.cd\n"
        "ER  - \n"
    )
    assert article_to_bibtex(article) == (
        "@article{crossref_10_1234_ab_cd,\n"
        "  title = {{Ocean \\{Warming\\} Trends}},\n"
        "  author = {Ada Lovelace and Grace Hopper},\n"
        "  year = {2021},\n"
        "  journal = {Nature Climate},\n"
        "  doi = {10.1234/ab.cd},\n"
        "  url = {https://doi.org/10.1234/ab.cd},\n"
        "  note = {Source: crossref}\n"
        "}\n"
    )
    assert article_to_apa(article) == (
        "Lovelace, A., & Hopper, G. (2021). Ocean {Warming} Trends. "
        "*Nature Climate*. https://doi.org/10.1234/ab.cd"
    )


def test_crossref_chapter_exports_chap_incollection_and_apa_in():
    item = json.loads((FIXTURES / "crossref_chapter.json").read_text(encoding="utf-8"))
    article = CrossRefFetcher()._parse_item(item["message"]["items"][0])
    ris = article_to_ris(article)
    bib = article_to_bibtex(article)
    apa = article_to_apa(article)
    assert article["work_type"] == "book-chapter"
    assert "TY  - CHAP" in ris
    assert "T2  - Schlager Anthology of Black America" in ris
    assert "JO  -" not in ris
    assert "@incollection{" in bib
    assert "booktitle = {Schlager Anthology of Black America}" in bib
    assert "In " in apa
    assert "Schlager Anthology of Black America" in apa


def test_doi_first_ur_l2_only_open_copy_discovery_in_n1():
    article = _article(
        article_id="W4412783059",
        source="openalex",
        doi="10.1234/oa.doi",
        work_type="journal-article",
        journal="Sleep Health",
        best_oa_url="https://example.org/open.pdf",
    )
    ris = article_to_ris(article)
    bib = article_to_bibtex(article)
    assert "UR  - https://doi.org/10.1234/oa.doi" in ris
    assert "L2  - https://example.org/open.pdf" in ris
    assert "N1  - Found via openalex: https://openalex.org/W4412783059" in ris
    assert "url = {https://doi.org/10.1234/oa.doi}" in bib
    assert "Found via openalex: https://openalex.org/W4412783059" in bib

    via_crossref = _article(best_oa_url="https://api.elsevier.com/content/article/doi/10?via=crossref")
    assert "L2  -" not in article_to_ris(via_crossref)

    no_open = _article(article_id="W1", source="openalex", doi="10.1234/oa.doi")
    no_open.pop("best_oa_url", None)
    assert "L2  -" not in article_to_ris(no_open)


def test_apa_uses_doi_for_non_crossref_rows():
    article = _article(
        article_id="35946417",
        source="pubmed",
        doi="10.5664/jcsm.10224",
        work_type="journal-article",
        journal="Journal of Clinical Sleep Medicine",
    )
    apa = article_to_apa(article)
    assert "https://doi.org/10.5664/jcsm.10224" in apa
    assert "pubmed.ncbi.nlm.nih.gov" not in apa


def test_doctoral_dissertation_uses_phdthesis():
    article = _article(
        work_type="dissertation",
        journal="",
        provider_type="nasa_ads:phdthesis",
    )
    assert "@phdthesis{" in article_to_bibtex(article)
    assert "Dissertation" not in article_to_bibtex(article)
    assert "TY  - THES" in article_to_ris(article)


def test_selection_csv_keeps_visible_order_and_appends_type_columns():
    papers = [
        _article(article_id=f"10.1234/p{i}", title=f"Paper {i}", work_type="journal-article")
        for i in range(3)
    ]
    papers[0]["similarity_score"] = 0.9
    papers[2]["similarity_score"] = 0.1
    body, _, _ = exports._format_ranked_export(papers, "csv")
    rows = _csv_rows(body)
    assert rows[0][:10] == [
        "Rank", "Similarity", "Title", "Year", "Journal", "Authors",
        "Source", "ID", "Cluster ID", "Cluster Label",
    ]
    assert rows[0][-5:] == ["Type", "DOI", "Container", "Publisher", "Open copy URL"]
    assert [row[2] for row in rows[1:]] == ["Paper 0", "Paper 1", "Paper 2"]
    assert rows[1][10] == "journal-article"
    assert rows[1][11] == "10.1234/p0"


def test_csv_formula_protection_covers_new_columns():
    out = exports._library_rows_to_csv([{
        "title": "ok",
        "year": "2024",
        "journal": "J",
        "authors": ["A"],
        "source": "pubmed",
        "article_id": "1",
        "cluster_id": -1,
        "work_type": "=CMD()",
        "container_title": "@SUM(1)",
        "biblio": _biblio(publisher="+Press"),
        "best_oa_url": "-http://x.example/oa",
        "note": "plain",
    }])
    row = _csv_rows(out)[1]
    assert row[12] == "'=CMD()"
    assert row[14] == "'@SUM(1)"
    assert row[15] == "'+Press"
    assert row[16] == "'-http://x.example/oa"


def test_txt_lists_type_and_doi_when_present():
    article = _article(work_type="report", doi="10.1234/rep")
    body, _, _ = exports._format_ranked_export([article], "txt")
    assert "Type: report" in body
    assert "DOI: 10.1234/rep" in body


def test_citation_model_feeds_every_formatter():
    article = _article(
        work_type="book-chapter",
        journal="Parent Book",
        container_title="Parent Book",
        biblio=_biblio(
            publisher="Press", editors=["Ed E"], volume="2", issue="1",
            pages="7-19", isbn=["9781234567890"],
        ),
        doi="10.1234/chap",
        best_oa_url="https://example.org/chap.pdf",
    )
    model = citation_model(article)
    assert model.work_type == "book-chapter"
    assert model.ris_ty == "CHAP"
    assert model.bibtex_type == "incollection"
    assert model.container == "Parent Book"
    assert model.publisher == "Press"
    assert model.editors == ["Ed E"]
    assert model.volume == "2"
    assert model.pages == "7-19"
    assert model.isbn == "9781234567890"
    assert model.doi == "10.1234/chap"
    assert model.canonical_url == "https://doi.org/10.1234/chap"
    assert model.open_copy_url == "https://example.org/chap.pdf"
    ris = article_to_ris(article)
    assert "ED  - Ed E" in ris
    assert "VL  - 2" in ris
    assert "IS  - 1" in ris
    assert "SP  - 7" in ris
    assert "EP  - 19" in ris
    assert "SN  - 9781234567890" in ris
    bib = article_to_bibtex(article)
    assert "editor = {Ed E}" in bib
    assert "volume = {2}" in bib
    assert "number = {1}" in bib
    assert "pages = {7-19}" in bib
    assert "isbn = {9781234567890}" in bib
    assert collection_to_ris([article]).startswith("TY  - CHAP")
    assert "@incollection{" in collection_to_bibtex([article])
    assert "In Ed, E. (Ed.)" in collection_to_apa([article]) or "In " in article_to_apa(article)
