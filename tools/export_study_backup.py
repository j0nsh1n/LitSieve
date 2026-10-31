"""Refit the frozen study backup from the research training files."""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from scipy.sparse import hstack  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from app.services.study_backup import cues  # noqa: E402


def gold_rows(path):
    rows, seen = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        question = next(iter(row["questions"]))
        if question != "study_type":
            continue
        text = row["state"]["text"] if isinstance(row["state"], dict) else row["state"]
        if text in seen:
            continue
        seen.add(text)
        probabilities = row.get("gold", {}).get(question, {}).get("probabilities") or {}
        label = (
            "none_fit"
            if probabilities and max(probabilities.values()) - min(probabilities.values()) < 1e-6
            else row["expected"][question]
        )
        rows.append((text, label))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        type=Path,
        default=Path.home() / "HealthDatabaseAccess-scratch/laya-ft/data-multi3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "app/content/study_type_backup.npz",
    )
    args = parser.parse_args()
    rows = gold_rows(args.data / "train_b.jsonl") + gold_rows(args.data / "val_study.jsonl")
    if len(rows) != 374:
        raise ValueError(f"Expected 374 training rows, got {len(rows)}")
    texts, labels = zip(*rows)
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        stop_words="english",
        max_features=20000,
        max_df=0.9,
    )
    features = hstack([vectorizer.fit_transform(texts), cues(texts)]).tocsr()
    text_model = LogisticRegression(C=3, max_iter=3000, class_weight="balanced").fit(
        features, labels
    )
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
    embeddings = encoder.encode(texts, batch_size=32, normalize_embeddings=True)
    embed_model = LogisticRegression(C=10, max_iter=3000, class_weight="balanced").fit(
        embeddings, labels
    )
    if not np.array_equal(text_model.classes_, embed_model.classes_):
        raise ValueError("Class order differs")
    vocabulary = np.asarray(vectorizer.get_feature_names_out(), dtype=str)
    np.savez_compressed(
        args.output,
        vocabulary=vocabulary,
        idf=vectorizer.idf_,
        classes=text_model.classes_,
        text_coef=text_model.coef_,
        text_intercept=text_model.intercept_,
        embed_coef=embed_model.coef_,
        embed_intercept=embed_model.intercept_,
    )
    print(f"{args.output}: {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
