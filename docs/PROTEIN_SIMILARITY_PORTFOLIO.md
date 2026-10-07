# Protein Similarity Portfolio v0.2

This portfolio demonstrates a reproducible sequence-similarity baseline for the four GM1/GM2 gangliosidosis seed proteins:

| Gene | UniProt | Role in this portfolio |
| --- | --- | --- |
| GLB1 | P16278 | GM1-associated lysosomal enzyme |
| HEXA | P06865 | Hexosaminidase alpha subunit |
| HEXB | P07686 | Hexosaminidase beta subunit |
| GM2A | P17900 | GM2 activator protein |

The portfolio uses two reproducible local-alignment methods implemented with the Python standard library. It is a sequence baseline, not a structural or clinical prediction system.

## How to run it

From the repository root:

```bash
python pipelines/compute_protein_similarity.py
```

The command validates every FASTA sequence against the SHA-256 checksum in `data/processed/proteins.csv`, computes all six unique protein pairs with two methods, and writes:

- `data/processed/protein_similarity.csv`
- `data/manifests/protein_similarity_v0.2.json`

No API key, Neo4j connection, or LLM call is needed for this step.

## Algorithms

Each row is one method applied to one protein pair. There are 12 rows: six pairs multiplied by two methods.

### 1. Transparent local-alignment baseline

The first method uses Smith-Waterman local alignment with constant scores:

```text
match     = +2
mismatch  = -1
gap       = -2
```

This version is useful for teaching the dynamic-programming flow. It treats every non-identical amino-acid substitution as equally unfavorable, so it is not a calibrated protein-evolution model.

### 2. Protein-aware local alignment

The second method uses the NCBI BLOSUM62 substitution matrix plus affine gap costs:

```text
gap cost for k residues = -(11 + 1 × k)
```

BLOSUM62 gives biologically plausible amino-acid substitutions different scores. For example, conservative substitutions can be less penalized than chemically implausible ones. The affine gap model charges a large opening cost and a smaller extension cost, so one long indel is treated differently from many independent indels.

The algorithm uses three dynamic-programming matrices:

```text
H[i,j]  best local score ending at residues i,j
E[i,j]  best score ending with a gap in the source sequence
F[i,j]  best score ending with a gap in the target sequence
```

At each cell, the nested loops compute `E`, `F`, then `H`. This preserves the dependency order: left, upper, and diagonal cells have already been computed. The final score is the largest value anywhere in `H`; traceback follows the stored matrix-state pointers until the score reaches zero.

The BLOSUM62 values and the `(11, 1)` gap parameters follow [NCBI's BLAST substitution-matrix guidance](https://blast.ncbi.nlm.nih.gov/html/sub_matrix.html). The code stores the matrix source URL with every derived result.

Local alignment is useful here because two proteins can share a conserved domain without being similar across their full lengths. The output reports the aligned region instead of hiding it inside one score.

The main metrics are:

- `alignment_score`: raw dynamic-programming score under the selected method. Do not compare raw scores across methods;
- `identity_pct`: identical residues among aligned residue pairs;
- `query_coverage_pct` and `target_coverage_pct`: residues used by the alignment in each full sequence, including residues aligned against a gap;
- `minimum_coverage_pct`: the more conservative of the two coverage values;
- `gap_fraction_pct`: fraction of alignment columns containing a gap.

**Statistical significance.** Identity and coverage do not say whether a local match could arise by chance. For the BLOSUM62 + affine method, the pipeline computes the Karlin-Altschul E-value and bit score:

```text
E    = K · m · n · exp(−λ · S)
bits = (λ · S − ln K) / ln 2
```

Here S is the raw score, m and n are the full sequence lengths, and λ = 0.267, K = 0.041 are NCBI BLAST's published parameters for gapped BLOSUM62 with gap costs 11/1. No finite-length correction is applied, so E-values for very short alignments are slightly conservative. An E-value below 10⁻³ is treated as significant. The linear teaching baseline has no published parameters, so its E-value fields stay empty.

The pipeline does not fabricate TM-scores, embeddings or other structure scores. Those fields remain empty until a separately versioned method is run.

**Implementation check.** The affine-gap dynamic programme was compared with an independent, slower Waterman-Smith-Beyer formulation (explicit maximisation over every gap length) on 300 random sequence pairs. The scores agreed in 300 of 300 cases.

## Results to show in the portfolio

| Pair | Simple DP: identity / min. coverage | BLOSUM62 + affine gaps: identity / min. coverage | Bits | E-value | Readout |
| --- | --- | --- | --- | --- | --- |
| HEXA / HEXB | 65.633% / 69.604% | 57.400% / 89.928% | 608.6 | 1.8 × 10⁻¹⁷⁸ | Significant, broad homology (positive control) |
| GLB1 / HEXA | 70.000% / 1.477% | 43.750% / 2.363% | 20.0 | 0.34 | Not distinguishable from chance |
| GLB1 / HEXB | 75.000% / 1.182% | 27.632% / 11.669% | 20.4 | 0.27 | Not distinguishable from chance |
| GLB1 / GM2A | 100.000% / 0.886% | 48.000% / 4.579% | 18.1 | 0.47 | Not distinguishable from chance |
| HEXA / GM2A | 87.500% / 1.512% | 30.233% / 8.129% | 16.5 | 1.1 | Not distinguishable from chance |
| HEXB / GM2A | 75.000% / 2.518% | 28.125% / 5.755% | 15.8 | 1.9 | Not distinguishable from chance |

`HEXA`/`HEXB` is the only significant pair (E = 1.8 × 10⁻¹⁷⁸). The BLOSUM62 result covers at least 89.928% of each sequence (the lower of the two coverages) with 57.400% identity, as expected for the two subunits of the same enzyme. It serves as the method's positive control. The other five pairs have E-values between 0.27 and 1.9: a match that good is expected by chance about once per comparison, so they are negative controls.

The same comparison shows why identity alone is unsafe. `GLB1`/`GM2A` changes from 100% identity over 0.886% coverage in the simple baseline to 48% identity over 4.579% coverage with BLOSUM62. Both results still indicate a short local signal, not a meaningful whole-protein relationship. The heuristic labels are review aids, not calibrated probabilities.

## How to interpret the result

The output is a computational research lead. A high sequence identity with broad coverage can support a homology or shared-domain hypothesis. It does not establish that two proteins have the same substrate, cellular role, disease mechanism, or treatment response.

The expected biological controls are deliberately different:

- `HEXA`/`HEXB` are a useful homologous lysosomal enzyme pair;
- `GLB1` is relevant to GM1 but should not rank as a close homolog merely because the diseases share lysosomal context;
- `GM2A` has a different activator-protein role, so lower sequence similarity does not remove its GM2 disease relevance.

For this reason, the portfolio keeps protein similarity separate from ClinVar, MONDO, phenotype, pathway, and clinical-study evidence.

## Structure comparison v0.1: a bounded 3D check

The structure step is deliberately narrower than a general structure-search engine. It uses the four versioned AlphaFold DB PDB files retrieved by `pipelines/fetch_alphafold_structures.py`; the source accessions, AlphaFold model version/date, original URLs and SHA-256 checksums are in `data/processed/structure_models.csv` and `data/manifests/structure_snapshot_20261003T231828Z.json`.

Run the local comparison with:

```bash
python pipelines/compute_structure_comparison.py
```

It writes `data/processed/structure_comparison.csv` plus `data/manifests/structure_comparison_v0.1.json`; it makes no API request and needs no third-party package. The procedure is explicit:

1. Recompute the BLOSUM62 + affine-gap local alignment and retain its zero-based residue mapping.
2. Map those residue pairs to one C-alpha coordinate per residue in the two AlphaFold PDB files. The parser validates both PDB SHA-256 values and checks that the PDB C-alpha sequence matches the versioned UniProt sequence.
3. Retain a pair only if both models assign pLDDT >= 70 to its C-alpha atom. In AlphaFold PDB files, pLDDT is stored in the B-factor field.
4. Only continue if there are at least 30 mapped C-alpha pairs and at least 25% coverage of each structure (the lower of the two coverages). A pair failing either gate is recorded as `not_evaluated`, not as a low structural-similarity score.
5. For eligible pairs, solve the rigid-fit objective

```text
minimize  Σ || R xᵢ + t − yᵢ ||²
over      a proper 3D rotation R and translation t
```

The code uses Horn's quaternion form of the Kabsch least-squares fit. It forms a fixed 4×4 symmetric matrix from the centered coordinate cross-covariance, obtains its largest-eigenvalue quaternion with Jacobi rotations, then computes the post-fit C-alpha RMSD. The sequence DP costs Θ(nm); after residue mapping, the coordinate pass costs Θ(k), where `k` is the number of mapped C-alpha pairs. The 4×4 eigensolve is constant-sized.

For the current four-model snapshot, only HEXA/HEXB meets both mapping gates: 500 mapped residue pairs, 483 high-confidence C-alpha pairs, mean pLDDT 96.970 / 97.618 in the used residues, and 0.865 Å C-alpha RMSD after fit. This agrees with the broad sequence-homology signal. The other five pairs are kept as explicit non-results because their sequence mapping covers only 2.363%–11.226% of the longer protein in each pair; that is too little for a full-protein structural interpretation.

This 0.865 Å result means the mapped portions of these two predicted monomers can be closely superposed under this **sequence-guided** procedure. It is not independent evidence. The residue pairing comes from the same sequence alignment, and AlphaFold predicts closely related sequences into similar shapes almost by construction, so the step confirms the sequence result rather than adding a second line of evidence. RMSD also depends on how many residues are compared; a length-normalised TM-score would be the standard next measure. It does not provide a TM-score, show that the proteins have identical complexes or substrates, or imply that GM2 disease mechanisms and treatments are interchangeable. For a broader structure search, use a separately versioned TM-align or Foldseek run after documenting the installed software and database version.

## What comes next

The next layer can add structure without changing the sequence baseline:

1. Review `data/processed/structure_models.csv` and its timestamped manifest. Confirm all four rows are `downloaded`, retain the model version/date, and inspect model confidence before interpreting flexible or low-confidence regions.
2. If the project needs an **independent** structural alignment, install and record the version of TM-align, then compare the six fixed pairs. Store TM-score, RMSD, aligned residues and structure coverage in a separate table; do not overwrite the v0.1 sequence-guided output.
3. Use Foldseek later only for a broader database search beyond the four seed proteins. It is not needed to compare six fixed pairs.
4. Compare sequence and structure signals side by side before considering any consensus ranking.
5. Load the derived rows into Neo4j as `SIMILAR_TO` edges with `assertion_level = inferred` and a computational `evidence_id`.

The structure layer should never overwrite a curated disease-gene edge or convert one similarity score into a diagnostic or treatment recommendation.
