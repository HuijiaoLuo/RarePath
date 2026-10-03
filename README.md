# RarePath - GM1 / GM2 Gangliosidosis Seed

This is the GitHub-ready seed package for the Rare Disease Atlas prototype.

Start with the [documentation index](docs/README.md), then use the [team overview](docs/TEAM_OVERVIEW.md), [data pipeline guide](docs/DATA_PIPELINE.md), and [evidence table](docs/SEED_EVIDENCE_TABLE.md). The planned protein layer is described in the [protein similarity integration contract](docs/PROTEIN_SIMILARITY_INTEGRATION.md).

The repository contains:

- reproducible public-data fetch and normalization code;
- disease, gene, protein, ClinVar, and ClinicalTrials.gov CSV files;
- an evidence-backed graph schema, node table, edge table, and Neo4j loader;
- a manifest for the committed data snapshot.

## Repository map

```text
docs/       project plans, evidence, and integration contracts
data/       normalized data and data-specific notes
graph/      graph CSVs, schema, loader, and graph-specific notes
pipelines/  reproducible public-data fetch scripts
```

The directory-level READMEs stay next to the data and graph files they describe. Project-wide documents live under `docs/`.

The raw Mondo, ClinVar, and ClinicalTrials.gov responses are intentionally not committed. They can be regenerated with the pipeline and are excluded by .gitignore.

## Rebuild the seed data

From the repository root:

~~~bash
python pipelines/fetch_seed_data.py
~~~

The pipeline writes new raw snapshots under data/raw/ and normalized files under data/processed/. Review the generated manifest before committing a refreshed curated snapshot.

## Important data boundary

This repository contains public aggregate research data only. It is a research-navigation prototype, not a diagnostic or treatment recommendation system. Study recruitment status and eligibility must be refreshed from the official ClinicalTrials.gov record before being shown to users.
