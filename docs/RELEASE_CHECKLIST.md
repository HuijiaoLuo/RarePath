# Release checklist

Run these steps in order before publishing a version of RarePath. Each step says how to check it.

## 1. Data is complete and current

```bash
python pipelines/build_atlas.py            # or --offline to rebuild from cached downloads only
python pipelines/fetch_clinvar_variants.py --offline
python graph/export_graph_json.py
```

- The ClinVar step must not print any `Note:` lines. Its manifest (`data/manifests/gene_variants_v0.1.json`) must have `"problems": []`.
- `python pipelines/check_cluster_benchmark.py` must end with `23/23 checks pass`.

## 2. Tests pass, and public numbers match the data

```bash
python -m pip install networkx             # the only package the tests need
python -m unittest
```

- `tests/test_published_numbers.py` compares the counts in the README, case study and docs with the committed data. If a rebuild changes a count, update the text, never the test.
- On machines where the system temp folder is not writable, set a writable one first, e.g. `export RAREPATH_TEST_TMP=$PWD/.tmp-tests`.
- Without networkx, the clustering tests are reported as **skipped**, not failed. A release needs them to run: the expected result is all tests passed and **0 skipped**.

## 3. The chat eval passes, and the build is frozen

```bash
python evals/run_chat_eval.py                       # offline answers: every case must pass
python evals/run_chat_eval.py --live --save         # optional, with your key: records the model's result
python pipelines/freeze_candidate.py --name demo-candidate-1
```

See [DEMO_CANDIDATE.md](DEMO_CANDIDATE.md).

## 4. Claims are labelled honestly

- The 10× case is a **hypothesis** until it is tested with a patient group (`docs/TEN_X_CASE.md`).
- The ClinVar and AlphaFold pattern is **descriptive** (`docs/GENE_AND_VARIANT_LAYER.md`).
- Screenshots in `docs/img/` and `demo/img/` show the current version.

## 5. Repository

```bash
git fetch origin && git status -sb      # nothing new on GitHub that you have not pulled
git status                              # no data/raw, .env, credentials, file.pdf or "Claude outputs/"
python pipelines/freeze_candidate.py --check
git add -A && git commit && git push
```

- The published site is the `demo/` folder (`index.html` is the case study, `explore.html` the app).
- A push that changes `demo/` republishes the site through `.github/workflows/pages.yml`, so freeze and check a candidate before pushing changes there.
- Confirm the Tests badge turns green on GitHub after pushing.

## 6. Before making AI answers public

The site is published **static only** (decided 2026-10-07): GitHub Pages serves `demo/`, the chat answers offline, and no key or model is involved. Before a hosted version with live AI answers, do these first:

- **Choose the AI model again.** The chat uses `gpt-5` with the owner's key. That is fine for a local demo, but too costly to put in front of anyone with a link. Either publish the site **static only** (offline answers, no key, no cost), or run the API with a smaller model set through `OPENAI_MODEL`, behind a monthly spend cap, rate limits and a separate project key.
- **Re-run the chat eval on the chosen model**, and read every answer:
  ```bash
  OPENAI_MODEL=<model> python evals/run_chat_eval.py --live --save
  ```
  Add the run to `tests/fixtures/eval/` with your own verdict for each answer. The results so far are for gpt-5 only and say nothing about another model.
- Freeze a new demo candidate (`python pipelines/freeze_candidate.py --name ...`).
