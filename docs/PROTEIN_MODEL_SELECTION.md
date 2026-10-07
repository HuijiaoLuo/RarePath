# Protein Model Selection

## Core decision

Gene-to-protein mapping is an identity-resolution task, not a machine-learning task. Resolve `GLB1`, `HEXA`, `HEXB`, and `GM2A` through stable identifiers and reviewed human UniProt entries first. Machine learning begins after the protein sequence and isoform are fixed.

For rare-disease discovery, use a layered retrieval-and-reranking system. Protein sequence similarity alone can find homologues, but it can miss proteins with related function, pathway, phenotype, or lysosomal context.

The first public mapping snapshot is already generated:

| Gene | UniProt | Length |
| --- | --- | ---: |
| GLB1 | P16278 | 677 aa |
| HEXA | P06865 | 529 aa |
| HEXB | P07686 | 556 aa |
| GM2A | P17900 | 193 aa |

The sequence checksums and UniProt release are recorded in `data/manifests/protein_snapshot_*.json`.

## Recommended layers

| Layer | Recommended tool/model | Compute | Use in the MVP |
| --- | --- | --- | --- |
| Identity | UniProt ID Mapping plus HGNC/NCBI cross-references | Very light | Required |
| Sequence retrieval | MMseqs2 or DIAMOND; BLASTP for small validation sets | CPU-friendly | Required baseline |
| Protein embedding | ESM-2 35M, then ESM-2 150M if useful | Light to moderate | Recommended second layer |
| Structure retrieval | AlphaFold DB structures plus Foldseek | No folding for known human proteins | Recommended third layer |
| Function and pathway | InterPro/Pfam, Gene Ontology, Reactome | Light | Required for interpretation |
| Disease phenotype | HPO semantic similarity | Light | Required for disease ranking |
| Variant effect | ESM-1v/ESM-2 scores plus ClinVar evidence | Moderate | Later, never a diagnosis by itself |
| Graph ML | R-GCN/GraphSAGE/link prediction | Heavy and data-hungry | Do not use in the first MVP |

## Why this order

### 1. Sequence baseline first

Use MMseqs2 or DIAMOND to retrieve candidate homologues and store identity, alignment coverage, E-value, bitscore, and database release. This is interpretable, fast, and provides a baseline for every later model.

For four seed genes, it is practical to validate a small number of pairs with BLASTP. For a larger human-protein search, MMseqs2 or DIAMOND is more practical than repeatedly calling a web service.

### 2. ESM-2 for a light embedding layer

The ESM-2 family includes a 35M-parameter model with 480-dimensional embeddings and a 150M-parameter model with 640-dimensional embeddings. Start with `esm2_t12_35M_UR50D`; move to `esm2_t30_150M_UR50D` only if the small model fails the validation set.

Use mean-pooled residue embeddings and cosine similarity. Store the model name, model release, pooling rule, and sequence checksum with every result. Do not treat cosine similarity as a probability or clinical score.

The official ESM repository documents ESM-2, ESMFold, and variant-effect models: <https://github.com/facebookresearch/esm>.

### 3. Structure without folding everything

Do not run a new folding model for every query. For known human proteins, retrieve the existing AlphaFold DB structure where available and compare structures with Foldseek. This is cheaper and more reproducible than generating structures on demand.

Use the structure layer to compare folds, domains, active-site neighborhoods, and confidence. Store the structure accession, database release, aligned coverage, TM-score, and any confidence filter.

References: <https://alphafold.ebi.ac.uk/> and <https://github.com/steineggerlab/foldseek>.

### 4. Add biology around the protein

Disease similarity should be ranked with more than protein sequence:

- HPO semantic similarity for patient phenotype;
- InterPro/Pfam domains and catalytic motifs;
- Gene Ontology and Reactome pathway overlap;
- lysosomal localization and substrate relationships;
- ClinVar variant evidence and disease-gene confidence;
- natural-history and study overlap from the existing graph.

This is especially important for GM1/GM2. HEXA and HEXB are useful sequence and structural positive controls, while GLB1 and GM2A may be biologically relevant without being close sequence homologues of HEXA/HEXB.

## Similarity score contract

Keep method-specific scores separate in `protein_similarity.csv`:

```text
method,primary_score,score_name,identity_pct,query_coverage,
evalue,bitscore,cosine_similarity,tm_score,lddt,
model_version,dataset_release,evidence_id
```

Do not average E-values, cosine similarities, and TM-scores into one number. First return a ranked list per method. Add a consensus rank only after testing known positive and negative controls.

Each `SIMILAR_TO` edge in Neo4j should have:

```text
assertion_level = inferred
method = blastp | mmseqs2 | esm2 | foldseek
source protein accession and sequence checksum
target protein accession and sequence checksum
model or database version
evidence_id
```

## Disease-level ranking

The recommended query is retrieval followed by reranking:

1. Retrieve candidate proteins by sequence or structure.
2. Map candidate proteins back to genes and diseases.
3. Rerank with HPO, pathway, domain, lysosomal, and evidence features.
4. Show each feature separately in the UI.
5. Ask a researcher to review the candidate before creating an R&D hypothesis.

A useful future score can be calibrated as:

```text
candidate_rank = f(sequence, embedding, structure,
                   phenotype, pathway, evidence_prior)
```

Do not train `f` until there is a labelled evaluation set. A graph neural network trained on the current 25-node graph would memorize the seed rather than generalize.

## Protein-folding opportunity

The strongest near-term opportunity is not to claim that RarePath discovers a drug automatically. It is to use protein structure to make research hypotheses more concrete:

- map ClinVar variants onto domains, active sites, and low-confidence regions;
- compare disease-protein folds and catalytic neighborhoods;
- identify possible chaperone, substrate-reduction, replacement, ASO, or gene-therapy hypotheses;
- connect a structural hypothesis to a biomarker and a study endpoint;
- record the hypothesis and its evidence as a reviewable graph object.

For the current seed, the first structural deliverable should be a side-by-side protein card for GLB1, HEXA, HEXB, and GM2A with sequence length, domain annotations, structure accession, confidence, and similarity results. It should not claim that a structural match proves therapeutic efficacy.

## MVP acceptance tests

1. Four seed genes map to traceable reviewed human proteins or have an explicit unmapped status.
2. Each sequence has a release and SHA-256 checksum.
3. The sequence baseline produces reproducible results on a versioned database.
4. ESM-2 35M embeddings run on ordinary laptop hardware and are cached by sequence checksum.
5. AlphaFold DB/Foldseek results are stored separately from sequence results.
6. HEXA–HEXB is detected as a positive control.
7. The UI labels every similarity result as computational and shows method, version, score, and evidence.

## Implementation order

1. Build the UniProt mapping table with `python pipelines/fetch_protein_mappings.py`.
2. Add protein nodes and `ENCODES` edges to Neo4j.
3. Run MMseqs2/DIAMOND sequence retrieval.
4. Add the ESM-2 35M embedding cache.
5. Add AlphaFold DB/Foldseek structure results.
6. Add HPO and pathway reranking.
7. Only then create R&D hypothesis cards and collaborator workflows.
