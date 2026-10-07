# RAG-to-Graph Ingestion

## Purpose

The curated Neo4j graph cannot contain every rare disease, paper, variant, study, or emerging research result. A retrieval-augmented generation (RAG) layer can discover candidate evidence outside the current snapshot and prepare it for review.

RAG must not write directly into the accepted graph. The safe path is:

```text
query
  -> entity resolution
  -> source retrieval
  -> evidence-grounded LLM extraction
  -> candidate nodes and edges
  -> validation and human review
  -> accepted Graph DB update
```

This preserves the existing rule that the model explains retrieved evidence and does not invent biomedical facts.

## When the graph has no disease

If a user searches for a disease that has no exact MONDO match:

1. Normalize the input name, synonyms, gene symbols, variants, and phenotype terms.
2. Check MONDO, Orphanet, HPO, ClinVar, UniProt, ClinicalTrials.gov, PubMed/PMC, and relevant NIH/FDA sources.
3. Retrieve documents using a hybrid keyword and vector search.
4. Ask the LLM to extract only claims supported by quoted source spans.
5. Create a provisional identifier such as `CANDIDATE:sha256:<short-hash>` rather than guessing a MONDO ID.
6. Store the candidate in a staging table or candidate graph.
7. Resolve identity, duplicates, conflicts, and source quality.
8. Let a reviewer accept, reject, or request more evidence.
9. Only then create a stable disease node or attach an accepted edge to the graph.

The candidate status must be visible to the UI. A missing database record is a reason to retrieve and review evidence, not permission to treat an LLM answer as an ontology fact.

## Source tiers

Use a source hierarchy so that retrieval quality is explicit:

| Tier | Sources | Automatic graph write-back |
| --- | --- | --- |
| 1 | MONDO, HPO, ClinVar, UniProt, ClinicalTrials.gov, PubMed/PMC, NIH, FDA, EMA | Only after schema and identity validation |
| 2 | Orphanet, specialist registries, institutional rare-disease centers, patient organizations | Candidate evidence; human review required |
| 3 | Preprints, conference pages, general web pages, search snippets | Discovery only; never promote automatically |

Store the URL, retrieval time, document hash, source tier, license/usage note, and the exact text span used for every extracted claim.

## RAG components

### Entity resolver

Resolve disease names, gene symbols, UniProt accessions, variants, NCT IDs, HPO terms, and organization names before retrieval. The resolver should return:

```json
{
  "input": "example disease name",
  "normalized_terms": ["..."],
  "matched_ids": [],
  "match_status": "unresolved",
  "next_queries": ["..."],
  "confidence": "low"
}
```

Never ask the LLM to invent a stable identifier. If identity is unresolved, keep the candidate provisional.

### Retriever

Use hybrid retrieval:

- exact and synonym keyword search for IDs, gene symbols, and NCT numbers;
- BM25 or equivalent lexical search for rare names and variants;
- embeddings for paraphrases and phenotype descriptions;
- source and date filters so a current study status is not replaced by an old page.

Keep the original documents and chunks outside Neo4j. Neo4j should store document metadata and evidence links, not become a dump of full PDFs.

### Structured extraction

The LLM should return a strict JSON object, not prose-only output:

```json
{
  "candidate_entities": [
    {
      "candidate_id": "CANDIDATE:...",
      "kind": "Disease",
      "label": "...",
      "aliases": ["..."],
      "gene_symbols": ["..."],
      "assertion_level": "extracted"
    }
  ],
  "candidate_edges": [
    {
      "source_id": "CANDIDATE:...",
      "edge_type": "ASSOCIATED_WITH",
      "target_id": "GENE_SYMBOL:...",
      "claim": "...",
      "evidence_id": "RAG-EVIDENCE:...",
      "confidence": "medium",
      "source_span": "..."
    }
  ],
  "uncertainties": ["..."],
  "conflicts": ["..."]
}
```

The extraction prompt must require a source span for each claim and allow `unknown`, `unresolved`, and `conflict` values.

### Candidate staging

Use a separate candidate namespace before acceptance:

```text
(Candidate)-[:EXTRACTED_FROM]->(SourceDocument)
(Candidate)-[:PROPOSES]->(CandidateEdge)
(CandidateEdge)-[:SUPPORTED_BY]->(Evidence)
(Candidate)-[:DUPLICATE_OF]->(Entity)
(Candidate)-[:CONFLICTS_WITH]->(Entity)
```

Candidate fields should include:

```text
candidate_id, kind, label, aliases, source_url, source_tier,
retrieved_at, document_hash, model_name, prompt_version,
review_status, reviewer, reviewed_at, rejection_reason
```

Recommended review states are `candidate`, `needs_identity_review`, `needs_evidence_review`, `accepted`, `rejected`, and `superseded`.

## Write-back rules

An item can move from staging to the accepted graph only when:

1. Its identity is resolved or explicitly marked as a stable local provisional entity.
2. Every material edge has an evidence ID, source URL, retrieval date, and source span.
3. The source tier and confidence are recorded.
4. Duplicate and conflicting claims have been reviewed.
5. The reviewer confirms that the claim is not a treatment recommendation or an unsupported disease equivalence.

Accepted graph writes should be append-only or versioned. Never silently overwrite a curated claim with an LLM extraction.

## RAG and research hypotheses

The RAG layer may create a `R&D_HYPOTHESIS` candidate from accepted evidence, for example:

```text
candidate disease -> candidate mechanism -> possible target/modality
                  -> biomarker or endpoint -> relevant study or collaborator
```

The hypothesis must retain its supporting documents and list the next experiment. It should be labeled as a research lead, not as an efficacy claim or clinical advice.

## Evaluation

Build a small reviewed evaluation set from the current GM1/GM2 evidence table and several deliberately missing diseases. Track:

- entity-resolution accuracy;
- retrieval recall@k;
- citation precision;
- claim-level extraction precision;
- duplicate and conflict detection;
- reviewer acceptance rate;
- unsupported-claim rate.

The most important safety metric is unsupported-claim rate. A system that returns fewer candidates with good provenance is preferable to one that fills the graph with plausible but unverified edges.

## Data and privacy boundaries

- Do not send identifiable patient data to a general LLM during the first RAG prototype.
- Do not put raw PDFs, full transcripts, or private contact details into Neo4j unless the access policy explicitly allows it.
- Keep source documents, chunks, embeddings, extraction outputs, review decisions, and graph IDs versioned separately.
- Record the model name, model version, prompt version, retrieval timestamp, and source snapshot for every extraction.

## MVP implementation order

1. Build an offline RAG corpus from the original project brief (not committed), the curated evidence table, and the public source snapshots.
2. Implement entity resolution and source-tier metadata.
3. Extract candidates into JSON and validate them without writing Neo4j.
4. Add a candidate review page with source spans and accept/reject actions.
5. Write only accepted candidates into Neo4j with `review_status=accepted`.
6. Add R&D hypothesis cards and UI explanations after the candidate pipeline is measurable.

