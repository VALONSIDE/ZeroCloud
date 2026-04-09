from app.models import (
    EventAction,
    EventCondition,
    EventRule,
    GateProfile,
    SkillRef,
)
from app.state import RuntimeState


def build_state() -> RuntimeState:
    profile = GateProfile(
        pool_id="POOL_ZC",
        pool_name="ZeroCloud",
        gate_id="GATE_01",
        gate_name="MAGI",
    )
    state = RuntimeState(
        profile=profile,
        default_event_cooldown_ms=1000,
        stream_interval_sec=0.5,
    )
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        status="ONLINE",
        skills=["SKILL_TEMP", "SKILL_HUM", "SKILL_DISPLAY"],
    )
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_002",
        status="ONLINE",
        skills=["SKILL_DISPLAY"],
    )
    return state


def test_form_event_requires_existing_skill():
    state = build_state()
    event = EventRule(
        event_id="evt_form",
        name="bad",
        enabled=True,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_001",
            source_skill="SKILL_NOT_EXISTS",
            operator=">",
            threshold=30,
        ),
        action=EventAction(
            target_kit_id="KIT_002",
            target_skill="SKILL_DISPLAY",
            payload={"msg": "TEST"},
        ),
    )
    try:
        state.validate_event_rule(event)
        assert False, "Expected skill validation to fail."
    except ValueError as exc:
        assert "SKILL_NOT_EXISTS" in str(exc)


def test_code_event_requires_selected_skill_refs():
    state = build_state()
    event = EventRule(
        event_id="evt_code",
        name="code",
        enabled=True,
        cooldown_ms=1000,
        mode="code",
        code="def evaluate(ctx):\n    return {'trigger': False}\n",
        required_skills=[SkillRef(kit_id="KIT_001", skill_id="SKILL_TEMP")],
        action=EventAction(
            target_kit_id="KIT_002",
            target_skill="SKILL_DISPLAY",
            payload={"msg": "HELLO"},
        ),
    )
    state.validate_event_rule(event)
