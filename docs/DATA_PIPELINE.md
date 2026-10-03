# Seed Data Pipeline

This pipeline creates a reproducible starting dataset for the GM1 / GM2 gangliosidosis prototype.

It retrieves:

1. The latest official Mondo release and records its release tag and SHA-256 checksum.
2. A bounded set of ClinVar records for GLB1, HEXA, HEXB, and GM2A.
3. The four ClinicalTrials.gov records referenced in the seed evidence table:
   - NCT05109793
   - NCT00029965
   - NCT07054515
   - NCT04470713

## Run it

The pipeline has no third-party Python dependencies.

~~~powershell
python pipelines/fetch_seed_data.py
~~~

To retrieve a smaller ClinVar sample while developing:

~~~powershell
python pipelines/fetch_seed_data.py --clinvar-max-per-gene 25
~~~

## Outputs

~~~text
data/
  raw/
    mondo/<release-tag>/release.json
    mondo/<release-tag>/mondo.json
    clinvar/<UTC-timestamp>/
    clinicaltrials/<UTC-timestamp>/
  processed/
    diseases.csv
    genes.csv
    variants.csv
    studies.csv
  manifests/
    seed_snapshot_<UTC-timestamp>.json
~~~

The manifest is the source-of-truth record for a run. It records the retrieval time, Mondo release tag, download checksum, source URLs, source query counts, and normalized output counts.

## Data-use notes

- The pipeline keeps public source snapshots for reproducibility; do not add patient-level data.
- The ClinVar pull is deliberately bounded and condition-focused. It is not a full ClinVar mirror.
- Study status and eligibility change. Refresh ClinicalTrials.gov before displaying an enrollment message.
- A shared study record means a potentially reusable research asset. It does not establish common treatment efficacy or patient eligibility.

