from __future__ import annotations

from typing import Any

from app.engine import KnowledgeEngine
from app.models import ResolutionInput, RuleInput
from app.store import KnowledgeStore


class ToolDispatcher:
    def __init__(self, store: KnowledgeStore):
        self.store = store
        self.engine = KnowledgeEngine(store)

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "capture_expert_rule":
            payload = RuleInput(**arguments)
            return self.engine.capture_rule(payload)

        if name == "inspect_knowledge_state":
            return self.engine.inspect_knowledge_state(str(arguments.get("topic", "")))

        if name == "retrieve_expert_guidance":
            return self.engine.retrieve_guidance(
                str(arguments.get("topic", "")),
                dict(arguments.get("observations", {})),
            )

        if name == "resolve_knowledge_conflict":
            payload = ResolutionInput(**arguments)
            resolved = self.store.resolve_conflict(
                payload.conflict_id,
                payload.resolution,
                payload.differentiating_condition,
            )
            if not resolved:
                return {"status": "not_found", "conflict_id": payload.conflict_id}
            self.store.add_audit(
                "conflict.resolved",
                {
                    "conflict_id": payload.conflict_id,
                    "differentiating_condition": payload.differentiating_condition,
                },
            )
            return {"status": "resolved", "conflict": resolved}

        return {
            "status": "error",
            "error": f"Unknown tool: {name}",
            "available_tools": [
                "capture_expert_rule",
                "inspect_knowledge_state",
                "resolve_knowledge_conflict",
                "retrieve_expert_guidance",
            ],
        }
