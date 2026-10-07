# Demo candidate

RarePath is not published yet. Before any user test or recording, the current build is frozen as a **demo candidate**: one graph version, one set of files, and the results that were true for them. Every user-test session, screenshot and chat-eval run then names the candidate it used, so findings can be traced back to exactly what people saw.

## Freeze a candidate

```bash
python graph/export_graph_json.py           # page data matches the graph CSVs
python evals/capture_facts.py               # only if the graph or the page changed (needs Playwright)
git add -A && git commit                    # so the record can name the commit
python pipelines/freeze_candidate.py --name demo-candidate-1
git add docs/demo_candidate.json && git commit -m "Freeze demo-candidate-1"
```

`freeze_candidate.py` refuses to write a record unless all of these hold:

| Check | Required |
| --- | --- |
| Page data | `demo/data/graph.js` carries the same graph version as `graph/*.csv` |
| Biology checks | 23/23 pass |
| ClinVar manifest | `problems: []` |
| Tests | all pass, 0 skipped (networkx installed) |
| Chat eval, offline | every question case passes (`evals/run_chat_eval.py`) |

The record, `docs/demo_candidate.json`, holds:

- the graph version and what it was built from (method version and source dates);
- node, edge, check, test and eval counts;
- the SHA-256 of every file a visitor sees or a result depends on: the two pages, the graph and structure data, the graph CSVs, the curated tables, the manifests, the eval set and the screenshots;
- the Python version and git commit.

## Check that nothing has drifted

```bash
python pipelines/freeze_candidate.py --check
```

This lists any changed, missing or new tracked file, and any change of graph version. Run it before each user-test session. If it reports drift, either restore the candidate or freeze a new one and note the change in the session log.

## What a candidate is not

- It is not a deployment by itself. GitHub Pages publishes whatever `demo/` holds on `main`, so freeze and `--check` before pushing changes to `demo/`. Static mode and API mode are described in [ARCHITECTURE.md](ARCHITECTURE.md#two-ways-to-run-it).
- A live chat-eval run (`python evals/run_chat_eval.py --live --save`) is recorded separately in `evals/results/`, because it depends on the model as well as the candidate. The saved result names the graph version.
