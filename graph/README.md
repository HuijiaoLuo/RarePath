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

Install the Python driver, then set the connection variables for the Neo4j instance you already created and run:

~~~bash
python -m pip install neo4j
export NEO4J_URI='neo4j+s://<instance>.databases.neo4j.io'
export NEO4J_USER='<username>'
export NEO4J_PASSWORD='<password>'
export NEO4J_DATABASE='<database>'
python graph/load_neo4j.py --load
~~~

On Windows Git Bash, keep the credentials in a local, ignored file or set the four variables for the current shell. Do not commit the credential file or put the password in tracked documentation. The loader also accepts `NEO4J_USERNAME` as an alias for `NEO4J_USER`.

The MVP deliberately uses a generic Entity label and a kind property. This keeps the import safe and lets the API expose consistent node data while the domain model is still evolving.

Do not interpret RESEARCH_NEIGHBOR or RESOURCE_NEIGHBOR as treatment equivalence. They are research-navigation relationships and must display their supporting evidence.
