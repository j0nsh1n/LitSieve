"""Public /learn guides: the two that set expectations about scope.

"Finish your research" and "Citation quality" are the pages that tell students
this app is a starting point and that appraisal here is deliberately weak (no
clinical evidence grades), so their content is asserted, not just their status
code.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.content.feature_guides import FEATURE_ORDER, get_guide, list_guides
from app.main import app


def test_finish_research_and_citation_guides():
    assert "finish-your-research" in FEATURE_ORDER
    assert "citation-quality" in FEATURE_ORDER
    fin = get_guide("finish-your-research")
    cit = get_guide("citation-quality")
    assert fin and cit
    assert "school library" in (fin["summary"] + " ".join(fin["how_it_works"])).lower()
    assert "google scholar" in " ".join(fin["how_it_works"]).lower()
    assert fin.get("checklists")
    assert cit.get("checklists")
    titles = " ".join(b["title"] for b in cit["checklists"]).lower()
    assert "citation" in titles
    assert "appraisal" in titles or "signal" in titles
    # Weak appraisal must not claim clinical grades.
    body = " ".join(
        " ".join(b.get("checks") or []) + " " + (b.get("intro") or "")
        for b in cit["checklists"]
    ).lower()
    assert "not" in body and ("a–d" in body or "a-d" in body or "clinical" in body)

    client = TestClient(app)
    for slug in ("finish-your-research", "citation-quality"):
        r = client.get(f"/learn/{slug}")
        assert r.status_code == 200, slug
        assert get_guide(slug)["title"].split()[0] in r.text or get_guide(slug)["title"] in r.text
        assert "checklist" in r.text.lower() or "peer-reviewed" in r.text.lower()

    landing = client.get("/")
    assert landing.status_code == 200
    assert "/learn/finish-your-research" in landing.text
    assert "/learn/citation-quality" in landing.text


def test_list_guides_includes_scope_guides():
    slugs = [g["slug"] for g in list_guides()]
    assert "finish-your-research" in slugs
    assert "citation-quality" in slugs
