from __future__ import annotations

import json
import re
from typing import Any

from app.models import RuleInput
from app.store import KnowledgeStore


DEFAULT_DIMENSIONS: dict[str, list[str]] = {
    "pump restart": [
        "shutdown_reason",
        "vibration",
        "suction_pressure",
        "load",
        "temperature",
    ],
    "pump b restart": [
        "shutdown_reason",
        "vibration",
        "suction_pressure",
        "load",
        "temperature",
    ],
}


def normalize(value: Any) -> str:
    text = str(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def signature(conditions: dict[str, Any]) -> str:
    normalized = {normalize(k): normalize(v) for k, v in conditions.items()}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def actions_conflict(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return False

    negative = ("do not", "don't", "stop", "block", "avoid", "never")
    a_neg = any(token in na for token in negative)
    b_neg = any(token in nb for token in negative)

    if a_neg != b_neg:
        return True
    return na != nb


class KnowledgeEngine:
    def __init__(self, store: KnowledgeStore):
        self.store = store

    def capture_rule(self, rule: RuleInput) -> dict[str, Any]:
        sig = signature(rule.conditions)
        prior = self.store.find_same_signature(rule.topic, sig)
        created = self.store.add_rule(
            topic=rule.topic.strip(),
            conditions=rule.conditions,
            condition_signature=sig,
            action=rule.action.strip(),
            rationale=rule.rationale.strip(),
            source_quote=rule.source_quote.strip(),
            expert=rule.expert.strip() or "Unknown expert",
            confidence=rule.confidence,
        )

        conflicts = []
        for old in prior:
            if actions_conflict(old["action"], created["action"]):
                conflicts.append(
                    self.store.add_conflict(
                        topic=rule.topic,
                        rule_a_id=old["id"],
                        rule_b_id=created["id"],
                        reason=(
                            "Two experts/rules prescribe different actions for the "
                            "same normalized operating conditions."
                        ),
                    )
                )

        self.store.add_audit(
            "rule.captured",
            {"rule_id": created["id"], "conflicts_created": [c["id"] for c in conflicts]},
        )
        return {
            "status": "captured",
            "rule": created,
            "conflicts": conflicts,
            "next": self.inspect_knowledge_state(rule.topic),
        }

    def inspect_knowledge_state(self, topic: str) -> dict[str, Any]:
        rules = self.store.list_rules(topic)
        open_conflicts = [
            conflict
            for conflict in self.store.list_conflicts("open")
            if normalize(conflict["topic"]) == normalize(topic)
        ]
        seen_dimensions = sorted(
            {normalize(key) for rule in rules for key in rule["conditions"].keys()}
        )
        expected = DEFAULT_DIMENSIONS.get(normalize(topic), seen_dimensions)
        missing = [dimension for dimension in expected if normalize(dimension) not in seen_dimensions]

        if expected:
            coverage = round(100 * (len(expected) - len(missing)) / len(expected))
        else:
            coverage = 0 if not rules else min(95, 35 + len(rules) * 8)

        if open_conflicts:
            next_question = (
                "Resolve the open contradiction first: ask what additional condition "
                "makes one action correct and the other incorrect."
            )
        elif missing:
            dimension = missing[0].replace("_", " ")
            next_question = f"Ask the expert how the decision changes when {dimension} changes."
        elif len(rules) < 5:
            next_question = (
                "Ask for an exception or edge case where the normal rule should not be followed."
            )
        else:
            next_question = (
                "Ask for the most dangerous false assumption a junior worker could make."
            )

        return {
            "topic": topic,
            "rule_count": len(rules),
            "coverage_percent": coverage,
            "dimensions_seen": seen_dimensions,
            "missing_dimensions": missing,
            "open_conflicts": open_conflicts,
            "next_question": next_question,
        }

    def retrieve_guidance(
        self, topic: str, observations: dict[str, Any]
    ) -> dict[str, Any]:
        rules = self.store.list_rules(topic)
        obs = {normalize(key): normalize(value) for key, value in observations.items()}

        full_matches: list[dict[str, Any]] = []
        partial_matches: list[dict[str, Any]] = []

        for rule in rules:
            conditions = {
                normalize(key): normalize(value)
                for key, value in rule["conditions"].items()
            }
            if not conditions:
                continue

            matched = 0
            mismatched = 0
            unknown = 0
            evidence: list[str] = []

            for key, expected in conditions.items():
                actual = obs.get(key)
                if actual is None:
                    unknown += 1
                elif actual == expected:
                    matched += 1
                    evidence.append(f"{key}={actual}")
                else:
                    mismatched += 1

            # A known mismatch rules the candidate out completely.
            if mismatched:
                continue

            specificity = matched / max(1, len(conditions))
            completeness = matched / max(1, matched + unknown)
            score = round(
                (0.7 * specificity + 0.3 * completeness) * rule["confidence"],
                4,
            )
            candidate = {
                "score": score,
                "matched_evidence": evidence,
                "rule": rule,
                "unverified_conditions": [
                    key for key in conditions if key not in obs
                ],
            }

            if unknown == 0:
                full_matches.append(candidate)
            else:
                partial_matches.append(candidate)

        full_matches.sort(key=lambda item: item["score"], reverse=True)
        partial_matches.sort(key=lambda item: item["score"], reverse=True)

        best = full_matches[0] if full_matches else None
        partial = partial_matches[0] if partial_matches else None

        if best:
            status = "matched"
        elif partial:
            status = "needs_clarification"
        else:
            status = "insufficient_evidence"

        result = {
            "topic": topic,
            "observations": observations,
            "match": best,
            "partial_match": partial,
            "alternatives": full_matches[1:4],
            "status": status,
        }
        self.store.add_audit("guidance.queried", result)
        return result
