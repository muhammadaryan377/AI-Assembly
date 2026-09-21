from pathlib import Path

from app.engine import KnowledgeEngine
from app.models import RuleInput
from app.store import KnowledgeStore


def make_engine(tmp_path: Path) -> KnowledgeEngine:
    store = KnowledgeStore(tmp_path / "test.db")
    store.init()
    return KnowledgeEngine(store)


def test_capture_and_retrieve_traceable_guidance(tmp_path):
    engine = make_engine(tmp_path)
    engine.capture_rule(
        RuleInput(
            topic="Pump B restart",
            conditions={
                "shutdown_reason": "overload",
                "vibration": "high",
                "suction_pressure": "falling",
            },
            action="Do not restart. Check for cavitation.",
            rationale="This pattern indicates cavitation risk.",
            source_quote="If pressure is falling with high vibration, don't restart it.",
            expert="Alex",
            confidence=0.96,
        )
    )

    result = engine.retrieve_guidance(
        "Pump B restart",
        {
            "shutdown_reason": "overload",
            "vibration": "high",
            "suction_pressure": "falling",
        },
    )

    assert result["status"] == "matched"
    assert result["match"]["rule"]["expert"] == "Alex"
    assert "Do not restart" in result["match"]["rule"]["action"]
    assert result["match"]["score"] > 0.9


def test_conflict_is_detected_instead_of_overwritten(tmp_path):
    engine = make_engine(tmp_path)
    base = dict(
        topic="Pump B restart",
        conditions={"vibration": "high", "load": "low"},
        rationale="Expert judgment",
        source_quote="Direct expert statement",
        confidence=0.9,
    )

    engine.capture_rule(RuleInput(**base, action="Shut the pump down", expert="Alex"))
    second = engine.capture_rule(
        RuleInput(**base, action="Continue operation", expert="Sam")
    )

    assert len(second["conflicts"]) == 1
    assert second["conflicts"][0]["status"] == "open"


def test_mismatched_condition_does_not_return_rule(tmp_path):
    engine = make_engine(tmp_path)
    engine.capture_rule(
        RuleInput(
            topic="Pump B restart",
            conditions={"suction_pressure": "falling"},
            action="Do not restart",
            source_quote="Do not restart while suction pressure is falling.",
            expert="Alex",
            confidence=0.95,
        )
    )

    result = engine.retrieve_guidance(
        "Pump B restart",
        {"suction_pressure": "normal"},
    )
    assert result["status"] == "insufficient_evidence"


def test_coverage_identifies_missing_dimensions(tmp_path):
    engine = make_engine(tmp_path)
    engine.capture_rule(
        RuleInput(
            topic="Pump B restart",
            conditions={"vibration": "high"},
            action="Inspect before restart",
            source_quote="Inspect it if vibration is high.",
            expert="Alex",
        )
    )

    state = engine.inspect_knowledge_state("Pump B restart")
    assert "suction_pressure" in state["missing_dimensions"]
    assert state["coverage_percent"] < 100
