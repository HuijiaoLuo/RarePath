# GM1 / GM2 Gangliosidosis - Seed Evidence Table

**Project status:** selected MVP disease cluster

**Last reviewed:** 2026-10-03
**Purpose:** a small, source-linked evidence inventory for the first demo path. It is not clinical guidance and is not a complete literature review.

## 1. Demo boundary

### Primary journey

> **GM1 gangliosidosis** -> **GM2 gangliosidoses** -> **shared natural-history / trial-design assets** -> **Cure GM1 Foundation and NTSAD** -> **validate whether outcome measures, registry fields, and eligibility criteria can be harmonized.**

### What the product may and may not claim

| May state | Must not state |
| --- | --- |
| GM1 and GM2 are biologically related lysosomal gangliosidoses with documented shared research resources. | A treatment or gene therapy for one condition will work for the other. |
| A study or registry may be a resource worth investigating for shared research operations. | A patient is eligible for a study; eligibility must be assessed from the current official record and by the study team. |
| A connection is supported, inferred, or unsupported, with links to the supporting records. | A clinical recommendation or a prediction of treatment efficacy. |

## 2. Seed nodes

| Node | Canonical ID / key | Role | Verification source | Status |
| --- | --- | --- | --- | --- |
| GM1 gangliosidosis | MONDO:0018149 | Parent disease node and search alias target | [Mondo release/downloads](https://mondo.monarchinitiative.org/pages/download/) | Ready |
| GM1 gangliosidosis type 2 | MONDO:0009261 | Primary late-infantile/juvenile demo case | [Monarch/DisMech record](https://dismech.monarchinitiative.org/pages/disorders/GM1_Gangliosidosis_Type_2.html) | Ready |
| GLB1 | Resolve stable HGNC and NCBI Gene IDs during ingestion | Causal-gene node for GM1 | [GM1 type 2 evidence summary](https://dismech.monarchinitiative.org/pages/disorders/GM1_Gangliosidosis_Type_2.html) | ID normalization pending |
| GM2 gangliosidosis | MONDO:0017720 | Parent mechanism and discovery node | [GM2 grouping record](https://dismech.monarchinitiative.org/pages/groupings/GM2_Gangliosidoses.html) | Ready |
| Tay-Sachs disease | MONDO:0010100 | GM2 disease node | [GM2 grouping record](https://dismech.monarchinitiative.org/pages/groupings/GM2_Gangliosidoses.html) | Ready |
| Sandhoff disease | MONDO:0010006 | GM2 disease node | [Sandhoff record](https://dismech.monarchinitiative.org/pages/disorders/Sandhoff_Disease.html) | Ready |
| HEXA, HEXB, GM2A | Resolve stable HGNC and NCBI Gene IDs during ingestion | GM2 causal-gene nodes | [GM2 grouping record](https://dismech.monarchinitiative.org/pages/groupings/GM2_Gangliosidoses.html) | ID normalization pending |
| Gaucher disease type 2 | MONDO:0009266; resolve gene mapping during ingestion | Cautionary comparison node | [NTSAD natural-history listing](https://ntsad.org/ntsad-research/research-for-families-and-individuals/natural-history-studies/) | Disease ID ready; gene mapping pending |
| Cure GM1 Foundation | Official URL | GM1 patient-organization node | [Cure GM1](https://www.curegm1.org/) | Ready |
| National Tay-Sachs & Allied Diseases Association (NTSAD) | Official URL | GM2 organization and research-resource node | [NTSAD research](https://ntsad.org/about-ntsad/) | Ready |

## 3. Seed evidence edges

| ID | Graph assertion | Type | Supporting record | Evidence and UI wording | Status |
| --- | --- | --- | --- | --- | --- |
| E-01 | GM1 gangliosidosis type 2 -> has causal gene -> GLB1 | Curated disease-gene fact | [GM1 type 2 record](https://dismech.monarchinitiative.org/pages/disorders/GM1_Gangliosidosis_Type_2.html) | “GM1 is associated with GLB1 deficiency.” Show the source link. | Ready |
| E-02 | Tay-Sachs / Sandhoff -> is a -> GM2 gangliosidosis | Ontology hierarchy | [GM2 grouping record](https://dismech.monarchinitiative.org/pages/groupings/GM2_Gangliosidoses.html) | “These are distinct GM2 conditions within the same gangliosidosis group.” | Ready |
| E-03 | GM2 gangliosidosis -> involves -> HEXA / HEXB / GM2A | Curated mechanism fact | [GM2 grouping record](https://dismech.monarchinitiative.org/pages/groupings/GM2_Gangliosidoses.html) | “GM2 degradation depends on several distinct gene products; keep each disease distinct.” | Ready |
| E-04 | NCT05109793 -> studies -> GM1 and GM2 gangliosidosis | Shared research asset | [NTSAD natural-history listing](https://ntsad.org/ntsad-research/research-for-families-and-individuals/natural-history-studies/) | “A natural-history study covers GM1 and GM2; this is a candidate shared data and outcome-measure asset.” | Ready; re-check study status at runtime |
| E-05 | NCT00029965 -> studies -> GM1 and GM2 gangliosidosis | Shared research asset | [NTSAD natural-history listing](https://ntsad.org/ntsad-research/research-for-families-and-individuals/natural-history-studies/) | “An NIH natural-history study spans several glycosphingolipid and glycoprotein disorders, including GM1 and GM2.” | Ready; re-check study status at runtime |
| E-06 | NCT07054515 -> has master protocol for -> GM1, GM2, and NPC | Shared trial-design asset | [NTSAD clinical-trial listing](https://ntsad.org/ntsad-research/clinical-trials/) | “A Phase 3 master protocol is a concrete example of cross-disease trial design.” The UI must show that the GM1/GM2 cohorts are listed as fully enrolled on NTSAD’s current page. | Ready; do not present as an enrollment opportunity |
| E-07 | Cure GM1 Foundation -> supports -> GM1 gangliosidosis | Organization-disease fact | [Cure GM1](https://www.curegm1.org/) | “Patient-led GM1 research and support organization.” | Ready |
| E-08 | NTSAD -> supports -> GM2 gangliosidoses | Organization-disease fact | [NTSAD research](https://ntsad.org/about-ntsad/) | “Patient organization with GM2 research and clinical-development resources.” | Ready |
| E-09 | Gaucher disease type 2 -> co-studied in NCT04470713 with GM1 and GM2 | Shared research-operations fact | [NTSAD natural-history listing](https://ntsad.org/ntsad-research/research-for-families-and-individuals/natural-history-studies/) | “This shared study record makes Gaucher type 2 a resource neighbor only. It is not enough evidence to infer a common treatment path.” | Ready; use as counterexample |

## 4. Core graph path for the demo

~~~text
GM1 gangliosidosis type 2
  -> GLB1-related lysosomal ganglioside storage
  -> related lysosomal gangliosidosis cluster
  -> GM2: Tay-Sachs and Sandhoff
  -> shared natural-history / trial-design records
  -> Cure GM1 Foundation and NTSAD
  -> action: validate shareable endpoints, registry variables, and age/eligibility constraints
~~~

The relationship from GM1 to GM2 is a **research-neighbor** connection. The demo must distinguish it from a direct therapeutic-transfer claim.

## 5. Immediate ingestion tasks

| Priority | Task | Output | Acceptance check |
| --- | --- | --- | --- |
| P0 | Download a versioned Mondo release and resolve the seed disease IDs. | data/raw/mondo/ and data/processed/diseases.csv | Every disease node has a MONDO ID, label, synonyms, source version, and retrieval date. |
| P0 | Retrieve ClinVar disease/gene and variant records for GLB1, HEXA, HEXB, and GM2A. | data/raw/clinvar/, genes.csv, variants.csv | Each variant retains its ClinVar ID, clinical-significance field, review status, and source date. |
| P0 | Create study records for the four NCT IDs in this table. | studies.csv | Store official URL, current status, conditions, sponsor, design, intervention, and eligibility text. |
| P1 | Run PubMed searches for natural history, biomarkers, and outcome measures. | papers.csv, claims_pending_review.csv | Every extracted claim has a PMID and an evidence excerpt before it can enter the public graph. |
| P1 | Add organization records for Cure GM1 and NTSAD. | organizations.csv | Store only publicly listed organization details and the source URL. |
| P1 | Add a human-review flag to every extracted or inferred edge. | edges.csv / Neo4j | The UI can label every edge as curated, extracted, inferred, or reviewed. |

### Suggested PubMed queries

~~~text
("GM1 gangliosidosis"[Title/Abstract]) AND ("natural history" OR biomarker OR "outcome measure")
("GM2 gangliosidosis"[Title/Abstract] OR "Tay-Sachs"[Title/Abstract] OR Sandhoff[Title/Abstract])
  AND ("natural history" OR biomarker OR "outcome measure")
("GM1 gangliosidosis"[Title/Abstract]) AND ("GM2 gangliosidosis"[Title/Abstract] OR "lysosomal storage")
~~~

## 6. Product copy for the first action card

> **Why this connection is worth checking:** GM1 and GM2 are related lysosomal gangliosidoses, and there are documented studies that collect natural-history information across both conditions. That creates a practical opportunity to compare how outcomes, registry fields, and study operations are defined.
>
> **What remains uncertain:** Their underlying genetic defects and substrate biology differ. This evidence does not show that a therapy or gene-delivery approach can be transferred between conditions.
>
> **Suggested next step:** Ask the relevant patient organizations and study teams whether their outcome measures, eligibility criteria, and data dictionaries can be aligned for a future shared research initiative.

## 7. Data-quality rules

1. The visible graph must link each material claim to a source record.
2. A model-extracted claim remains **extracted** until a person reviews it.
3. Current recruitment status must be retrieved from the official ClinicalTrials.gov record at display time; do not rely on a static seed file.
4. “Shared study” means a possible shared research asset. It does not imply shared mechanism, trial eligibility, or therapeutic response.
5. Keep personal health data out of the prototype. Use only public aggregate data and organization contact details.
