#!/usr/bin/env python3
"""Run transparent BM25 retrieval over the RarePath JSONL corpus."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_:.+\-]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def load_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line.strip():
                try:
                    documents.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSONL at {path}:{line_number}") from error
    if not documents:
        raise ValueError(f"Corpus is empty: {path}")
    return documents


def search(documents: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    tokenized = [tokenize(str(document.get("text", ""))) for document in documents]
    bm25 = BM25Okapi(tokenized)
    query_tokens = tokenize(query)
    scores = bm25.get_scores(query_tokens)

    ranked = sorted(
        range(len(documents)),
        key=lambda index: (float(scores[index]), str(documents[index].get("doc_id", ""))),
        reverse=True,
    )
    results = []
    for rank, index in enumerate(ranked[:top_k], start=1):
        document = documents[index]
        results.append(
            {
                "rank": rank,
                "score": round(float(scores[index]), 4),
                "doc_id": document.get("doc_id"),
                "kind": document.get("kind"),
                "source_type": document.get("source_type"),
                "source_path": document.get("source_path"),
                "source_url": document.get("source_url"),
                "source_locator": document.get("source_locator"),
                "source_tier": document.get("source_tier"),
                "content_hash": document.get("content_hash"),
                "text": document.get("text"),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieve evidence from the RarePath corpus.")
    parser.add_argument("--corpus", default="data/derived/rag/corpus.jsonl")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")

    documents = load_documents(Path(args.corpus))
    payload = {"query": args.query, "results": search(documents, args.query, args.top_k)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
