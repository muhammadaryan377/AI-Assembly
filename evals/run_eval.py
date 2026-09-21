from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine import KnowledgeEngine
from app.models import RuleInput
from app.store import KnowledgeStore


def build_engine() -> KnowledgeEngine:
    temp_dir = tempfile.TemporaryDirectory()
    store = KnowledgeStore(Path(temp_dir.name) / "eval.db")
    store.init()
    engine = KnowledgeEngine(store)
    engine._eval_temp_dir = temp_dir  # keep directory alive for the run

    seed = json.loads((ROOT / "data/seed_expertise.json").read_text())
    for item in seed["example_rules"]:
        engine.capture_rule(
            RuleInput(
                topic=seed["demo_topic"],
                conditions=item["conditions"],
                action=item["action"],
                rationale=item["rationale"],
                source_quote=item["rationale"],
                expert=seed["expert"],
                confidence=0.95,
            )
        )
    return engine


def main() -> None:
    engine = build_engine()
    scenarios = json.loads((ROOT / "evals/scenarios.json").read_text())

    correct = 0
    unsupported = 0
    rows = []

    for scenario in scenarios:
        result = engine.retrieve_guidance(
            scenario["topic"],
            scenario["observations"],
        )
        match = result["match"]
        expected = scenario["expected_action_contains"]

        if expected is None:
            passed = match is None
            unsupported += int(match is not None)
            predicted = match["rule"]["action"] if match else "NO MATCH"
        else:
            predicted = match["rule"]["action"] if match else "NO MATCH"
            passed = bool(match and expected.lower() in predicted.lower())

        correct += int(passed)
        rows.append((scenario["id"], "PASS" if passed else "FAIL", predicted))

    total = len(scenarios)
    accuracy = correct / total if total else 0
    unsupported_rate = unsupported / total if total else 0

    print("\nTacitOS deterministic retrieval evaluation")
    print("=" * 62)
    for sid, status, predicted in rows:
        print(f"{sid:<8} {status:<6} {predicted}")
    print("-" * 62)
    print(f"Scenario accuracy:         {accuracy:.1%}")
    print(f"Unsupported guidance rate: {unsupported_rate:.1%}")
    print(f"Scenarios:                 {total}")

    if correct != total or unsupported != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
