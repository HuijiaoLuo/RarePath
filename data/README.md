# Data layout

- processed/ contains the small normalized CSV files used by the prototype.
- manifests/manifest.json records the committed seed snapshot.
- raw/ is generated locally by the fetch pipeline and is ignored by Git because it contains large source snapshots.
