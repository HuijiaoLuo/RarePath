# Changelog

What changed, and why. Scoring versions are recorded in each run's manifest (`data/manifests/`).

## First test on the hosted site (2026-10-07)

- **Found by using the site: an answer about the wrong disease.** While viewing Bardet-Biedl syndrome, the question "What is the life expectancy for GM1?" was answered from Bardet-Biedl's facts. The page answers only from the facts of the disease on screen, but did not notice that the question was about another one.
  - The page now checks whether a question names a disease the facts on screen do not mention. If it does, it offers "Switch to GM1 gangliosidosis and ask" or "Answer about Bardet-Biedl syndrome anyway" instead of answering.
  - The check runs before any model call, so it protects AI answers too. Two eval cases (Q16, Q17) keep it working. None of the page's own suggested questions, across all 51 diseases, triggers it.
- Wording: "caused by changes in the BBS1, BBS10 and BBS2 genes" (was "gene"), "ciliopathies" (was "ciliopathys"), and "RarePath rates the link between A and B as …" (was "A has a "handle with care" with B").

## Published as a static site (2026-10-07)

- `demo/` is published on GitHub Pages ([open the app](https://huijiaoluo.github.io/RarePath/explore.html)). It is the static mode only: offline answers, no key and no server, so no model or spending decision was needed yet. Live AI answers stay local; section 6 of the release checklist lists what a hosted AI version needs first.
- The README links point to the site again, and the Tests badge names the branch so it shows the current status.

## Not deployed yet (2026-10-05)

- The README no longer links to a hosted site that does not exist; it says how to open the app locally. Publishing now has its own checklist step, which starts with choosing a cheaper model for public AI answers and re-running the chat eval on it.

## First live chat eval (2026-10-05)

- **gpt-5 scored 8/15, but reading the answers showed most failures were the scorer's.** Its "don't know" check had been written against the offline answers' wording, so it missed "the facts here don't give a number" and similar phrasings. It also flagged "we cannot tell whether your daughter can join" as a forbidden claim.
  - The scorer now recognises more ways of saying "the facts do not contain this". It uses the model's `answered_from_facts` flag, ignores forbidden phrases in a negated clause, and normalises curly apostrophes.
  - It is now tested against the 15 real answers, each judged by hand (`tests/fixtures/eval/`), and must agree with every verdict.
- **One real gap.** For three treatment questions (Tay-Sachs therapy for GM1, MEK inhibitors, Prader-Willi treatments), the model was careful but never said the decision belongs to the family's doctor. Treatment questions now check for that. The system prompt now asks the model to say first that RarePath cannot decide, and who can, and to mark answers the facts do not cover.
- **Second live run: 14/15, and on reading, 15/15 acceptable.** All three treatment answers now say first that RarePath cannot decide and name the doctor or study team; questions outside the graph now set `answered_from_facts` to false. The one failure was the scorer again: "it is risky to assume the same treatments will help" is a warning, so hedged clauses now count like negated ones. This run is the second hand-labelled fixture.
- Live results are saved one file per run, so the baseline (`evals/results/gpt-5_2026-10-05.json`) is kept for comparison.

## Demo candidate (2026-10-05)

- **Protein comparison in the gene panel.** The sequence alignment and AlphaFold superposition, previously only in the method notes, now appear where people read about a gene. HEXA–HEXB shows as closely related; other pairs show "no detectable match" and "shape not evaluated", with a note that this is not evidence the shapes differ, and that the method is a sequence-guided comparison of predicted models, not a structure search or a clinical measure.
- Fixed: the protein method notes said coverage was measured on the shorter protein. The code uses the lower of the two coverages, which is the longer protein's.
- **Chat evaluation set** (`evals/`): 15 question cases and 5 system cases. The first run failed 6 of 15 offline answers: questions about life expectancy, prevalence, hospitals, joining a study and a MEK inhibitor got a generic summary instead of "RarePath cannot answer that". The offline answers now recognise these questions, and a disease name only counts as "named" if it is not the disease being viewed. All 20 cases pass; a test keeps it that way.
- **Feedback review statuses**: new, reviewing, confirmed_issue, rejected, fixed_in_next_graph. Decisions are appended to `data/curated/feedback_decisions.csv`; an item marked fixed closes only once the graph version changes.
- **Demo candidate freeze** (`pipelines/freeze_candidate.py`): records the graph version, results and file checksums, and refuses to freeze unless every check, test and eval case passes. `--check` reports any drift.
- Added `docs/DEMO_CANDIDATE.md` and `docs/USER_TEST_PROTOCOL.md`; `docs/ARCHITECTURE.md` now states what static and API modes support and what is never saved.

## Feedback, history and graph versions (2026-10-05)

- **Graph version.** Each export now carries a fingerprint of the graph's content and the method and source dates behind it. The page footer shows it, and AI answers and feedback records name it. CSV and Neo4j copies of the same graph get the same version, and a test checks this.
- **Feedback without health data.** Each evidence, link, gene and study panel, and each answer, has one-tap feedback with fixed categories. The local server validates it (known record IDs only, no free text, no IP address, rate-limited) and appends it to a git-ignored file. `pipelines/review_feedback.py` turns it into a review queue; feedback never edits the graph. A static copy offers a prefilled public GitHub issue instead.
- **Recently viewed, on this device only.** Up to six disease IDs are kept in the browser, and the page reopens the last one. "Forget" clears them.
- Added `docs/ARCHITECTURE.md`.

## Release preparation (2026-10-05)

- **An external review found the published variant counts did not match the data.** The data had 2,014 variants in 30 genes; the text said 2,633 in 32.
  - **Cause:** an offline re-run could not find two ClinVar batches that had been split on an earlier run (FGD1, GLA), so it skipped those genes.
  - **Fix:** split batches are now found from their halves, with a regression test.
- **New test, `tests/test_published_numbers.py`.** It checks the counts in the README, case study and docs against the committed data and manifests, so text and data cannot drift apart again.
- **Test environment.** The tests now report missing networkx as *skipped*, not as errors. They also accept a writable temp folder (`RAREPATH_TEST_TMP`), so environment problems are not mistaken for defects.
- **The 10× case is labelled as a hypothesis** everywhere it appears, pending validation with patient groups.
- Added `docs/RELEASE_CHECKLIST.md`.

## Gene, protein and variant layer (2026-10-05)

- **Gene panel.** Clicking a gene name shows:
  - the protein's UniProt function and location;
  - the diseases the gene causes in RarePath;
  - its Reactome processes and similar proteins;
  - a rotatable AlphaFold model coloured by confidence.

  The viewer is a small canvas script with no external library ([details](docs/GENE_AND_VARIANT_LAYER.md)).
- **ClinVar variants on the structure.** Pathogenic and likely pathogenic missense variants are drawn on the model. A variant is kept only when its reference amino acid matches the model's sequence. The panel compares how often variant positions fall in very-high-confidence regions with how often the whole protein does, and says this is descriptive, not a finding.
- Fixed: GLB1's summary showed the function of a minor isoform (an elastin-binding protein). Only the canonical isoform is now used.
- **Fixed after the first full ClinVar run** (1,507 variants in 32 genes). Reviewing the per-gene counts showed three problems:
  - **Too-strict gene filter.** GLA, GBA1, HRAS and ASPA had no variants, because ClinVar also lists overlapping genes for them. The filter now checks the gene in the variant's preferred name.
  - **Numbering shift.** 182 ARSA variants were rejected because ClinVar's transcript numbers ARSA 2 residues higher than UniProt. A per-gene shift is now detected and applied when it explains at least 90% of the variants.
  - **Cached errors.** Two oversized batches came back as NCBI error messages and were cached. Such batches are now split and retried, and errors are never cached.
- **Re-run: 2,633 variants at 1,549 positions in 32 proteins.**
  - The pooled shares (84% of variant positions in very-high-confidence regions against 55% of residues) mix genes with very different baselines. The summary now compares observed with expected within each gene: 1,301 against 1,170.1, a ratio of 1.11 and a z of 9.7 under a hypergeometric null.
  - By family: lysosomal 1.09, RASopathies 1.09, ciliopathies 1.53.
  - An earlier impression that RASopathy variants as a whole avoid confident regions did not hold up. Only RAF1 and SOS1 do.

## Evidence map and clean-up (2026-10-04)

- **Evidence map** redrawn as a radial SVG map in the guide's colours, with studies and patient groups on an outer ring. "All communities" is now a set of cards. The Cytoscape dependency is gone.
- The guide sends the AI a fact about the disease's own family, so "what kind of disease is this?" no longer cites an unrelated link.
- Documentation reorganised for readers of a portfolio. Early planning notes moved to `docs/archive/`.

## Scoring v0.4: shared disease class as a weak link (2026-10-04)

- **Why.** All 12 predictions for the new families held, but reviewing every pair found true relatives labelled as look-alikes.
  - Noonan 5 (RAF1) vs LEOPARD 1 (PTPN11): one cascade, but Reactome files the two steps in different pathways.
  - Joubert 2 vs Meckel 4.
- **Change.** Diseases in the same mechanism-defined MONDO class (lysosomal storage disease, RASopathy, ciliopathy) get a mechanism floor of 0.15. It stops a "look-alike" label but never creates a neighbour or merges communities.
- **Result.** Only two pairs remain look-alikes, Krabbe–Canavan and Bardet-Biedl 1–Prader-Willi, both involving counterexamples placed on purpose. The third designed counterexample, Aarskog-Scott, is `not_linked` to Noonan 1: its symptom overlap is only at the 54th percentile, below the top-quarter gate. Three new checks guard the fix and are marked as added after review. 23/23 checks pass.

## Scoring v0.3: RASopathies and ciliopathies (2026-10-04)

- The panel grew from 20 to 43 diseases in three families.
- Pathway rarity and symptom percentiles are now measured within each family, so all 190 original lysosomal pairs stayed identical (guarded by a test).
- Curated causal genes (e.g. Noonan 1 = PTPN11) and MONDO disease series (Noonan, Bardet-Biedl, Joubert, Meckel).
- Twelve predictions were written down before scoring, and all held on the first run with real data.
- Hand-checked studies and patient groups for the new families, each with its check date.

## Scoring v0.2 (2026-10-03)

- v0.1 passed 6 of 8 known-biology checks: it split the GM2 diseases and called Morquio B "similar" to GM1.
- Fixed with general rules:
  - shared MONDO disease series as a mechanism signal;
  - a cap on pathways shared by most genes;
  - lab findings excluded from the symptom score;
  - relation classes drive the guide's labels.
- 8/8 checks pass.

## First version (2026-10-03)

- GM1/GM2 seed graph from MONDO, ClinVar and ClinicalTrials.gov, loaded into Neo4j.
- Conversation-first guide with sourced evidence panels, a grounded OpenAI chat with an offline fallback, the 10× case and protein similarity for the four GM1/GM2 genes.
