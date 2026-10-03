#!/usr/bin/env python3
"""Extract reviewable candidate entities and edges from retrieved evidence.

This script is deliberately a staging step. It never writes to Neo4j and it
requires every material claim to point to one of the retrieved document IDs.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from rag.retrieve import load_documents, search


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "candidate_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "label": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "assertion_level": {"type": "string"},
                },
                "required": ["candidate_id", "kind", "label", "aliases", "assertion_level"],
            },
        },
        "candidate_edges": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_id": {"type": "string"},
                    "edge_type": {"type": "string"},
                    "target_id": {"type": "string"},
                    "claim": {"type": "string"},
                    "evidence_id": {"type": "string"},
                    "confidence": {"type": "string"},
                    "source_span": {"type": "string"},
                },
                "required": [
                    "source_id",
                    "edge_type",
                    "target_id",
                    "claim",
                    "evidence_id",
                    "confidence",
                    "source_span",
                ],
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["candidate_entities", "candidate_edges", "uncertainties", "conflicts"],
}


SYSTEM_PROMPT = """You extract biomedical research candidates from supplied evidence.
Use only the evidence included in the user message. Do not use outside knowledge.
Every candidate edge must use an evidence_id that exactly matches a supplied
document ID and must include a short verbatim source_span from that document.
If evidence is insufficient, return an empty array and explain the uncertainty.
Use provisional candidate IDs such as CANDIDATE:<label> when no stable ID is
present. Do not give diagnoses, treatment recommendations, or efficacy claims.
"""


def evidence_prompt(query: str, results: list[dict[str, Any]]) -> str:
    blocks = []
    for result in results:
        blocks.append(
            "\n".join(
                [
                    f"DOCUMENT_ID: {result['doc_id']}",
                    f"SOURCE: {result.get('source_url') or result.get('source_path')}",
                    f"TEXT:\n{result.get('text', '')}",
                ]
            )
        )
    return f"Query: {query}\n\nRetrieved evidence:\n\n" + "\n\n---\n\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract reviewable RAG candidates with OpenAI.")
    parser.add_argument("--corpus", default="data/derived/rag/corpus.jsonl")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", default="data/derived/rag/candidates.json")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5"))
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")

    documents = load_documents(Path(args.corpus))
    results = search(documents, args.query, args.top_k)
    client = OpenAI()
    response = client.responses.create(
        model=args.model,
        store=False,
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": evidence_prompt(args.query, results)}],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "rarepath_candidates",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )

    payload = json.loads(response.output_text)
    payload["metadata"] = {
        "query": args.query,
        "model": args.model,
        "retrieved_doc_ids": [result["doc_id"] for result in results],
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "review_status": "candidate",
        "neo4j_writeback": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reviewable candidates to {output}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
