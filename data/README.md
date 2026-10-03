# Data layout

- processed/ contains the small normalized CSV files used by the prototype.
- processed/proteins.csv and processed/proteins.fasta contain the reviewed human UniProt mapping and sequence snapshot for GLB1, HEXA, HEXB, and GM2A.
- manifests/manifest.json records the committed seed snapshot.
- manifests/protein_snapshot_*.json records the protein mapping release and sequence checksums.
- raw/ is generated locally by the fetch pipeline and is ignored by Git because it contains large source snapshots.
