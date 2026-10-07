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
                    "source_span": {"type": "string"},
                },
                "required": [
                    "source_id",
                    "edge_type",
                    "target_id",
                    "claim",
                    "evidence_id",
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
Do not assign confidence; the application computes confidence from source tier,
record type, exact source-span matching, and relationship type.
"""


DIRECT_RELATIONS = {
    "in_gene",
    "has_variant_type",
    "has_clinical_significance",
    "has_protein_effect",
}

RELATION_CAPS = {
    # A seed/search label is weaker than an explicit condition assertion.
    "has_condition_label": 0.65,
    # Similarity and hypothesis edges remain research leads until independently
    # supported by functional, clinical, or curated disease evidence.
    "similar_to": 0.45,
    "possible_association": 0.45,
    "hypothesizes": 0.35,
}


def endpoint_fragment(value: str) -> str:
    return value.split(":", 1)[-1].strip().lower()


def score_edge(edge: dict[str, Any], documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence_id = str(edge.get("evidence_id", ""))
    document = documents.get(evidence_id)
    basis: list[str] = []
    score = 0.0
    if document is None:
        return {
            "confidence": "low",
            "confidence_score": 0.0,
            "confidence_basis": ["evidence_id_not_in_retrieved_context"],
        }

    tier = str(document.get("source_tier", "internal"))
    if tier == "1":
        score += 0.45
        basis.append("tier_1_official_source")
    elif tier == "2":
        score += 0.30
        basis.append("tier_2_specialist_source")
    else:
        score += 0.10
        basis.append("internal_or_unranked_source")

    if document.get("kind") == "structured_record":
        score += 0.25
        basis.append("structured_source_record")

    text = str(document.get("text", "")).lower()
    source_span = str(edge.get("source_span", "")).strip()
    if source_span and source_span.lower() in text:
        score += 0.20
        basis.append("exact_source_span_match")
    else:
        basis.append("source_span_not_verified")

    endpoints = " ".join(
        [endpoint_fragment(str(edge.get("source_id", ""))), endpoint_fragment(str(edge.get("target_id", "")))]
    )
    if any(fragment and fragment in text for fragment in endpoints.split()):
        score += 0.10
        basis.append("endpoint_appears_in_source")

    edge_type = str(edge.get("edge_type", ""))
    if edge_type in RELATION_CAPS:
        score = min(score, RELATION_CAPS[edge_type])
        basis.append(f"relationship_cap_{edge_type}")
    elif edge_type in DIRECT_RELATIONS:
        basis.append("direct_record_relationship")
    else:
        score = min(score, 0.55)
        basis.append("unclassified_relationship_cap")

    independent_sources = {
        str(item.get("source_url") or item.get("source_path"))
        for item in documents.values()
    }
    if len(independent_sources) < 2:
        score = min(score, 0.85)
        basis.append("single_source_context_cap")

    score = round(min(score, 1.0), 2)
    confidence = "high" if score >= 0.80 else "medium" if score >= 0.55 else "low"
    return {
        "confidence": confidence,
        "confidence_score": score,
        "confidence_basis": basis,
    }


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
    evidence_by_id = {str(result["doc_id"]): result for result in results}
    for edge in payload.get("candidate_edges", []):
        edge.update(score_edge(edge, evidence_by_id))
    payload["metadata"] = {
        "query": args.query,
        "model": args.model,
        "retrieved_doc_ids": [result["doc_id"] for result in results],
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "review_status": "candidate",
        "neo4j_writeback": False,
        "confidence_policy": {
            "version": "0.1",
            "formula": "source tier + structured-record status + exact source-span match + endpoint match, then relationship-specific and single-source caps",
            "high": ">= 0.80",
            "medium": "0.55-0.79",
            "low": "< 0.55 or unresolved evidence ID",
            "important_limit": "Sequence/protein similarity alone is capped as a low-confidence research hypothesis unless independent functional or curated disease evidence is present.",
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reviewable candidates to {output}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
