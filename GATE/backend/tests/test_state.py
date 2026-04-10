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


def test_deleted_kit_is_ignored_on_reconnect():
    state = build_state()
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        status="OFFLINE",
        skills=["SKILL_TEMP", "SKILL_HUM", "SKILL_DISPLAY"],
    )
    state.delete_kit("KIT_001", force=True)
    assert not state.has_kit("KIT_001")

    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        status="ONLINE",
        skills=["SKILL_TEMP", "SKILL_HUM", "SKILL_DISPLAY"],
    )
    state.upsert_skill_value(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        skill_id="SKILL_TEMP",
        value=33.3,
    )
    assert not state.has_kit("KIT_001")


def test_delete_kit_marks_related_event_dead():
    state = build_state()
    event = EventRule(
        event_id="evt_dead",
        name="dead",
        enabled=True,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_001",
            source_skill="SKILL_TEMP",
            operator=">",
            threshold=30,
        ),
        action=EventAction(
            target_kit_id="KIT_002",
            target_skill="SKILL_DISPLAY",
            payload={"msg": "TEST", "duration": 5000},
        ),
    )
    state.validate_event_rule(event)
    state.upsert_event(event)
    state.delete_kit("KIT_002", force=True)

    saved = state.get_event("evt_dead")
    assert saved.status == "DEAD"
    assert saved.enabled is False
    assert "KIT removed" in (saved.lock_reason or "")


def test_delete_kit_marks_code_event_dead():
    state = build_state()
    event = EventRule(
        event_id="evt_code_dead",
        name="code dead",
        enabled=True,
        cooldown_ms=1000,
        mode="code",
        code="def evaluate(ctx):\n    return {'trigger': False}\n",
        required_skills=[SkillRef(kit_id="KIT_001", skill_id="SKILL_TEMP")],
    )
    state.validate_event_rule(event)
    state.upsert_event(event)
    state.delete_kit("KIT_001", force=True)

    saved = state.get_event("evt_code_dead")
    assert saved.status == "DEAD"
    assert saved.enabled is False
    assert "KIT removed" in (saved.lock_reason or "")


def test_enable_event_fails_when_source_offline():
    state = build_state()
    event = EventRule(
        event_id="evt_lock",
        name="lock",
        enabled=False,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_001",
            source_skill="SKILL_TEMP",
            operator=">",
            threshold=30,
        ),
        action=EventAction(
            target_kit_id="KIT_002",
            target_skill="SKILL_DISPLAY",
            payload={"msg": "TEST"},
        ),
    )
    state.validate_event_rule(event)
    state.upsert_event(event)
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        status="OFFLINE",
        skills=["SKILL_TEMP", "SKILL_HUM", "SKILL_DISPLAY"],
    )

    try:
        state.set_event_enabled("evt_lock", True)
        assert False, "Expected enabling locked event to fail."
    except ValueError as exc:
        assert "offline" in str(exc).lower()


def test_offline_source_locks_disabled_event_immediately():
    state = build_state()
    event = EventRule(
        event_id="evt_lock_immediate",
        name="lock immediate",
        enabled=False,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_001",
            source_skill="SKILL_TEMP",
            operator=">",
            threshold=30,
        ),
        action=EventAction(
            target_kit_id="KIT_002",
            target_skill="SKILL_DISPLAY",
            payload={"msg": "TEST"},
        ),
    )
    state.validate_event_rule(event)
    state.upsert_event(event)
    saved = state.get_event("evt_lock_immediate")
    assert saved.status == "IDLE"

    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_001",
        status="OFFLINE",
        skills=["SKILL_TEMP", "SKILL_HUM", "SKILL_DISPLAY"],
    )
    saved = state.get_event("evt_lock_immediate")
    assert saved.status == "LOCKED"
    assert saved.lock_reason == "Source KIT offline"


def test_discovered_pool_name_does_not_flap_without_metadata():
    state = build_state()
    state.observe_pool(
        pool_id="POOL_REMOTE",
        gate_id="GATE_REMOTE",
        pool_name="Remote Pool",
        gate_name="Remote Gate",
    )
    # Later topic frames usually only carry IDs and should not overwrite names.
    state.observe_pool(pool_id="POOL_REMOTE", gate_id="GATE_REMOTE")

    found = {item["pool_id"]: item for item in state.list_discovered_pools()}["POOL_REMOTE"]
    assert found["pool_name"] == "Remote Pool"
    assert found["gates"][0]["gate_name"] == "Remote Gate"


def test_factory_reset_clears_discovered_pool_cache():
    state = build_state()
    state.observe_pool(
        pool_id="POOL_REMOTE",
        gate_id="GATE_REMOTE",
        pool_name="Remote Pool",
        gate_name="Remote Gate",
    )
    state.factory_reset(
        pool_id="POOL_ZC",
        pool_name="ZeroCloud",
        gate_id="GATE_01",
        gate_name="MAGI",
    )

    snapshot = state.snapshot()
    assert snapshot["discovered_pools"] == []
    assert snapshot["profile"]["configured"] is False


def test_skill_capability_metadata_controls_output_actions():
    state = build_state()
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_003",
        status="ONLINE",
        skills=["SKILL_SPK_NOTIFY"],
        skill_meta={
            "SKILL_SPK_NOTIFY": {
                "io_type": "output",
                "actions": ["PLAY", "STOP"],
                "supports_duration": True,
            }
        },
    )
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_004",
        status="ONLINE",
        skills=["SKILL_SPK_EVENT"],
        skill_meta={"SKILL_SPK_EVENT": {"io_type": "input"}},
    )

    flat = state.skills_catalog()["flat"]
    spk_row = next(item for item in flat if item["skill_id"] == "SKILL_SPK_NOTIFY")
    assert spk_row["io_type"] == "output"
    assert spk_row["actions"] == ["PLAY", "STOP"]
    assert spk_row["supports_duration"] is True

    invalid = EventRule(
        event_id="evt_action_invalid",
        name="invalid action",
        enabled=True,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_004",
            source_skill="SKILL_SPK_EVENT",
            operator="==",
            threshold=1,
        ),
        action=EventAction(
            target_kit_id="KIT_003",
            target_skill="SKILL_SPK_NOTIFY",
            action="SET",
            payload={"msg": "HI", "duration": 3000},
        ),
    )
    try:
        state.validate_event_rule(invalid)
        assert False, "Expected unsupported action validation to fail."
    except ValueError as exc:
        assert "Allowed: PLAY, STOP" in str(exc)

    valid = EventRule(
        event_id="evt_action_valid",
        name="valid action",
        enabled=True,
        cooldown_ms=1000,
        mode="form",
        condition=EventCondition(
            source_kit_id="KIT_004",
            source_skill="SKILL_SPK_EVENT",
            operator="==",
            threshold=1,
        ),
        action=EventAction(
            target_kit_id="KIT_003",
            target_skill="SKILL_SPK_NOTIFY",
            action="PLAY",
            payload={"duration": 3000},
        ),
    )
    state.validate_event_rule(valid)


def test_skill_action_spec_requires_payload_fields():
    state = build_state()
    state.upsert_kit_status(
        pool_id="POOL_ZC",
        gate_id="GATE_01",
        kit_id="KIT_005",
        status="ONLINE",
        skills=["SKILL_SPK_RING"],
        skill_meta={
            "SKILL_SPK_RING": {
                "io_type": "output",
                "action_specs": {
                    "RING": [
                        {"key": "times", "type": "number", "required": True, "min": 1}
                    ]
                },
            }
        },
    )

    try:
        state.validate_skill_action(
            kit_id="KIT_005",
            skill_id="SKILL_SPK_RING",
            action="RING",
            payload={},
        )
        assert False, "Expected required payload validation to fail."
    except ValueError as exc:
        assert "times" in str(exc)

    state.validate_skill_action(
        kit_id="KIT_005",
        skill_id="SKILL_SPK_RING",
        action="RING",
        payload={"times": 3},
    )
