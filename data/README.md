# Data layout

- processed/ contains the small normalized CSV files used by the prototype.
- processed/proteins.csv and processed/proteins.fasta contain the reviewed human UniProt mapping and sequence snapshot for GLB1, HEXA, HEXB, and GM2A.
- processed/structure_models.csv records the latest bounded AlphaFold DB model fetch: one predicted model per seed accession, with model version, source URLs, file checksum, and retrieval time.
- processed/structure_comparison.csv records the offline, sequence-guided C-alpha comparison. It includes only a C-alpha RMSD when a pair passes the documented alignment-coverage and pLDDT gates; empty RMSD fields are intentional, not missing values.
- manifests/manifest.json records the committed seed snapshot.
- manifests/protein_snapshot_*.json records the protein mapping release and sequence checksums.
- manifests/structure_snapshot_*.json records the AlphaFold metadata and coordinate-file acquisition for each bounded structure run.
- manifests/structure_comparison_v0.1.json records the comparison algorithm, input tables, gates, and result counts.
- raw/ is generated locally by the fetch pipelines and is ignored by Git because it contains large source snapshots, including AlphaFold metadata and PDB/mmCIF files.
