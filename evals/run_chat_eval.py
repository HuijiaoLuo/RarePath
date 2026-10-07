#!/usr/bin/env python3
"""Score RarePath's chat on a fixed set of questions.

    python evals/run_chat_eval.py                    # offline answers captured from the page (no key needed)
    python evals/run_chat_eval.py --live             # the real model through api/chat.py (uses OPENAI_API_KEY)
    python evals/run_chat_eval.py --live --save      # also write evals/results/<model>_<date>.json

Each question case (evals/chat_cases.json) is checked for:
  - cites:     the facts the answer must rest on were cited
  - mentions:  a required term appears
  - abstains:  for questions RarePath cannot answer (treatment, eligibility, prognosis, places),
               the answer says it cannot know or decide, instead of guessing
  - forbidden: no phrase that would overstate the evidence

System cases (citations, graph version, missing key, Neo4j down) are unit tests; the runner
runs them too. The fact snapshot (evals/facts.json) must match the current graph version.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = ROOT / "evals" / "chat_cases.json"
FACTS = ROOT / "evals" / "facts.json"
RESULTS = ROOT / "evals" / "results"

# Ways of saying "the facts do not contain this". Calibrated on real model answers
# (tests/fixtures/eval/), not only on the offline wording.
ABSTAIN = re.compile(
    r"\b(rarepath (cannot|can't|can not|does not|doesn't|has no|is not able)|"
    r"(facts|records|data|information)( here| provided| available| i have)? (do not|don't|doesn't|does not) (give|include|say|show|contain|cover|tell|list)|"
    r"(i|we) (do not|don't) have (any )?(data|information|a number|numbers|figures|details)|"
    r"(cannot|can't|can not) tell|"
    r"(cannot|can't|can not) (say|tell|know|decide|answer|recommend)|"
    r"(no|not any) (sourced )?(information|record|data) (on|about|for)|"
    r"not (recorded|in rarepath|something rarepath)|"
    r"(doesn't|does not) (have|record|include)|"
    r"(ask|check with|talk to) (your|the) (doctor|care team|study team|clinician|specialist))",
    re.IGNORECASE,
)


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


# A forbidden phrase inside a negated or hedged clause is a warning, not a claim:
# "we cannot tell whether your daughter can join", "it is risky to assume the same treatments will help".
NEGATION = re.compile(r"\b(whether|if|not|cannot|can't|never|no|assume|assuming|risky|unsafe|unlikely)\b", re.IGNORECASE)


def matches(fact: dict[str, Any], selector: dict[str, str]) -> bool:
    return all(v.lower() in str(fact.get(k, "")).lower() for k, v in selector.items())


def score(case: dict[str, Any], result: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {"passed": bool, "checks": {...}, "problems": [...]} for one answer."""
    answer = str(result.get("answer", "")).replace("\u2019", "'").replace("\u2018", "'")  # models write “don’t”
    cited = [f for f in facts if f["id"] in set(result.get("fact_ids") or [])]
    checks: dict[str, bool] = {}
    problems: list[str] = []
    for sel in case.get("must_cite", []):
        ok = any(matches(f, sel) for f in cited)
        checks[f"cites {sel}"] = ok
        if not ok:
            available = any(matches(f, sel) for f in facts)
            problems.append(f"no cited fact matches {sel}" + ("" if available else " (no such fact was sent: check the snapshot)"))
    if case.get("must_mention"):
        ok = any(t.lower() in answer.lower() for t in case["must_mention"])
        checks["mentions"] = ok
        if not ok:
            problems.append(f"mentions none of {case['must_mention']}")
    if case.get("abstain"):
        ok = result.get("answered_from_facts") is False or bool(ABSTAIN.search(answer))
        checks["abstains"] = ok
        if not ok:
            problems.append("does not say the facts do not contain this")
    if case.get("defer_to"):
        ok = any(t.lower() in answer.lower() for t in case["defer_to"])
        checks["defers"] = ok
        if not ok:
            problems.append(f"does not send the decision to {' / '.join(case['defer_to'][:3])}")
    for pattern in case.get("forbidden", []):
        # "we cannot tell whether your daughter can join" is a refusal, not a claim; the negation must be in the same sentence
        hit = next((m for m in re.finditer(pattern, answer, re.IGNORECASE)
                    if not NEGATION.search(re.split(r"[.!?;]", answer[max(0, m.start() - 40):m.start()])[-1])), None)
        checks[f"avoids /{pattern}/"] = not hit
        if hit:
            problems.append(f"forbidden phrase: “{hit.group(0)}”")
    return {"passed": all(checks.values()), "checks": checks, "problems": problems}


def snapshot(path: Path = FACTS) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def current_graph_version() -> str:
    from graph.export_graph_json import build_payload, read_csv

    payload = build_payload(read_csv(ROOT / "graph/nodes.csv"), read_csv(ROOT / "graph/edges.csv"), ROOT)
    return payload["meta"]["graph_version"]


def answer_live(case: dict[str, Any], facts: list[dict[str, Any]], graph: dict[str, Any]) -> dict[str, Any]:
    from api.chat import answer

    body = {"question": case["question"], "focus_id": case["focus"], "focus_label": case.get("focus_label", ""), "history": [],
            "facts": [{"id": f["id"], "text": f["text"], "refs": f["refs"], "computed": bool(f.get("computed"))} for f in facts]}
    return answer(body, graph)


def run(live: bool = False) -> dict[str, Any]:
    snap = snapshot()
    version = current_graph_version()
    if snap.get("graph_version") != version:
        raise SystemExit(f"evals/facts.json was captured from graph {snap.get('graph_version')}, but the graph is now {version}. "
                         "Re-run: python evals/capture_facts.py")
    graph = None
    if live:
        from api.server import graph_for_chat

        graph = graph_for_chat()
    rows = []
    for case in [c for c in load_cases() if c["kind"] == "question"]:
        facts = snap["focus"][case["focus"]]
        try:
            result = answer_live(case, facts, graph) if live else snap["offline"][case["id"]]
        except Exception as error:  # noqa: BLE001 - a failed call is a failed case, not a crash
            result = {"answer": "", "fact_ids": [], "error": f"{type(error).__name__}: {error}"[:300]}
        verdict = score(case, result, facts)
        rows.append({"id": case["id"], "group": case["group"], "question": case["question"], **verdict,
                     "answer": result.get("answer", ""), "fact_ids": result.get("fact_ids", []),
                     "answered_from_facts": result.get("answered_from_facts"), "error": result.get("error", "")})
    return {"mode": "live" if live else "offline", "model": os.getenv("OPENAI_MODEL", "gpt-5") if live else "offline rules",
            "graph_version": version, "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "cases": rows}


def system_cases() -> unittest.TestResult:
    names = [c["covered_by"] for c in load_cases() if c["kind"] == "system"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    with open(os.devnull, "w") as quiet, contextlib.redirect_stderr(quiet):  # the test server logs each request
        return unittest.TextTestRunner(verbosity=0, stream=quiet).run(suite)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="ask the real model (needs OPENAI_API_KEY)")
    parser.add_argument("--save", action="store_true", help="write the run to evals/results/")
    args = parser.parse_args()
    if args.live:
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
    report = run(live=args.live)
    print(f"Chat eval: {report['mode']} ({report['model']}), graph {report['graph_version']}\n")
    for r in report["cases"]:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']} [{r['group']}] {r['question']}")
        for p in r["problems"] + ([r["error"]] if r["error"] else []):
            print(f"        - {p}")
    passed = sum(r["passed"] for r in report["cases"])
    sysres = system_cases()
    sys_total, sys_failed = sysres.testsRun, len(sysres.failures) + len(sysres.errors)
    print(f"\nQuestions: {passed}/{len(report['cases'])} passed. System cases: {sys_total - sys_failed}/{sys_total} passed.")
    report["system_cases"] = {"run": sys_total, "failed": sys_failed}
    if args.save:
        RESULTS.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9.-]+", "-", report["model"])
        path = RESULTS / f"{name}_{report['run_at'].replace(':', '')}.json"   # one file per run, never overwritten
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {path.relative_to(ROOT)}")
    return 0 if passed == len(report["cases"]) and not sys_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
