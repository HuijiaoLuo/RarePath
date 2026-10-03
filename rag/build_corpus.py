#!/usr/bin/env python3
"""Build a deterministic, provenance-preserving RAG corpus.

The first RAG milestone intentionally uses only the committed normalized CSV
files and project documentation. The output is JSONL so it can be inspected,
diffed, and replaced by a vector index later without changing source data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable


CSV_FILES = (
    "diseases.csv",
    "genes.csv",
    "proteins.csv",
    "variants.csv",
    "studies.csv",
)


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def csv_documents(processed_dir: Path) -> Iterable[dict[str, object]]:
    repo_root = processed_dir.parent.parent
    for filename in CSV_FILES:
        path = processed_dir / filename
        if not path.exists():
            continue
        source_type = path.stem
        relative_path = path.relative_to(repo_root).as_posix()
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            for row_number, row in enumerate(reader, start=2):
                fields = [
                    f"{key}: {value}"
                    for key, value in row.items()
                    if value not in (None, "")
                ]
                text = "\n".join(fields)
                source_url = str(row.get("source_url") or "")
                yield {
                    "doc_id": f"CSV:{source_type}:{row_number}",
                    "kind": "structured_record",
                    "source_type": source_type,
                    "source_path": relative_path,
                    "source_url": source_url,
                    "source_tier": "1" if source_url else "internal",
                    "source_locator": f"{relative_path}#row={row_number}",
                    "text": text,
                }


def markdown_documents(docs_dir: Path, chunk_chars: int) -> Iterable[dict[str, object]]:
    repo_root = docs_dir.parent
    for path in sorted(docs_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(repo_root).as_posix()
        # Keep headings with the following text so each chunk remains useful
        # when shown as evidence in the UI.
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        current = ""
        chunk_number = 0
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > chunk_chars:
                chunk_number += 1
                yield {
                    "doc_id": f"MD:{path.stem}:{chunk_number}",
                    "kind": "project_document",
                    "source_type": "markdown",
                    "source_path": relative_path,
                    "source_url": "",
                    "source_tier": "internal",
                    "source_locator": f"{relative_path}#chunk={chunk_number}",
                    "text": current,
                }
                current = ""
            current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunk_number += 1
            yield {
                "doc_id": f"MD:{path.stem}:{chunk_number}",
                "kind": "project_document",
                "source_type": "markdown",
                    "source_path": relative_path,
                "source_url": "",
                "source_tier": "internal",
                    "source_locator": f"{relative_path}#chunk={chunk_number}",
                "text": current,
            }


def normalize_document(document: dict[str, object]) -> dict[str, object]:
    text = str(document["text"])
    document = {**document, "content_hash": stable_id(text)}
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RarePath JSONL RAG corpus.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="data/derived/rag/corpus.jsonl")
    parser.add_argument("--chunk-chars", type=int, default=1800)
    args = parser.parse_args()
    if args.chunk_chars < 200:
        parser.error("--chunk-chars must be at least 200")

    repo_root = Path(args.repo_root).resolve()
    documents = list(csv_documents(repo_root / "data" / "processed"))
    documents.extend(markdown_documents(repo_root / "docs", args.chunk_chars))
    documents = [normalize_document(document) for document in documents]
    documents.sort(key=lambda document: str(document["doc_id"]))

    output = (repo_root / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for document in documents:
            stream.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")

    print(f"Wrote {len(documents)} documents to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
