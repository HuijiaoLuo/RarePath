# Graph layer

The graph layer converts the normalized seed data into a small evidence-backed graph. The CSV files are the source-controlled input; Neo4j is a query and visualization layer.

## Files

- nodes.csv: graph nodes and stable/provisional identities.
- edges.csv: relationships with assertion level, evidence ID, confidence, and source URL.
- schema.md: node, relationship, and acceptance rules.
- load_neo4j.py: standard-library dry-run validator and optional Neo4j loader.

## Dry-run validation

From the repository root:

~~~bash
python graph/load_neo4j.py
~~~

This checks duplicate IDs, missing endpoints, invalid relationship names, and missing evidence nodes without requiring Neo4j.

## Neo4j loading

Install the Python driver, start a local Neo4j instance, then set NEO4J_PASSWORD and run:

~~~bash
python -m pip install neo4j
python graph/load_neo4j.py --load
~~~

The MVP deliberately uses a generic Entity label and a kind property. This keeps the import safe and lets the API expose consistent node data while the domain model is still evolving.

Do not interpret RESEARCH_NEIGHBOR or RESOURCE_NEIGHBOR as treatment equivalence. They are research-navigation relationships and must display their supporting evidence.
