# Graph schema

The graph is an evidence-backed research-navigation graph. The canonical source files remain the normalized CSV files and the evidence edge table.

## Nodes

Every node is stored with the generic Neo4j label Entity and a kind property.

| kind | Required identity | Examples |
| --- | --- | --- |
| Disease | MONDO ID | MONDO:0018149 |
| Gene | Provisional symbol ID until HGNC IDs are resolved | GENE_SYMBOL:GLB1 |
| Protein | UniProt accession for a reviewed human protein | UNIPROT:P16278 |
| Study | NCT ID | NCT:NCT05109793 |
| Organization | Stable local ID plus official URL | ORG:CURE_GM1 |
| Evidence | Evidence-table ID | EVIDENCE:E-01 |

## Relationships

Each relationship has an edge ID, an assertion level, an evidence ID, a confidence value, a source URL, and notes.

- curated: directly represented by a source record or ontology.
- extracted: extracted from a publication and awaiting review.
- inferred: a derived research lead; useful for navigation but not a direct biological or clinical claim.
- human_reviewed: reviewed by a person after extraction.

The MVP uses **RESEARCH_NEIGHBOR** and **RESOURCE_NEIGHBOR** for research-navigation links. They must not be rendered as treatment-equivalence claims.

**ENCODES** links a provisional gene node to a reviewed human UniProt protein node. It is an identity mapping, not a similarity claim.

## Query acceptance checks

The first graph build is correct when these paths are queryable:

1. GM1 gangliosidosis -> RESEARCH_NEIGHBOR -> GM2 gangliosidosis.
2. NCT05109793 -[STUDIES]-> GM1 gangliosidosis.
3. GM1 gangliosidosis -> RESOURCE_NEIGHBOR -> Gaucher disease type II.
4. Every material edge has an `evidence_id` that matches an Evidence node with a source URL.

## Identity note

The gene IDs are deliberately provisional symbol IDs until the HGNC and NCBI Gene mappings are resolved. Do not treat GENE_SYMBOL:* as final canonical IDs in downstream analysis.
