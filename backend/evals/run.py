from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from app.agents import SYSTEM, model

ModelAdapter = Callable[[list[dict]], dict]


@dataclass(frozen=True)
class Grade:
    case: str
    score: float
    passed: bool
    reasons: tuple[str, ...]
    tools: tuple[str, ...]


def load_cases(path: Path | None = None) -> list[dict]:
    cases = json.loads((path or Path(__file__).with_name("cases.json")).read_text())
    if len(cases) != 9 or len({case["name"] for case in cases}) != len(cases):
        raise ValueError("Evaluation suite must contain nine uniquely named cases")
    return cases


def prompt_for(case: dict, system_prompt: str = SYSTEM) -> list[dict]:
    # Exposing the candidate prompt lets an offline adapter score hill-climb variants.
    content = f"<system>{system_prompt}</system>\n{json.dumps(case['context'])}\n\nTake the next step and finish with end_step."
    return [{"role": "user", "content": content}]


def tool_uses(response: dict) -> list[dict]:
    return [block for block in response.get("content", []) if block.get("type") == "tool_use"]


def grade(case: dict, response: dict) -> Grade:
    calls = tool_uses(response)
    names = [call.get("name", "") for call in calls]
    rules, reasons, checks = case["expect"], [], []

    def check(ok: bool, reason: str) -> None:
        checks.append(ok)
        if not ok:
            reasons.append(reason)

    required, forbidden = rules.get("required_any", []), rules.get("forbidden", [])
    check(not required or any(name in names for name in required), f"requires one of {required}")
    check(not any(name in names for name in forbidden), f"forbids {forbidden}")
    check(bool(names) and names[-1] == "end_step", "must finish with end_step")
    check(len(names) <= rules.get("max_calls", 4), "too many tool calls")
    for before, after in rules.get("order", []):
        check(before in names and after in names and names.index(before) < names.index(after), f"{before} must precede {after}")
    for tool_name, fields in rules.get("required_inputs", {}).items():
        matching = [call.get("input", {}) for call in calls if call.get("name") == tool_name]
        check(bool(matching) and all(str(matching[0].get(field, "")).strip() for field in fields), f"{tool_name} needs {fields}")

    hard_failure = any(name in names for name in forbidden)
    score = 0.0 if hard_failure else sum(checks) / len(checks)
    return Grade(case["name"], score, score == 1.0, tuple(reasons), tuple(names))


def evaluate(adapter: ModelAdapter, cases: Iterable[dict] | None = None, system_prompt: str = SYSTEM) -> list[Grade]:
    return [grade(case, adapter(prompt_for(case, system_prompt))) for case in (cases or load_cases())]


def mean_score(grades: Iterable[Grade]) -> float:
    values = list(grades)
    return sum(item.score for item in values) / len(values) if values else 0.0


def hill_climb(adapter: ModelAdapter, candidates: Iterable[str], cases: Iterable[dict] | None = None) -> tuple[str, list[Grade]]:
    """Choose the best explicit prompt suffix; the supplied adapter owns all inference."""
    suite = list(cases or load_cases())
    best_prompt, best_grades = SYSTEM, evaluate(adapter, suite, SYSTEM)
    for suffix in candidates:
        candidate = f"{SYSTEM}\n{suffix.strip()}"
        grades = evaluate(adapter, suite, candidate)
        if mean_score(grades) > mean_score(best_grades):
            best_prompt, best_grades = candidate, grades
    return best_prompt, best_grades


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the nine-case nous agent evaluation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    grades = evaluate(model)
    if args.json:
        print(json.dumps({"score": mean_score(grades), "cases": [asdict(item) for item in grades]}, indent=2))
    else:
        for item in grades:
            print(f"{'PASS' if item.passed else 'FAIL'} {item.case}: {item.score:.0%} {'; '.join(item.reasons)}")
        print(f"score={mean_score(grades):.1%}")
    if not all(item.passed for item in grades):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
