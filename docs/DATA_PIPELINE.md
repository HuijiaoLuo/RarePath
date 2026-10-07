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
4. Reviewed human UniProt protein mappings and sequences for GLB1, HEXA, HEXB, and GM2A.
5. One AlphaFold DB predicted structure per mapped UniProt accession, limited to the four seed proteins.

## Sources, methods, and versioning

| Dataset | How the code retrieves it | What is versioned |
| --- | --- | --- |
| Mondo | GitHub Releases API resolves the latest `mondo.json`, then the exact release asset is downloaded. | Release tag, asset URL, SHA-256, retrieval time, selected MONDO IDs. |
| ClinVar | NCBI E-utilities runs four documented gene-and-condition queries, then requests summary records in batches of 100. | Exact query, source count, bounded downloaded count, raw JSON snapshot, retrieval time. |
| ClinicalTrials.gov | The v2 API retrieves each explicitly listed NCT record. | NCT ID, source URL, raw JSON snapshot, retrieval time. |
| UniProt | REST search resolves one reviewed human entry per seed gene and writes its FASTA sequence. | UniProt release header, accession, sequence length, sequence SHA-256, source URL. |
| AlphaFold DB | The accession-keyed [AlphaFold DB API](https://www.alphafold.ebi.ac.uk/api-docs) is queried with the already-versioned UniProt accession; the returned model URL is downloaded for only the four seed proteins. | Accession, model ID/version/date, metadata URL, model URL, file bytes, file SHA-256, retrieval time. |

Raw source files live under `data/raw/` and are ignored by Git. Normalized CSVs and manifests are small reviewable records. A manifest is written for every acquisition run so the code, source URL, timestamp, and file checksum remain connected.

## Run it

The pipeline has no third-party Python dependencies.

~~~powershell
python pipelines/fetch_seed_data.py
~~~

To retrieve a smaller ClinVar sample while developing:

~~~powershell
python pipelines/fetch_seed_data.py --clinvar-max-per-gene 25
~~~

Resolve the four reviewed human protein mappings and FASTA sequences:

~~~powershell
python pipelines/fetch_protein_mappings.py
~~~

Download exactly four AlphaFold predicted structure models in PDB format:

~~~powershell
python pipelines/fetch_alphafold_structures.py
~~~

Check which AlphaFold model URLs would be used without downloading coordinates:

~~~powershell
python pipelines/fetch_alphafold_structures.py --dry-run
~~~

Compare the local AlphaFold PDB files without another download:

~~~powershell
python pipelines/compute_structure_comparison.py
~~~

The fetcher first requests `https://alphafold.ebi.ac.uk/api/prediction/<UniProt-accession>`, selects the newest returned record for that accession, then uses its `pdbUrl` (or `cifUrl` fallback). The exact returned URLs, model version and retrieval time are retained in `structure_models.csv` and the timestamped manifest. The current bounded snapshot contains P16278 (GLB1), P06865 (HEXA), P07686 (HEXB), and P17900 (GM2A), each as an AlphaFold v6 PDB model. No full AlphaFold database, Docker image, local server, or firewall change is involved.

## Outputs

~~~text
data/
  raw/
    mondo/<release-tag>/release.json
    mondo/<release-tag>/mondo.json
    clinvar/<UTC-timestamp>/
    clinicaltrials/<UTC-timestamp>/
    structures/alphafold/<UTC-timestamp>/
  processed/
    diseases.csv
    genes.csv
    variants.csv
    studies.csv
    proteins.csv
    proteins.fasta
    structure_models.csv
    structure_comparison.csv
  manifests/
    seed_snapshot_<UTC-timestamp>.json
    protein_snapshot_<UTC-timestamp>.json
    structure_snapshot_<UTC-timestamp>.json
    structure_comparison_v0.1.json
~~~

The manifest is the source-of-truth record for a run. It records the retrieval time, Mondo release tag, download checksum, source URLs, source query counts, and normalized output counts.

## Data-use notes

- The pipeline keeps public source snapshots for reproducibility; do not add patient-level data.
- The ClinVar pull is deliberately bounded and condition-focused. It is not a full ClinVar mirror.
- Study status and eligibility change. Refresh ClinicalTrials.gov before displaying an enrollment message.
- AlphaFold DB models are predicted monomer structures. Preserve the model version and confidence metadata; do not represent them as experimental structures.
- The AlphaFold fetcher is intentionally capped at four mapped seed proteins and 50 MB per model file. Do not replace it with a full-proteome download on a laptop.
- The structure comparison is local and does not download anything. It maps the existing BLOSUM62 affine local alignment to the PDB C-alpha trace, filters to pairs with pLDDT >= 70 in both models, then finds the rigid rotation and translation minimizing squared C-alpha distances. It records RMSD only after its mapping gates pass. This is not TM-align, Foldseek, a database search, or a clinical similarity score.
- A shared study record means a potentially reusable research asset. It does not establish common treatment efficacy or patient eligibility.

