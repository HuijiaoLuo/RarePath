# Project documentation

These are project-wide documents. Code-specific instructions remain next to their code in `data/` and `graph/`.

Recommended reading order:

1. [Team overview](TEAM_OVERVIEW.md) — scope, MVP, and working assumptions.
2. [Seed data pipeline](DATA_PIPELINE.md) — how to regenerate the public-data snapshot.
3. [Seed evidence table](SEED_EVIDENCE_TABLE.md) — curated claims and provenance.
4. [Protein similarity integration](PROTEIN_SIMILARITY_INTEGRATION.md) — the proposed Gene → Protein → Similar Protein layer.
5. [Graph DB handoff](GRAPH_DB_HANDOFF.md) — schema, loading, API shape, and UI guidance for the teammate building the graph experience.
6. [Ecosystem roadmap](ECOSYSTEM_ROADMAP.md) — research insights, collaboration, patient data, and ultra-rare disease workflows.
7. [Protein model selection](PROTEIN_MODEL_SELECTION.md) — lightweight sequence, embedding, structure, phenotype, and pathway methods.
8. [RAG-to-Graph ingestion](RAG_GRAPH_INGESTION.md) — how to discover missing diseases and add only reviewed evidence to Neo4j.
