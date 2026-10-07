# RarePath: from a rare diagnosis to the people already working on it

[![Tests](https://github.com/HuijiaoLuo/RarePath/actions/workflows/tests.yml/badge.svg)](https://github.com/HuijiaoLuo/RarePath/actions/workflows/tests.yml) **Not deployed yet:** clone the repository and open `demo/explore.html` in a browser ([how](#run-it)).

RarePath is an evidence graph and a conversational guide for rare genetic diseases. A family types the name of a disease. RarePath shows:

- which other disease communities share its biology;
- which studies and patient groups already exist;
- one concrete next step, with a checklist and a draft message.

Every link names its source. Anything RarePath computed is labelled as computed, and a disease that only *looks* similar is shown as a caution, never as a partner.

It covers 43 diseases in three families (lysosomal storage diseases, RASopathies and ciliopathies). They were chosen to test three claims: one gene can cause different diseases, different genes can disrupt the same process, and similar symptoms can have different causes.

![The RarePath guide for GM1 gangliosidosis: its three closest communities, one next step and a map of the connections](docs/img/rarepath-guide.png)

## Highlights

- **Two signals, kept apart.** Mechanism (Reactome pathway overlap of the causal genes, weighted by rarity) and symptoms (simGIC over HPO) are scored separately. The relation class then comes from predeclared gates, so "look-alike, different mechanism" is a first-class answer rather than a false positive. See the [method notes](docs/CLUSTER_EXPANSION.md).
- **Checked against known biology.** 23 checks run on every build (`pipelines/check_cluster_benchmark.py`). For the RASopathy and ciliopathy families, 12 of them were written down before their data was scored, and all 12 held on the first run.
- **A review finding, fixed at the cause.** The predictions held, but reading every new pair showed that true relatives were sometimes called look-alikes. For example, PTPN11 and RAF1 act at different steps of one cascade and share no lowest-level Reactome pathway. Scoring v0.4 adds a weak link for diseases in the same mechanism-defined MONDO class. Now only 2 pairs are labelled look-alikes, both involving counterexamples I designed: Krabbe vs Canavan, and Bardet-Biedl 1 vs Prader-Willi. The third designed counterexample, Aarskog-Scott, is not similar enough in symptoms to Noonan 1 to count as a look-alike, so it stays unlinked. The communities are unchanged ([details](docs/CLUSTER_EXPANSION.md#why-v04-a-review-finding)).
- **Stable when the data grows.** Pathway rarity and symptom percentiles are measured within each disease family. When I added two families, the original 190 lysosomal pairs stayed identical, and a unit test guards that.
- **Grounded AI answers.** The chat sends the model only numbered facts from the graph. The model must cite them, and the server deletes any citation that doesn't match a fact (`api/chat.py`, OpenAI Responses API with a strict JSON schema and `store=False`). Without the server, the page answers offline from the same facts.
- **From disease to protein.** Clicking a gene name opens a panel with:
  - the protein's UniProt function summary;
  - the diseases the gene causes in RarePath;
  - its Reactome processes;
  - a protein comparison: HEXA and HEXB are 57.4% identical (E-value 1.8 × 10⁻¹⁷⁸) and their AlphaFold models superimpose to 0.865 Å over 483 confident residues. Pairs that align too little are shown as "not evaluated", never as "different";
  - a rotatable AlphaFold model coloured by confidence, with disease-causing ClinVar missense variants placed on it. A variant is placed only when its reference amino acid matches the model's sequence.

  The viewer is a small, dependency-free canvas script. The model is labelled as a prediction, and the variant pattern as descriptive ([details](docs/GENE_AND_VARIANT_LAYER.md)).
- **An evaluation set for the chat.** 15 fixed questions (answerable, not in the graph, treatment and eligibility, look-alikes) list the facts an answer must cite and the phrases it must never use, plus 5 system cases (forged citations, graph-version mismatch, no key, Neo4j down). Its first run caught six offline answers that guessed instead of saying "RarePath does not record this"; they now abstain ([`evals/`](evals/run_chat_eval.py)).
- **Privacy by design.** Feedback is one tap on a fixed category ("the link looks wrong") about a record ID, with no free text and no identity, and it goes to a review queue, never straight into the graph. Recent diseases are remembered only in the browser. Every answer and feedback record names the graph version it came from ([architecture](docs/ARCHITECTURE.md)).
- **Reproducible data.** Downloads are reused when present, written atomically and recorded with source versions and SHA-256 checksums. The graph's source of truth is two CSV files under version control, loaded into Neo4j.

Each part of the answer opens a panel:

| Why we think so | Your next step | Gene and protein |
| --- | --- | --- |
| <img src="docs/img/evidence-panel.png" width="280" alt="Evidence panel for GM1 and GM2 gangliosidosis: reasons, what differs, and sources from Reactome, HPO and ClinicalTrials.gov"> | <img src="docs/img/next-step.png" width="280" alt="Next-step panel: compare how the PRONTO study measures progression, a checklist for an expert, and a draft email"> | <img src="docs/img/gene-panel-glb1.png" width="280" alt="Gene panel for GLB1: UniProt summary and the AlphaFold model coloured by confidence, with disease-causing ClinVar variants"> |
| Every reason, what differs, and the sources behind it | One step, what an expert must check, and a draft message | UniProt summary, AlphaFold model and ClinVar variants |

## Three stories from the data

| Family | What RarePath shows | Open locally |
| --- | --- | --- |
| Lysosomal storage | GM1 gangliosidosis's strongest neighbour is the GM2 group (a shared breakdown process and a cherry-red spot). A completed natural-history study (PRONTO, NCT05109793) already enrolled both. Reusing it instead of starting a new one could cut the time to comparable data from about 4 years to about 4 months. That is a hypothesis, with its assumptions listed for testing ([10× case](docs/TEN_X_CASE.md)). | GM1: `?focus=MONDO:0018149` |
| Ciliopathies | One gene, CEP290, appears as three diseases: Joubert syndrome 5, Senior-Loken syndrome 6 and Meckel syndrome 4. Prader-Willi syndrome shares obesity and hypogonadism with Bardet-Biedl syndrome but is flagged as a look-alike. | Joubert 5: `?focus=MONDO:0012432` |
| RASopathies | Noonan, Costello, CFC, Legius syndromes and NF1 involve different genes in one pathway, and a recruiting RASopathy biorepository (NCT04395495) covers five of them. Aarskog-Scott syndrome has a Noonan-like face but is kept apart. | Noonan 1: `?focus=MONDO:0008104` |

Studies and patient organisations for the newer families are hand-checked against their official pages, with the check date stored in [`data/curated/family_resources.csv`](data/curated/family_resources.csv).

## How it works

```mermaid
flowchart LR
  S["Public sources<br/>MONDO · HPO · Reactome · UniProt<br/>ClinicalTrials.gov · patient-group sites"] --> P["Python pipelines<br/>local-first, checksummed manifests"]
  P --> C["graph/nodes.csv + edges.csv<br/>(source of truth)"]
  C --> N[("Neo4j")]
  C --> J["demo/data/graph.js"]
  N --> A["api/server.py"]
  J --> U["RarePath guide<br/>demo/explore.html"]
  A --> U
  A -- "question + numbered facts" --> O["OpenAI Responses API"]
  O -- "answer with citations" --> A
```

| Step | Script | Output |
| --- | --- | --- |
| Fetch | `pipelines/fetch_cluster_expansion.py` | panel resolved to MONDO, HPO annotations, causal genes, Reactome pathways |
| Score and cluster | `pipelines/compute_disease_similarity.py` | pair scores, relation classes, Louvain clusters |
| Check | `pipelines/check_cluster_benchmark.py` | known-biology checks and predeclared predictions |
| Graph | `pipelines/sync_cluster_to_graph.py`, `pipelines/sync_curated_resources.py` | `graph/nodes.csv`, `graph/edges.csv` |
| Serve | `graph/load_neo4j.py`, `graph/export_graph_json.py`, `api/server.py` | Neo4j, static data file, local API |

The protein layer (`pipelines/compute_protein_similarity.py`) adds Smith-Waterman alignments with Karlin-Altschul E-values and AlphaFold structure comparisons for the GM1/GM2 genes ([notes](docs/PROTEIN_SIMILARITY_PORTFOLIO.md)).

## Run it

RarePath is not deployed yet. Open `demo/explore.html` from a local copy in any browser; it needs no install or server. Add `?focus=` and a MONDO ID to start at a disease, for example `demo/explore.html?focus=MONDO:0018149` for GM1. `demo/index.html` is the case study.

For AI answers and live Neo4j data:

```bash
python -m pip install -r requirements.txt
python api/server.py            # then open http://127.0.0.1:8000/explore.html
```

The server reads `OPENAI_API_KEY` (optionally `OPENAI_MODEL`, default `gpt-5`) and `NEO4J_*` from the environment. If either is missing, the page falls back to the exported snapshot and offline answers.

To rebuild the data:

```bash
python pipelines/fetch_seed_data.py      # Mondo, ClinVar, ClinicalTrials.gov seed (GM1/GM2)
python pipelines/build_atlas.py          # fetch (diseases, genes, AlphaFold, ClinVar) -> score -> check -> graph -> page
python graph/load_neo4j.py --load --prune
python -m unittest                       # 71 tests
```

To add a disease, add one line to `PANEL` in `pipelines/fetch_cluster_expansion.py` and re-run. Mondo is never re-downloaded unless you pass `--download-mondo`.

## Repository map

```text
demo/       case-study page (index.html), RarePath guide (explore.html, plain JavaScript and SVG), exported graph data
api/        local server: page + live Neo4j + grounded chat + feedback
graph/      graph CSVs (source of truth), schema, Neo4j loader, JSON export
pipelines/  data fetch, disease similarity, known-biology checks, graph sync, protein layer
data/       processed tables, curated resources and manifests (raw downloads are git-ignored)
rag/        corpus builder, BM25 retriever, OpenAI candidate extraction into a review queue
docs/       method notes
evals/      fixed chat questions, the facts the page sends, and the scorer
tests/      unit and end-to-end tests
```

## Further reading

- [Method: mechanism and symptom scoring, clustering, checks](docs/CLUSTER_EXPANSION.md)
- [The 10× case](docs/TEN_X_CASE.md): a hypothesis that reusing existing studies could bring comparable natural-history data in months instead of years, with the assumptions still to validate
- [Gene, protein and variant layer](docs/GENE_AND_VARIANT_LAYER.md): UniProt summaries, AlphaFold models and ClinVar variants
- [Architecture](docs/ARCHITECTURE.md): the evidence graph, the LLM and user data kept apart, and how that would grow
- [Demo candidate](docs/DEMO_CANDIDATE.md) and [user test protocol](docs/USER_TEST_PROTOCOL.md): how a build is frozen and tested with people
- [Changelog](CHANGELOG.md): what changed and why, version by version
- [Protein similarity](docs/PROTEIN_SIMILARITY_PORTFOLIO.md): sequence and structure comparison of GLB1, HEXA, HEXB and GM2A
- [Seed evidence table](docs/SEED_EVIDENCE_TABLE.md), [data pipeline](docs/DATA_PIPELINE.md) and [graph schema](graph/schema.md)
- [1-minute walkthrough](docs/DEMO_SCRIPT.md) and [all documents](docs/README.md)

## Limits

RarePath uses public, aggregate research data only. It is a research-navigation tool, not a diagnostic or treatment tool. A link between two diseases is a reason to investigate together, not evidence that a treatment transfers. The panel is hand-chosen, Reactome membership is coarse, and study status is a dated snapshot that must be checked on the live ClinicalTrials.gov record.

Built by Huijiao Luo.
