# Protein Similarity Integration

## Recommendation

Protein mapping and similarity search can be added to RarePath as a derived research-navigation layer. It should extend the current evidence graph rather than replace the curated disease, gene, study, organization, and evidence layer.

The output of a similarity search is a hypothesis or ranking signal. It is not, by itself, evidence that two diseases are equivalent, that a treatment will work, or that a patient is eligible for a study.

## Proposed graph extension

The current graph keeps provisional gene nodes such as `GENE_SYMBOL:GLB1`. Add protein nodes only after the gene-to-protein mapping has been normalized:

```text
(Disease)-[:HAS_GENE|INVOLVES_GENE]->(Gene)
(Gene)-[:ENCODES]->(Protein)
(Protein)-[:SIMILAR_TO {method: ...}]->(Protein)
```

`SIMILAR_TO` should be an inferred relationship with explicit provenance. It must not be rendered as a treatment-equivalence edge.

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

1. **Sequence baseline:** BLASTP or DIAMOND against a versioned protein set. Keep identity, alignment coverage, E-value, and bit score. This gives the team an interpretable baseline.
2. **Embedding ranking:** add a fixed protein language model and record the model name, version, pooling method, and cosine similarity. Use this as a separate ranking signal until it has been calibrated against known relationships.
3. **Structure search:** use Foldseek only when a consistent structure source and quality threshold are available. Store the structure accession and structural score with the edge.

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
4. Add `Protein` nodes and `ENCODES`/`SIMILAR_TO` relationships to the loader.
5. Add embeddings or structure search only after the baseline output is visible and reviewable.
