from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.engine import KnowledgeEngine
from app.models import RuleInput
from app.store import KnowledgeStore


def main() -> None:
    payload = json.loads(Path("data/seed_expertise.json").read_text())
    store = KnowledgeStore(settings.db_path)
    store.init()
    engine = KnowledgeEngine(store)

    for item in payload["example_rules"]:
        result = engine.capture_rule(
            RuleInput(
                topic=payload["demo_topic"],
                conditions=item["conditions"],
                action=item["action"],
                rationale=item["rationale"],
                source_quote=item["rationale"],
                expert=payload["expert"],
                confidence=0.95,
            )
        )
        print(result["rule"]["id"], result["rule"]["action"])


if __name__ == "__main__":
    main()
