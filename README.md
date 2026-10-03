# RarePath - GM1 / GM2 Gangliosidosis Seed

This is the GitHub-ready seed package for the Rare Disease Atlas prototype.

It contains:

- the reproducible public-data fetch pipeline;
- normalized disease, gene, ClinVar, and ClinicalTrials.gov CSV files;
- an evidence-backed graph schema, node table, edge table, and Neo4j loader;
- the protein-mapping and similarity integration contract for the next graph layer;
- the team overview and evidence table;
- a manifest for the committed data snapshot.

The raw Mondo, ClinVar, and ClinicalTrials.gov responses are intentionally not committed. They can be regenerated with the pipeline and are excluded by .gitignore.

## Rebuild the seed data

From this folder:

~~~bash
python pipelines/fetch_seed_data.py
~~~

The pipeline writes new raw snapshots under data/raw/ and normalized files under data/processed/. Review the generated manifest before committing a refreshed curated snapshot.

## Important data boundary

This repository contains public aggregate research data only. It is a research-navigation prototype, not a diagnostic or treatment recommendation system. Study recruitment status and eligibility must be refreshed from the official ClinicalTrials.gov record before being shown to users.
