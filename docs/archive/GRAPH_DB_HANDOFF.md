# Graph DB Handoff

## Purpose

Neo4j is the query and provenance layer for the RarePath research-navigation prototype. It is not the source of truth by itself: the versioned CSV files under `graph/` remain the import source, and every material relationship must retain its evidence metadata.

The current seed snapshot contains:

- 31 `Entity` nodes;
- 35 relationships;
- 6 diseases, 4 genes, 4 proteins, 4 studies, 11 evidence records, and 2 organizations.

## Files to use

| File | Purpose |
| --- | --- |
| `graph/nodes.csv` | Source node table. |
| `graph/edges.csv` | Source relationship table and provenance. |
| `graph/schema.md` | Node, relationship, and acceptance rules. |
| `graph/load_neo4j.py` | Validation and Neo4j import script. |
| `graph/README.md` | Local and Aura loading instructions. |
| `data/processed/*.csv` | Normalized disease, gene, variant, and study data. |
| `data/processed/proteins.csv` / `proteins.fasta` | Reviewed human protein mapping and sequence snapshot. |
| `pipelines/fetch_protein_mappings.py` | Reproducible UniProt mapping step. |
| `data/processed/structure_comparison.csv` | Bounded AlphaFold sequence-guided C-alpha comparison; only eligible computed rows may become graph edges. |
| `pipelines/sync_structure_evidence_to_graph.py` | Local synchronization of computed structure evidence into graph CSVs; does not contact Neo4j. |

## Data model

All imported nodes currently use the label `Entity` and a `kind` property. This keeps the first API stable while the domain model is still growing.

Node properties:

```text
node_id, kind, label, external_id, source_url, status
```

Relationship properties:

```text
edge_id, assertion_level, evidence_id, confidence, source_url, notes
```

The main relationship semantics are:

- `HAS_GENE` / `INVOLVES_GENE`: disease-to-gene biology links;
- `STUDIES` / `RESEARCH_ASSET_FOR`: study or research-resource links;
- `SUPPORTED_BY`: link from an entity to an evidence node;
- `RESEARCH_NEIGHBOR` / `RESOURCE_NEIGHBOR`: navigation links only, never treatment equivalence.
- `SIMILAR_TO`: inferred protein-level computational lead; its method, score, coverage, and model provenance remain visible.

`assertion_level` is one of `curated`, `extracted`, `inferred`, or `human_reviewed`. Similarity results from the planned protein layer should use `inferred` and must carry a method, release, score, and provenance.

## Connection contract

The backend may read these environment variables:

```text
NEO4J_URI
NEO4J_USER       # NEO4J_USERNAME is also accepted by the loader
NEO4J_PASSWORD
NEO4J_DATABASE
```

Never put credentials in Git, frontend code, screenshots, or tracked `.env` files. The browser should call a backend API; it should never connect directly to Aura with a password embedded in JavaScript.

## Validation and loading

From the repository root:

```bash
python graph/load_neo4j.py
python graph/load_neo4j.py --load
```

The first command validates duplicate IDs, CSV shape, missing endpoints, relationship names, and evidence references. The second command writes the prepared graph after the connection variables have been set.

Before either command, regenerate the local inferred similarity edge after a structure-comparison refresh:

```bash
python pipelines/sync_structure_evidence_to_graph.py
python graph/load_neo4j.py
```

The synchronizer currently adds a single HEXA -> HEXB `SIMILAR_TO` edge. It has `assertion_level = inferred` and `confidence = medium`, because it is reproducible computational support but not independent evidence of shared mechanism or treatment response.

## Starter Cypher queries

Count the graph by node type:

```cypher
MATCH (n:Entity)
RETURN n.kind AS kind, count(*) AS count
ORDER BY kind;
```

Show the GM1-to-GM2 research-neighbor path:

```cypher
MATCH p=(a:Entity {node_id:'MONDO:0018149'})
      -[:RESEARCH_NEIGHBOR]->
      (b:Entity {node_id:'MONDO:0017720'})
RETURN p;
```

Show a disease and its evidence links:

```cypher
MATCH (d:Entity {node_id:'MONDO:0018149'})-[r]->(x:Entity)
RETURN d, r, x
ORDER BY r.confidence DESC;
```

Show the bounded protein structure result and its evidence node:

```cypher
MATCH (a:Entity {node_id:'UNIPROT:P06865'})-[s:SIMILAR_TO]->(b:Entity {node_id:'UNIPROT:P07686'})
MATCH (e:Entity {node_id:'EVIDENCE:SIMSTRUCT_P06865_P07686'})
RETURN a, s, b, e;
```

## Recommended product UI

Build a thin read-only application on top of Neo4j instead of exposing Neo4j Browser to users. A practical hackathon stack is a small backend using the Neo4j driver and a graph-capable frontend such as Cytoscape.js. The exact framework can vary; the API contract matters more than the framework.

The MVP should have four views:

1. **Disease overview:** name, MONDO ID, genes, studies, organizations, and a short evidence list.
2. **Evidence panel:** source URL, assertion level, confidence, notes, and the relationship being supported.
3. **Research graph:** a small, filtered neighborhood around one selected disease. Start with curated links and let users turn inferred links on.
4. **Similarity explorer:** protein or gene candidates ranked by method and score, with a visible label such as “computational research lead.”

Avoid showing the entire graph as a force-directed hairball. Start from one disease, limit the first expansion to one or two hops, group by node type, and open the source evidence in a side panel. Use different styles for curated versus inferred edges and always show the source and score behind a result.

## Suggested API response shape

The frontend should receive normalized graph data rather than raw Neo4j records:

```json
{
  "nodes": [
    {"id": "MONDO:0018149", "kind": "Disease", "label": "GM1 gangliosidosis"}
  ],
  "edges": [
    {
      "id": "REL-01",
      "type": "RESEARCH_NEIGHBOR",
      "source": "MONDO:0018149",
      "target": "MONDO:0017720",
      "assertion_level": "inferred",
      "confidence": "medium",
      "evidence_id": "E-04"
    }
  ]
}
```

Useful read-only endpoints are:

```text
GET /diseases/{mondo_id}/overview
GET /diseases/{mondo_id}/graph?depth=1&include_inferred=false
GET /diseases/{mondo_id}/evidence
GET /diseases/{mondo_id}/similarity?method=blastp
GET /studies/{nct_id}
```

The API should keep query logic and credential handling on the server. The frontend should handle layout, filters, labels, and evidence presentation.

## Handoff checklist

Before adding new graph features, confirm that:

1. New nodes have stable IDs and a source URL.
2. New edges have an assertion level, evidence ID, confidence, and notes.
3. Inferred or similarity relationships are visually distinct from curated biology facts.
4. The UI can open the source evidence for every displayed relationship.
5. The existing graph acceptance queries still return the expected paths.
