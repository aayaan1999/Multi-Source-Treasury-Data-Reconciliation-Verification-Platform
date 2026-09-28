"""Scores the real model on the golden questions (specs/ask-a-question.md section 11.3).

    backend/.venv/Scripts/python.exe scripts/eval_ask.py [--only N] [--file backend/tests/ask_questions_holdout.json]

Reads LLM_BASE_URL / LLM_MODEL (/ LLM_API_KEY) from backend/.env - the laptop's Ollama, or a vLLM
server - and runs every question in backend/tests/ask_questions.json through the same steps as the
app: model -> text extraction -> merge. No database needed: branch/product names come from the file.

Prints, per question, whether the outcome was right, and a summary:
  * right entry   - the model picked the expected catalogue entry (or unsupported)
  * fully right   - entry, status and filters all as expected
  * wrong answer  - a table would have been shown with the wrong entry or filters (the number that
                    must be 0 before go-live: a wrong answer should become a clarify, never a table)
"""
import argparse
import json
import os
import pathlib
import sys
import time
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

for line in (ROOT / "backend" / ".env").read_text(encoding="utf-8").splitlines():
    key, sep, value = line.partition("=")
    if sep and not line.lstrip().startswith("#") and key.strip() not in os.environ:
        os.environ[key.strip()] = value.strip().strip("\"'")

from app.ask import llm, service, vocab  # noqa: E402
from app.ask.extract import extract  # noqa: E402

STRICT = ("countries", "regions", "branches", "segments", "products", "stages", "tables", "date_from", "date_to", "top_n")


def same(got: dict, case: dict) -> bool:
    if got["status"] != case["status"]:
        return False
    if case["status"] == "unsupported":
        return True
    if got.get("query") != case["query"]:
        return False
    if case["status"] != "answer":
        return True
    want, filters = case["filters"], got["filters"]
    norm = lambda v: sorted(v) if isinstance(v, list) else v
    return all(norm(filters.get(k)) == norm(v) for k, v in want.items()) and all(k in want for k in STRICT if k in filters)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, help="first N questions only")
    parser.add_argument("--file", default=str(ROOT / "backend" / "tests" / "ask_questions.json"),
                        help="question file (e.g. backend/tests/ask_questions_holdout.json)")
    args = parser.parse_args()
    path = pathlib.Path(args.file)
    golden = json.loads(path.read_text(encoding="utf-8"))
    if "names_from" in golden:     # the held-out file reuses the golden file's bank names
        golden["names"] = json.loads((path.parent / golden["names_from"]).read_text(encoding="utf-8"))["names"]
    vocab.names = lambda: golden["names"]
    today = date.fromisoformat(golden["today"])
    cases = golden["cases"][: args.only] if args.only else golden["cases"]
    print(f"Model {llm.model_name()} at {os.environ.get('LLM_BASE_URL')}, {len(cases)} questions\n")

    llm.classify("warm up")          # the first call loads the model; don't count it
    right_entry = fully_right = wrong_answer = 0
    times = []
    for case in cases:
        started = time.monotonic()
        model = llm.classify(case["q"])
        times.append(time.monotonic() - started)
        got = service.merge(model, extract(case["q"], today, golden["names"]))
        entry_ok = (model.get("query") == "unsupported") if case["status"] == "unsupported" else model.get("query") == case["query"]
        ok = same(got, case)
        right_entry += entry_ok
        fully_right += ok
        wrong = got["status"] == "answer" and not ok
        wrong_answer += wrong
        mark = "OK   " if ok else ("WRONG" if wrong else "miss ")
        print(f"{mark} {times[-1]:4.1f}s  {case['q'][:48]:48}  model={model.get('query')}/{model.get('metric')}"
              f"  -> {got['status']} {got.get('query', '')} {json.dumps(got.get('filters', {}), ensure_ascii=False)[:90]}")
    n = len(cases)
    print(f"\nRight entry:  {right_entry}/{n} ({100 * right_entry / n:.0f}%)")
    print(f"Fully right:  {fully_right}/{n} ({100 * fully_right / n:.0f}%)")
    print(f"Wrong answer shown as a table: {wrong_answer}/{n}")
    print(f"Time per question: average {sum(times) / n:.1f}s, slowest {max(times):.1f}s")


if __name__ == "__main__":
    main()
