from __future__ import annotations

from typing import Any


CAPTURE_PROMPT = """
You are TacitOS, an expert-knowledge interviewer. Your job is not to chat casually.
You turn undocumented human expertise into precise, traceable operational rules.

Interview behavior:
1. Ask one concise question at a time.
2. When the expert states a decision rule, exception, threshold, prerequisite, or warning,
   call capture_expert_rule immediately.
3. Conditions must be structured as concrete key/value facts. Examples:
   {"vibration":"high","suction_pressure":"falling"}.
4. Never invent a source quote. Use the expert's actual wording as closely as possible.
5. After a rule is captured, use inspect_knowledge_state and ask the returned best next question.
6. If a conflict appears, do not choose a winner. Ask the expert for the differentiating condition.
7. Keep spoken responses short because this is a live voice experience.

The demo domain is industrial troubleshooting, but support any expert domain.
"""

APPRENTICE_PROMPT = """
You are TacitOS in Apprentice Guidance mode. You help a worker reuse verified expert knowledge.

Rules:
1. Gather the minimum observations needed to answer.
2. Call retrieve_expert_guidance before recommending any operational action.
3. Never invent a rule that is not returned by the tool.
4. State the matched expert, source quote, and relevant conditions when available.
5. If evidence is insufficient or important conditions are unverified, ask for those facts.
6. If guidance conflicts, explain that expert review is needed rather than choosing one.
7. Keep spoken replies concise and action-oriented.
"""


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "capture_expert_rule",
        "description": (
            "Store one explicit expert decision rule, exception, threshold, prerequisite, "
            "or warning with provenance. Call this whenever reusable expertise is stated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Decision topic, e.g. Pump B restart"},
                "conditions": {
                    "type": "object",
                    "description": "Observed conditions as short key/value pairs",
                    "additionalProperties": {"type": ["string", "number", "boolean"]},
                },
                "action": {"type": "string", "description": "Action the expert recommends"},
                "rationale": {"type": "string", "description": "Why the action is correct"},
                "source_quote": {
                    "type": "string",
                    "description": "Expert wording that supports the rule",
                },
                "expert": {"type": "string", "description": "Expert name if known"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence inferred only from explicit certainty",
                },
            },
            "required": ["topic", "conditions", "action", "source_quote"],
        },
    },
    {
        "type": "function",
        "name": "inspect_knowledge_state",
        "description": (
            "Inspect captured knowledge for coverage gaps, unresolved contradictions, "
            "and the best next interview question."
        ),
        "parameters": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
    {
        "type": "function",
        "name": "resolve_knowledge_conflict",
        "description": (
            "Mark an identified contradiction as resolved after the expert explains "
            "the missing differentiating condition."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conflict_id": {"type": "string"},
                "resolution": {"type": "string"},
                "differentiating_condition": {"type": "string"},
            },
            "required": ["conflict_id", "resolution"],
        },
    },
    {
        "type": "function",
        "name": "retrieve_expert_guidance",
        "description": (
            "Match current observations against captured expert rules and return "
            "traceable guidance. Use before giving operational recommendations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "observations": {
                    "type": "object",
                    "additionalProperties": {"type": ["string", "number", "boolean"]},
                },
            },
            "required": ["topic", "observations"],
        },
    },
]


def session_config(mode: str) -> dict[str, Any]:
    capture = mode != "apprentice"
    return {
        "type": "session.update",
        "session": {
            "system_prompt": CAPTURE_PROMPT if capture else APPRENTICE_PROMPT,
            "greeting": (
                "I'm ready to capture your expertise. What decision or troubleshooting process should we preserve?"
                if capture
                else "Tell me what is happening, and I'll check it against captured expert knowledge."
            ),
            "output": {"voice": "anna"},
            "input": {
                "turn_detection": {
                    "vad_threshold": 0.55,
                    "min_silence": 850,
                    "max_silence": 4500,
                    "interrupt_response": True,
                }
            },
            "tools": TOOLS,
        },
    }
