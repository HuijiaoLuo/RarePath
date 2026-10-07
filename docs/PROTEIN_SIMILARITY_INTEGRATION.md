# Protein Similarity Integration

## Recommendation

Protein mapping and similarity search are implemented in RarePath as a derived research-navigation layer. They extend the curated disease, gene, study, organization, and evidence layer rather than replace it.

The output of a similarity search is a hypothesis or ranking signal. It is not, by itself, evidence that two diseases are equivalent, that a treatment will work, or that a patient is eligible for a study.

## Proposed graph extension

The current graph keeps provisional gene nodes such as `GENE_SYMBOL:GLB1`. Add protein nodes only after the gene-to-protein mapping has been normalized:

```text
(Disease)-[:HAS_GENE|INVOLVES_GENE]->(Gene)
(Gene)-[:ENCODES]->(Protein)
(Protein)-[:SIMILAR_TO {method: ...}]->(Protein)
```

`SIMILAR_TO` should be an inferred relationship with explicit provenance. It must not be rendered as a treatment-equivalence edge.

The current bounded implementation is intentionally restrictive. Running `python pipelines/sync_structure_evidence_to_graph.py` reads `data/processed/structure_comparison.csv` and creates graph evidence only for rows with `status = computed`. It currently adds the HEXA (P06865) -> HEXB (P07686) edge from the 0.865 Å, 483-high-confidence-pair C-alpha fit. The five rows with insufficient mapping are retained in the comparison CSV but create no graph edge.

### Protein node fields

Recommended fields for `data/processed/proteins.csv`:

```text
protein_id,uniprot_accession,isoform_id,gene_symbol,organism_taxon,
reviewed,sequence_length,sequence_sha256,mapping_source,source_release,source_url
```

For the first version, select one reviewed human canonical protein per gene where possible. Keep alternative isoforms as separate nodes when the isoform changes the sequence or the biological interpretation.

UniProt's ID Mapping service is suitable for the gene-to-protein step. Store the mapping release and the original gene symbol so that the result can be regenerated and audited.

Reference: [UniProt ID Mapping API](https://idmapping.uniprot.org/cgi-bin/idmapping_http_client3?page=RESTfulDoc).

### Similarity edge fields

Recommended fields for `data/processed/protein_similarity.csv`:

```text
similarity_id,source_protein_id,target_protein_id,method,
identity_pct,query_coverage,target_coverage,evalue,bitscore,
embedding_model,embedding_version,cosine_similarity,
structure_source,tm_score,lddt,assertion_level,evidence_id,
primary_score,score_name,dataset_release,source_url,notes
```

Only populate the metrics produced by the selected method. Do not fill missing metrics with zero. Store one canonical pair ordering to avoid duplicate reciprocal edges.

## Similarity methods

Use a staged approach:

1. **Pairwise sequence baseline:** the committed four-protein portfolio first runs two reproducible Smith-Waterman methods: a transparent +2/-1/-2 linear-gap baseline and BLOSUM62 with affine gaps. Keep identity, alignment coverage, gap fraction, the substitution matrix, and gap model. Raw scores are only comparable within a method.
2. **Database sequence search:** use BLASTP or DIAMOND against a versioned protein set when expanding beyond the four seed proteins. Keep identity, alignment coverage, E-value, and bit score. The pairwise DP portfolio does not produce a calibrated E-value.
3. **Embedding ranking:** add a fixed protein language model and record the model name, version, pooling method, and cosine similarity. Use this as a separate ranking signal until it has been calibrated against known relationships.
4. **Structure search:** use Foldseek only when a consistent structure source and quality threshold are available. Store the structure accession and structural score with the edge.

Reference implementations: [NCBI Protein BLAST](https://blast.ncbi.nlm.nih.gov/Blast.cgi?BLAST_PROGRAMS=blastp&LINK_LOC=protein&PAGE=Proteins&PAGE_TYPE=BlastSearch) and [Foldseek](https://github.com/steineggerlab/foldseek).

Do not combine these scores into one number in the first MVP. Show separate scores and, if useful, add a later consensus rank after evaluating known positive and negative controls.

## GM1/GM2-specific guardrails

- `HEXA` and `HEXB` are useful positive controls for a homologous lysosomal enzyme relationship.
- `GLB1` is biologically relevant to GM1 but should not be expected to rank as a close sequence homolog of HEXA/HEXB merely because the diseases share a lysosomal context.
- `GM2A` has a different protein role from HEXA/HEXB; a low sequence score must not be interpreted as lack of disease relevance.
- Pathway, lysosomal localization, substrate, and phenotype evidence should remain separate graph features. Protein similarity is only one signal.

## Evidence and confidence rules

Every derived similarity edge should include:

- `assertion_level = inferred`;
- a method and dataset/model release;
- the exact source protein accessions and sequence versions;
- a reproducible score and coverage metric;
- an `evidence_id` linked to a computational-evidence node or record.

Curated disease-gene edges remain authoritative for the MVP. A similarity edge may help find a candidate disease or study, but it must not upgrade a disease-gene assertion or clinical recommendation.

### Interpreting confidence

Confidence has two separate meanings and they must not be conflated:

1. **Claim support:** does the cited source actually contain the extracted claim?
2. **Biological truth:** is the claim sufficient to establish a disease mechanism or a useful intervention?

The first can be scored mechanically. The current RAG extractor uses this auditable policy:

```text
score = source-tier weight
      + structured-record weight
      + exact source-span match
      + endpoint appears in source
      then apply a relationship-specific cap
```

The policy labels `high` (>=0.80), `medium` (0.55-0.79), or `low` (<0.55). A direct statement such as “this record is reported in GLB1” can therefore have high **claim-support confidence** when its ClinVar row and exact source span are present. That does not mean the record is an expert-confirmed causal variant. A `seed_condition` search label is capped at medium because it may describe retrieval context rather than an explicit condition assertion.

Protein similarity is computational evidence. A high sequence, embedding, or structure score can support a hypothesis about shared ancestry, fold, domain, active-site geometry, or possibly a related pathway, depending on the method and its coverage. It does not by itself establish:

- that two diseases are equivalent;
- that the proteins have the same substrate or cellular role;
- that a variant is pathogenic; or
- that a drug or gene therapy will work.

For a similarity edge to move above a low-confidence research lead, add independent evidence such as:

| Evidence layer | What it supports |
| --- | --- |
| Reproducible score, coverage, E-value/TM-score, model and release | The computational similarity result is reproducible |
| Domain, active-site, localization, substrate, and pathway agreement | A plausible shared mechanism |
| Functional assay or curated disease-gene record | Direct biological support |
| Repeated patient phenotype or natural-history concordance | Human relevance |
| Independent sources and replicated experiments | Confidence that the signal is not an artifact |

The UI should display these layers separately. It should never turn one similarity score into a “similar disease” or treatment recommendation.

## Acceptance checks

The first integration is ready when:

1. All four seed symbols (`GLB1`, `HEXA`, `HEXB`, `GM2A`) have a traceable human protein mapping or an explicit unmapped status.
2. Every mapped protein has an accession, isoform, sequence length, sequence checksum, and mapping release.
3. Every similarity row has a method, dataset/model version, score, and source protein versions.
4. The Neo4j loader can import the protein nodes and similarity edges without changing the existing disease-gene evidence edges.
5. The UI/API labels similarity results as computational research leads and displays their provenance.

## Suggested Neo4j query

After the protein layer is loaded, this query exposes a ranked research path from GM1 to another disease through a similar protein:

```cypher
MATCH (d:Entity {node_id: 'MONDO:0018149'})
      -[:HAS_GENE|INVOLVES_GENE]->(g:Entity)
      -[:ENCODES]->(p:Entity)
      -[s:SIMILAR_TO]->(p2:Entity)
      <-[:ENCODES]-(g2:Entity)
      <-[:HAS_GENE|INVOLVES_GENE]-(d2:Entity)
WHERE d2.kind = 'Disease'
RETURN d.label AS source_disease,
       g.label AS source_gene,
       p.label AS source_protein,
       p2.label AS similar_protein,
       g2.label AS candidate_gene,
       d2.label AS candidate_disease,
       s.method AS method,
       s.primary_score AS score,
       s.score_name AS score_name,
       s.query_coverage AS query_coverage,
       s.evidence_id AS evidence_id
ORDER BY score DESC
LIMIT 25;
```

The exact relationship properties should be adapted to the chosen similarity method. The query is for navigation and review, not diagnosis.

## Implementation order

1. Resolve the four provisional gene symbols to reviewed human UniProt entries.
2. Commit a small, versioned protein mapping table with checksums.
3. Run the sequence baseline and inspect the positive/negative controls.
4. Run `python pipelines/sync_structure_evidence_to_graph.py`, then dry-validate with `python graph/load_neo4j.py`.
5. Add embeddings or an independent structure search only after the baseline output is visible and reviewable.
