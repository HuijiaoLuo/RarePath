# Disease similarity: mechanism and symptom scoring

This layer answers a family's first question, *who shares our disease characteristics?* It organises diseases by mechanism and by symptoms instead of by name. Scoring version **v0.4**. Data: HPO v2026-09-01, Mondo v2026-09-01 and Reactome v97.

The result is a research-navigation signal. It never states that a treatment transfers or that a patient is eligible for a study.

## Panel

The panel has 43 diseases in three families. Each family was chosen to test the same three claims:

| Claim | Lysosomal storage (20) | RASopathies (11) | Ciliopathies (12) |
| --- | --- | --- | --- |
| One gene can cause different diseases | **GLB1**: GM1 gangliosidosis vs Morquio B, *same gene, different presentation* | **PTPN11**: Noonan 1 and LEOPARD 1 | **CEP290**: Joubert 5, Senior-Loken 6 and Meckel 4. Senior-Loken 6 vs Meckel 4 is *same gene, different presentation* |
| Different genes can disrupt the same process | GM1 with the GM2 diseases (CS/DS and keratan sulfate breakdown) and with sialidosis (sialic acid metabolism) | NF1 vs Legius: *Regulation of RAS by GAPs* (mechanism 0.28). Noonan 3 (KRAS) vs Costello (HRAS): 0.84 | BBS1, BBS2 and BBS10: *BBSome-mediated cargo targeting* |
| Similar symptoms can have different causes | **Canavan** (ASPA, not lysosomal) is a look-alike for Krabbe disease | **Aarskog-Scott** (FGD1) has a Noonan-like face, but is not linked by mechanism and stays out of the RAS cluster | **Prader-Willi** (imprinting) shares obesity and hypogonadism with BBS1 and is labelled a look-alike |

The panel is defined in `PANEL` in `pipelines/fetch_cluster_expansion.py`:

- Each entry is an OMIM ID with a family, a role and a short rationale.
- It is resolved to MONDO by exact match (xref as a fallback). The name is then checked against HPO's disease name, and a failed check excludes the entry rather than guessing its identity.
- An entry may name its **curated causal genes**. HPO links some diseases to several genes; Noonan syndrome 1, for example, also lists BRAF and MAP2K1. Only the curated gene (PTPN11) is then used for scoring and for the graph's `HAS_GENE` links. Prader-Willi syndrome (`genes="-"`) has no single-gene cause and is scored on symptoms only.

To add a disease, add one line and re-run.

## Pipeline

```bash
python pipelines/build_atlas.py     # fetch -> score -> check -> graph sync -> curated resources -> validate -> export
```

| Step | Script | Network | Output |
| --- | --- | --- | --- |
| 1 | `pipelines/fetch_cluster_expansion.py` | yes, cached | `data/processed/cluster_*.csv`, `data/manifests/cluster_expansion_v0.1.json` |
| 2 | `pipelines/compute_disease_similarity.py` | no | `disease_similarity.csv`, `disease_clusters.csv`, `disease_similarity_v0.1.json` |
| 3 | `pipelines/check_cluster_benchmark.py` | no | exits 1 if a check fails |
| 4 | `pipelines/sync_cluster_to_graph.py` | no | `graph/nodes.csv`, `graph/edges.csv` (idempotent) |
| 5 | `pipelines/sync_curated_resources.py` | no | studies and patient groups from `data/curated/family_resources.csv` |
| 6 | `graph/load_neo4j.py`, `graph/export_graph_json.py` | no | validation (`--load --prune` writes Neo4j); `demo/data/graph.js` |

**The fetch step is local-first.**

- Mondo is never downloaded unless you pass `--download-mondo`. The step looks in `data/raw/mondo/`, then the sibling `../data/raw`, then any `--extra-raw-dir`.
- HPO files are reused from `data/raw/hpo/<tag>/`. Pass `--refresh-hpo` to fetch a newer release.
- UniProt and Reactome responses are cached under `data/raw/`. Reactome's `UniProt2Reactome.txt` is downloaded once per Reactome version and gives each pathway's size among human proteins, which is shown next to the evidence.
- Downloads go to a `.part` file and are then renamed. Every source is recorded in the manifest with its version and SHA-256.

## Method

### Symptoms (simGIC)

1. HPO annotations are propagated up the is_a hierarchy.
2. Each term's information content is `IC = -ln(n_t / N)` over all annotated diseases in the HPO release.
3. The score is the sum of IC over the terms both diseases share, divided by the sum over the terms either disease has.

Lab findings under *Abnormality of metabolism/homeostasis* (HP:0001939) are left out (74 annotations), so the symptom score cannot simply repeat the mechanism.

### Mechanism

The mechanism score is the largest of four signals:

| Signal | Value |
| --- | --- |
| Shared causal gene | always a mechanism link, reported on its own |
| Pathway overlap | Jaccard over the Reactome (non-disease) pathways of each disease's scoring genes, with each pathway weighted `w = ln(genes / genes in pathway)` |
| Shared MONDO disease series (Noonan syndrome, Bardet-Biedl syndrome, Joubert syndrome, Meckel syndrome, GM1 and GM2 gangliosidosis, and others) | at least 0.6 |
| Shared mechanism-defined MONDO class (lysosomal storage disease, RASopathy, ciliopathy) | at least 0.15 (new in v0.4, see below) |

A pair that shares only broad pathways (each involving more than half the genes being compared, and more than two) has its pathway overlap capped below 0.10.

"Niemann-Pick disease" is deliberately not used as a series. MONDO groups types A and C by their historical name, although SMPD1 and NPC1 act through different processes.

### Comparison sets (v0.3)

Pathway weights and symptom percentiles are measured within the comparison set:

- For a pair inside one family, the set is that family's genes and pairs.
- For a pair across families, pathways are weighted over all panel genes, and its symptom score is ranked against the pooled within-family pairs.

As a result, adding a family never changes the scores inside another family. When the RASopathies and ciliopathies were added, all 190 lysosomal pairs stayed identical to v0.2. Ranking cross-family pairs against within-family pairs also removed about 150 weak cross-family look-alikes. `tests/test_family_scoring.py` guards both properties.

### Relation classes

These gates are predeclared and recorded in the manifest:

| Class | Rule | Graph edge |
| --- | --- | --- |
| same gene, similar or different presentation | shares a scoring gene; "different" if symptoms are below the top quarter | `SHARES_CAUSAL_GENE` |
| mechanism and phenotype neighbor | mechanism ≥ 0.25 and symptoms in the top quarter | `MECHANISM_NEIGHBOR` (medium) |
| mechanism neighbor, different presentation | mechanism ≥ 0.25 only | `MECHANISM_NEIGHBOR` (low) |
| phenotype neighbor, weak mechanism | top-quarter symptoms, 0.10 ≤ mechanism < 0.25 | `PHENOTYPE_NEIGHBOR` |
| look-alike, different mechanism | top-quarter symptoms, mechanism < 0.10 | `PHENOTYPE_LOOKALIKE` |

### Clustering

Louvain clustering (networkx, seed 42) runs three times: on mechanism only, on symptoms only, and combined (0.5 × mechanism + 0.5 × symptom percentile). In the combined run, a pair carries zero weight if it is a look-alike, or if its only mechanism evidence is a shared MONDO class. Symptoms alone, or a broad class alone, therefore never pull two diseases into one community.

## Results (v0.4)

| | Lysosomal | RASopathies | Ciliopathies |
| --- | --- | --- | --- |
| Same gene | 9 | 1 | 3 |
| Mechanism neighbor (with or without similar symptoms) | 21 | 13 | 10 |
| Symptoms, weak mechanism ("needs review") | 33 | 3 | 8 |
| Look-alike | 1 (Krabbe vs Canavan) | 0 | 1 (BBS1 vs Prader-Willi) |

The combined clustering gives 16 communities and none mixes families. Examples:

- the GM1, GM2, Morquio and sialidosis diseases form one community;
- Noonan 1, 3, 4, 5 and 7, LEOPARD 1, Costello and CFC 3 form another;
- NF1 and Legius syndrome form a third;
- BBS1, BBS2 and BBS10 form a fourth;
- Joubert 1, 2 and 5, Meckel 1 and 4, Senior-Loken 6 and Alström syndrome form a fifth.

## Known-biology checks

`pipelines/check_cluster_benchmark.py` runs on every build and in the unit tests. It has 23 checks.

- **8 lysosomal checks** (since v0.2). GM1 types together; GM2 diseases together; Gaucher types together; Canavan alone; GM1 vs Morquio B as same gene, different disease; Morquio A and B sharing a mechanism; GM1 vs Sandhoff as mechanism neighbors; GM1 vs Fabry *not* strong neighbors. Scoring v0.1 passed 6 of 8.
- **12 RASopathy and ciliopathy checks, written down before their data was scored.** All 12 held on the first run with real Reactome data, and they are now enforced:
  - Noonan types together;
  - Noonan 1 and LEOPARD 1 sharing PTPN11;
  - Costello and CFC 3 with Noonan 1;
  - NF1 vs Legius as a mechanism link;
  - Aarskog-Scott not a mechanism neighbor of Noonan 1, and not in its cluster;
  - BBS1, 2 and 10 together;
  - CEP290 diseases sharing their gene, with at least one pair presenting differently;
  - Prader-Willi as a look-alike for BBS1, and not in its cluster;
  - Alström vs BBS1 in the top quarter of symptom overlap;
  - no community mixing families.
- **3 checks added after reviewing that run, marked `[v0.4]`.** They were not predeclared:
  - Noonan 5 vs LEOPARD 1 is not a look-alike;
  - Joubert 2 vs Meckel 4 is not a look-alike;
  - Krabbe vs Canavan stays a look-alike.

New families follow the same route. Their checks start as reported predictions (`predictions()` in the script) and become enforced checks after one review.

## Why v0.4: a review finding

The predictions all held, but reading every new pair showed a systematic error. Some true relatives were labelled "look similar, different biology":

- **Noonan 5 (RAF1) vs LEOPARD 1 (PTPN11).** RAF1 also causes LEOPARD syndrome type 2. The two proteins act at different steps of one RAS-MAPK cascade, and Reactome's lowest-level pathways put those steps in different pathways, so the pair shares none.
- **Joubert 2 (TMEM216) vs Meckel 4 (CEP290).** TMEM216 also causes Meckel syndrome type 2. The shared pathway, *anchoring of the basal body*, involves 5 of the 9 ciliopathy genes, one more than the "broad pathway" line.

In total, 40 within-family pairs were affected: 31 lysosomal, 8 ciliopathy and 1 RASopathy.

MONDO's mechanism-defined classes (lysosomal storage disease, RASopathy, ciliopathy) contain every panel disease except the three designed counterexamples (Canavan, Aarskog-Scott and Prader-Willi). v0.4 gives a shared class a weak mechanism floor of 0.15. This sits between "no specific process" (0.10) and "mechanism neighbor" (0.25), so the effects are limited:

- These pairs become *symptoms overlap, weak mechanism: needs review*.
- Only two pairs remain look-alikes, Krabbe–Canavan and Bardet-Biedl 1–Prader-Willi, and both involve designed counterexamples. The third designed counterexample, Aarskog-Scott, is not a look-alike of Noonan 1 (symptom overlap at the 54th percentile, below the top-quarter gate). It is simply not linked.
- The communities are unchanged, because class-only pairs carry no clustering weight.

The rule was chosen to fix the cause, not individual pairs. It is reported here because it was added after seeing results.

**What this changes in the guide.** In GM1's view, Niemann-Pick A and C1, Farber and Gaucher types 2 and 3 moved from "look similar, different biology" to "needs review", with the explanation that they share the lysosomal class but no specific process.

## What would change at 7,000 diseases

The panel is small on purpose, so every result can be checked by hand. Scaling it up would change some parts and leave others as they are:

| Part | At 43 diseases | At ~7,000 diseases |
| --- | --- | --- |
| Source data (Mondo, HPO, Reactome mapping) | Whole files, already local | Same files, no change |
| Gene profiles, AlphaFold, ClinVar | 34 genes, cached | About 4,500 genes: the same cached, linear fetch, run once in hours rather than minutes |
| Pair scoring | 903 pairs in pure Python | About 24 million pairs. simGIC and weighted Jaccard become sparse matrix products over disease × term and disease × pathway matrices, and only each disease's top neighbours are kept |
| Disease families (comparison sets) | Assigned by hand in `PANEL` | Taken from MONDO's mechanism-defined classes, which v0.4 already uses as a signal |
| Known-biology checks | 23 written by hand | Hand checks stay as smoke tests. Add held-out checks that need no curation: for example, numbered types of one MONDO series should rank each other highly, and diseases sharing a gene must be "same gene" |
| Studies and patient groups | 9 studies and 9 organisations, checked by hand | The real bottleneck. ClinicalTrials.gov can be queried by condition automatically, but patient organisations need the review queue in `rag/` (candidates are extracted, a person approves them) |
| The guide | Shows 3 communities and 1 step | Unchanged: it never shows more than a person can read |

The method scales; human-checked resource curation does not, which is why the review queue matters more than the scoring code.

## Limits

- The panel is hand-chosen. Clusters describe these 43 diseases, not all of rare disease.
- Reactome membership is coarse in two ways. Two enzymes in one catabolic pathway can act on different substrates, and steps of one signalling cascade can sit in different lowest-level pathways. A shared pathway is a reason to look closer. Scoring parent pathways in Reactome's hierarchy is a possible next step.
- The class floor depends on MONDO's classification, which is curated but can lag new findings.
- HPO annotation depth varies by disease, and well-studied diseases have more terms. simGIC partly corrects for this, but the bias remains.
- The "top quarter" symptom gate is relative to each family: simGIC ≥ 0.161 for the lysosomal diseases, 0.254 for the RASopathies and 0.154 for the ciliopathies.
