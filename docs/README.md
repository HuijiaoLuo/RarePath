# Documentation

Start with the [README](../README.md) or the case-study page (`demo/index.html`). Code-specific notes live next to their code in `data/` and `graph/`.

## Method and results

1. [Disease similarity](CLUSTER_EXPANSION.md): mechanism (Reactome) and symptom (HPO) scoring, comparison sets, relation classes, clustering, the 23 known-biology checks and the v0.4 review finding.
2. [The 10× case](TEN_X_CASE.md): the milestone, today's timeline compared with the RarePath route, sources and assumptions.
3. [Gene, protein and variant layer](GENE_AND_VARIANT_LAYER.md): UniProt summaries, AlphaFold models and ClinVar variants in the gene panel.
4. [Protein similarity](PROTEIN_SIMILARITY_PORTFOLIO.md): sequence alignment with E-values and AlphaFold structure comparison for the GM1/GM2 genes.
5. [Seed evidence table](SEED_EVIDENCE_TABLE.md): the curated GM1/GM2 claims and their provenance.

## Data and graph

6. [Seed data pipeline](DATA_PIPELINE.md): how to regenerate the public-data snapshot.
7. [Graph schema](../graph/schema.md).
8. [RAG-to-graph ingestion](RAG_GRAPH_INGESTION.md): how candidate diseases and links are found and reviewed before entering the graph.

## Design notes and ideas

9. [Protein similarity integration](PROTEIN_SIMILARITY_INTEGRATION.md): the Gene → Protein → Similar Protein layer.
10. [Protein model selection](PROTEIN_MODEL_SELECTION.md): sequence, embedding, structure, phenotype and pathway methods considered.
11. [Ecosystem roadmap](ECOSYSTEM_ROADMAP.md): collaboration, patient data and ultra-rare disease workflows.

## Presenting

12. [1-minute walkthrough](DEMO_SCRIPT.md): the tested click path and voice-over.
13. [Release checklist](RELEASE_CHECKLIST.md): rebuild, test and publish a consistent version.
14. [Architecture](ARCHITECTURE.md): the evidence graph, the LLM and user data as three separate layers, what static and API modes support, and the path to a hosted service.
15. [Demo candidate](DEMO_CANDIDATE.md): freezing a build with its graph version, results and file checksums.
16. [User test protocol](USER_TEST_PROTOCOL.md): four tasks and the three misreadings to check, with a record sheet.

Earlier planning notes from the project's first version are kept in [archive/](archive/).
