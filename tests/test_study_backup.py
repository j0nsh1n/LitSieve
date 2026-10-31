from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import laya_client, study_backup, study_type


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    study_type._clear_laya_cache_for_tests()
    monkeypatch.delenv("LITSIEVE_STUDY_BACKUP", raising=False)
    monkeypatch.delenv("LITSIEVE_LAYA_URL", raising=False)
    yield
    study_type._clear_laya_cache_for_tests()


def paper():
    articles = [
        {
            "title": "A paper about education",
            "abstract": "This paper examines learning and reports results across many schools and students. "
            * 2,
        }
    ]
    study_type.attach_study_types(articles)
    return articles


def test_frozen_probabilities_and_no_pickle():
    fixture = Path(__file__).parent / "fixtures/study_backup_equivalence.npz"
    model = Path(__file__).parent.parent / "app/content/study_type_backup.npz"
    with np.load(model, allow_pickle=False) as data:
        for key in data.files:
            assert not data[key].dtype.hasobject
    with np.load(fixture, allow_pickle=False) as data:
        texts = data["texts"].tolist()
        _, text = study_backup.probabilities(texts)
        _, blend = study_backup.probabilities(texts, data["embeddings"])
        np.testing.assert_allclose(text, data["text_expected"], rtol=0, atol=1e-6)
        np.testing.assert_allclose(blend, data["blend_expected"], rtol=0, atol=1e-6)


def test_disabled_by_default(monkeypatch):
    articles = paper()
    before = [dict(a) for a in articles]
    monkeypatch.setattr(study_backup, "classify", lambda *args: pytest.fail("backup called"))
    assert study_type.refine_study_types_with_laya(articles) == 0
    assert articles == before


def test_backup_only_when_laya_has_no_answer(monkeypatch):
    monkeypatch.setenv("LITSIEVE_STUDY_BACKUP", "true")
    monkeypatch.setenv("LITSIEVE_LAYA_URL", "http://localhost")
    calls = []
    monkeypatch.setattr(
        study_backup, "classify", lambda texts, model: calls.append(model) or [("survey", 0.7)]
    )
    monkeypatch.setattr(laya_client, "choice", lambda *args: [{"choice": "trial", "p": 0.5}])
    articles = paper()
    assert study_type.refine_study_types_with_laya(articles) == 0
    assert not calls
    study_type._clear_laya_cache_for_tests()
    monkeypatch.setattr(laya_client, "choice", lambda *args: None)
    assert study_type.refine_study_types_with_laya(articles) == 1
    assert articles[0]["study_type_source"] == "backup"
    assert calls == [None]
    assert not study_type._cache


def test_only_cached_general_encoder_and_safe_failure(monkeypatch):
    monkeypatch.setenv("LITSIEVE_STUDY_BACKUP", "true")
    seen = []
    monkeypatch.setattr(study_backup, "classify", lambda texts, model: seen.append(model) or [None])
    other = SimpleNamespace(
        model_name="pubmedbert", cached_model=lambda: pytest.fail("must not load")
    )
    study_type.refine_study_types_with_laya(paper(), other)
    encoder = object()
    general = SimpleNamespace(
        model_name="general",
        cached_model=lambda: encoder,
        resolve_model_path=lambda _: "sentence-transformers/all-MiniLM-L6-v2",
    )
    study_type.refine_study_types_with_laya(paper(), general)
    assert seen == [None, encoder]
    monkeypatch.setattr(study_backup, "classify", lambda *args: 1 / 0)
    articles = paper()
    before = [dict(a) for a in articles]
    assert study_type.refine_study_types_with_laya(articles, general) == 0
    assert articles == before


def test_failed_batch_uses_backup_only_for_uncached_papers(monkeypatch):
    monkeypatch.setenv("LITSIEVE_STUDY_BACKUP", "true")
    monkeypatch.setenv("LITSIEVE_LAYA_URL", "http://localhost")
    cached = paper()[0]
    missing = paper()[0]
    missing["title"] = "A different study about education"
    study_type._cache[study_type._cache_key(cached)] = ("trial", 0.9)
    seen = []
    monkeypatch.setattr(laya_client, "choice", lambda *args: None)
    monkeypatch.setattr(study_backup, "classify", lambda texts, model: seen.extend(texts) or [("survey", 0.7)])
    assert study_type.refine_study_types_with_laya([cached, missing]) == 2
    assert cached["study_type_source"] == "laya"
    assert missing["study_type_source"] == "backup"
    assert len(seen) == 1 and seen[0].startswith(missing["title"])


@pytest.mark.parametrize(
    "embedding,score,expected",
    [(False, 0.6, True), (False, 0.599, False), (True, 0.4, True), (True, 0.399, False)],
)
def test_thresholds_and_none_fit(monkeypatch, embedding, score, expected):
    monkeypatch.setattr(
        study_backup,
        "probabilities",
        lambda *args: (np.array(["survey", "none_fit"]), np.array([[score, 1 - score]])),
    )
    model = SimpleNamespace(encode=lambda *args, **kwargs: np.zeros((1, 2))) if embedding else None
    result = study_backup.classify(["text"], model)
    # For the blend cut, use enough classes that the target can be top below .5.
    if embedding:
        monkeypatch.setattr(
            study_backup,
            "probabilities",
            lambda *args: (
                np.array(["survey", "none_fit", "trial"]),
                np.array([[score, (1 - score) / 2, (1 - score) / 2]]),
            ),
        )
        result = study_backup.classify(["text"], model)
    assert bool(result[0]) == expected
    monkeypatch.setattr(
        study_backup,
        "probabilities",
        lambda *args: (np.array(["survey", "none_fit"]), np.array([[0.1, 0.9]])),
    )
    assert study_backup.classify(["text"], model) == [None]
