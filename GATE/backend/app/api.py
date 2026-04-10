from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import asyncio
import json
import secrets
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .engine import SAFE_BUILTINS
from .event_templates import CODE_FRAMEWORK, builtin_event_templates
from .models import EventAction, EventCondition, EventRule, SkillRef
from .mqtt_gateway import MqttGateway
from .schemas import (
    AdoptRequest,
    CodeTestRequest,
    DisplayRequest,
    GateResetConfirmRequest,
    EventToggleRequest,
    EventUpsertRequest,
    KitRenameRequest,
    ProfileNamesRequest,
    ProfileRequest,
    SkillInvokeRequest,
)
from .state import RuntimeState
from .storage import save_event_rows, save_json_object


def create_router(
    state: RuntimeState,
    mqtt_gateway: MqttGateway,
    event_store: Path,
    profile_store: Path,
    kit_store: Path,
    default_pool_id: str,
    default_pool_name: str,
    default_gate_id: str,
    default_gate_name: str,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def persist_events() -> None:
        save_event_rows(event_store, state.serialize_events())

    def persist_profile() -> None:
        save_json_object(profile_store, state.serialize_profile())

    def persist_kit_aliases() -> None:
        save_json_object(kit_store, state.serialize_kit_aliases())

    reset_challenge_code: Optional[str] = None
    reset_challenge_expire_at = 0.0
    missing_value = object()

    def gate_root_dir() -> Path:
        # profile_store is usually <GATE>/backend/data/profile.json
        return profile_store.resolve().parents[2]

    def ensure_env_profile_unconfigured() -> None:
        env_path = gate_root_dir() / ".env"
        if not env_path.exists():
            return
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        updated: list[str] = []
        for line in lines:
            if line.startswith("ZC_PROFILE_CONFIGURED="):
                updated.append('ZC_PROFILE_CONFIGURED="0"')
                found = True
            else:
                updated.append(line)
        if not found:
            updated.append('ZC_PROFILE_CONFIGURED="0"')
        env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

    def perform_gate_reset() -> None:
        for path in (profile_store, kit_store, event_store):
            if path.exists():
                path.unlink()

        ensure_env_profile_unconfigured()
        state.factory_reset(
            pool_id=default_pool_id,
            pool_name=default_pool_name,
            gate_id=default_gate_id,
            gate_name=default_gate_name,
        )

    def build_event(event_id: str, body: EventUpsertRequest) -> EventRule:
        condition = (
            EventCondition(
                source_kit_id=body.condition.source_kit_id.strip().upper(),
                source_skill=body.condition.source_skill.strip(),
                operator=body.condition.operator,
                threshold=body.condition.threshold,
            )
            if body.condition is not None
            else None
        )
        action = (
            EventAction(
                target_kit_id=body.action.target_kit_id.strip().upper(),
                target_skill=body.action.target_skill.strip(),
                action=body.action.action.strip().upper(),
                payload=dict(body.action.payload),
            )
            if body.action is not None
            else None
        )
        required_skills = [
            SkillRef(
                kit_id=item.kit_id.strip().upper(),
                skill_id=item.skill_id.strip(),
            )
            for item in body.required_skills
        ]
        return EventRule(
            event_id=event_id,
            name=body.name.strip(),
            enabled=body.enabled,
            cooldown_ms=body.cooldown_ms,
            mode=body.mode,
            condition=condition,
            action=action,
            code=body.code,
            required_skills=required_skills,
        )

    def build_code_test_context() -> Dict[str, Any]:
        with state.lock:
            profile = state.profile_snapshot()
            kits_snapshot = {
                kit_id: {
                    "status": kit.status,
                    "name": kit.display_name,
                    "skills": list(kit.skills),
                    "values": dict(kit.skill_values),
                }
                for kit_id, kit in state.kits_by_id.items()
            }

        def get_skill(kit_id: str, skill_id: str, default: Any = missing_value) -> Any:
            normalized_kit = str(kit_id).strip().upper()
            normalized_skill = str(skill_id).strip()
            kit = kits_snapshot.get(normalized_kit)
            if kit is None:
                raise KeyError(f"KIT {normalized_kit} not found.")
            if normalized_skill not in kit["skills"]:
                raise KeyError(
                    f"SKILL {normalized_skill} not found on KIT {normalized_kit}."
                )
            if normalized_skill in kit["values"]:
                return kit["values"][normalized_skill]
            if default is not missing_value:
                return default
            raise KeyError(
                f"SKILL {normalized_skill} has no value yet on KIT {normalized_kit}."
            )

        def is_online(kit_id: str) -> bool:
            normalized_kit = str(kit_id).strip().upper()
            kit = kits_snapshot.get(normalized_kit)
            return bool(kit and kit["status"] == "ONLINE")

        return {
            "pool_id": profile["pool_id"],
            "gate_id": profile["gate_id"],
            "now_unix": time.time(),
            "get": get_skill,
            "is_online": is_online,
            "kits": kits_snapshot,
        }

    @router.get("/health")
    def health() -> Dict[str, Any]:
        snapshot = state.snapshot()
        return {
            "ok": True,
            "pool_id": snapshot["profile"]["pool_id"],
            "gate_id": snapshot["profile"]["gate_id"],
            "mqtt_connected": snapshot["metrics"]["mqtt_connected"],
            "frame_tps": snapshot["metrics"]["frame_tps"],
        }

    @router.get("/state")
    def state_snapshot() -> Dict[str, Any]:
        return state.snapshot()

    @router.get("/topology")
    def topology_snapshot() -> Dict[str, Any]:
        snapshot = state.snapshot()
        return {
            "pool_id": snapshot["pool_id"],
            "gate_id": snapshot["gate_id"],
            "topology": snapshot["topology"],
            "metrics": snapshot["metrics"],
            "events": snapshot["events"],
        }

    @router.get("/profile")
    def profile_read() -> Dict[str, Any]:
        return state.profile_snapshot()

    @router.put("/profile")
    def profile_update(body: ProfileNamesRequest) -> Dict[str, Any]:
        try:
            profile = state.update_profile_names(
                pool_name=body.pool_name,
                gate_name=body.gate_name,
            )
            persist_profile()
            mqtt_gateway.announce_profile()
            return profile
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def setup_profile(body: ProfileRequest) -> Dict[str, Any]:
        current = state.profile_snapshot()
        if current.get("configured"):
            raise HTTPException(
                status_code=409,
                detail="GATE is already bound to one POOL. Setup is only available on first start.",
            )
        try:
            profile = state.update_profile(
                pool_id=body.pool_id,
                pool_name=body.pool_name,
                gate_id=body.gate_id,
                gate_name=body.gate_name,
                configured=True,
            )
            persist_profile()
            mqtt_gateway.announce_profile()
            return profile
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/pools/discovered")
    def discovered_pools() -> Dict[str, Any]:
        return {"items": state.list_discovered_pools()}

    @router.post("/setup/join")
    def setup_join_pool(body: ProfileRequest) -> Dict[str, Any]:
        return setup_profile(body)

    @router.post("/setup/create")
    def setup_create_pool(body: ProfileRequest) -> Dict[str, Any]:
        return setup_profile(body)

    @router.post("/pools/join")
    def join_pool(body: ProfileRequest) -> Dict[str, Any]:
        return setup_profile(body)

    @router.post("/pools/create")
    def create_pool(body: ProfileRequest) -> Dict[str, Any]:
        return setup_profile(body)

    @router.post("/gate/reset/challenge")
    def gate_reset_challenge() -> Dict[str, Any]:
        nonlocal reset_challenge_code, reset_challenge_expire_at
        reset_challenge_code = f"{secrets.randbelow(900000) + 100000}"
        reset_challenge_expire_at = time.time() + 120.0
        return {
            "code": reset_challenge_code,
            "expires_in_sec": 120,
        }

    @router.post("/gate/reset/confirm")
    def gate_reset_confirm(body: GateResetConfirmRequest) -> Dict[str, Any]:
        nonlocal reset_challenge_code, reset_challenge_expire_at
        now = time.time()
        if (
            not reset_challenge_code
            or now > reset_challenge_expire_at
            or body.code.strip() != reset_challenge_code
        ):
            raise HTTPException(status_code=400, detail="Invalid or expired reset code.")

        reset_challenge_code = None
        reset_challenge_expire_at = 0.0
        perform_gate_reset()
        return {
            "ok": True,
            "message": "GATE has been reset. Console will return to first-time setup.",
        }

    @router.get("/pending")
    def pending_list() -> Dict[str, Any]:
        return {"items": state.list_pending()}

    @router.post("/pending/{uid}/adopt")
    def adopt_pending(uid: str, body: AdoptRequest) -> Dict[str, Any]:
        try:
            pending_pool_id, kit_id, skills, uid_matched_existing = state.prepare_adoption(
                uid,
                body.kit_id,
                body.pending_pool_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Pending UID {uid} not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        profile = state.profile_snapshot()
        topic = f"{pending_pool_id}/PROVISION/{uid}"
        payload = {
            "pool_id": profile["pool_id"],
            "pool_name": profile["pool_name"],
            "gate_id": profile["gate_id"],
            "gate_name": profile["gate_name"],
            "kit_id": kit_id,
        }
        try:
            mqtt_gateway.publish_json(topic=topic, payload=payload, qos=1, retain=False)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MQTT publish failed: {exc}") from exc

        adoption = state.commit_adoption(
            uid=uid,
            pending_pool_id=pending_pool_id,
            kit_id=kit_id,
            skills=skills,
            display_name=body.kit_name,
        )
        persist_kit_aliases()
        return {
            "uid": uid,
            "pending_pool_id": pending_pool_id,
            "kit_id": adoption["kit_id"],
            "kit_name": adoption["kit_name"],
            "merged_existing": bool(adoption["merged_existing"] or uid_matched_existing),
            "topic": topic,
            "payload": payload,
        }

    @router.get("/kits")
    def kit_list() -> Dict[str, Any]:
        snapshot = state.snapshot()
        return {"items": snapshot["kits"]}

    @router.patch("/kits/{kit_id}/name")
    def rename_kit(kit_id: str, body: KitRenameRequest) -> Dict[str, Any]:
        try:
            item = state.rename_kit(kit_id=kit_id, name=body.name)
            persist_kit_aliases()
            return item
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"KIT {kit_id} not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/kits/{kit_id}")
    def delete_kit(kit_id: str, force: bool = False) -> Dict[str, Any]:
        try:
            removed = state.delete_kit(kit_id=kit_id, force=force)
            persist_kit_aliases()
            persist_events()
            return {"ok": True, "removed": removed}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"KIT {kit_id} not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def publish_kit_skill_action(
        kit_id: str, skill_id: str, action: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        normalized_kit_id = kit_id.strip().upper()
        normalized_skill_id = skill_id.strip()
        normalized_action = action.strip().upper() or "SET"
        if not normalized_skill_id:
            raise HTTPException(status_code=400, detail="Missing skill_id.")
        if not state.has_kit(normalized_kit_id):
            raise HTTPException(
                status_code=404, detail=f"KIT {normalized_kit_id} not found."
            )

        try:
            state.validate_skill_action(
                kit_id=normalized_kit_id,
                skill_id=normalized_skill_id,
                action=normalized_action,
                payload=payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        profile = state.profile_snapshot()
        topic = (
            f"{profile['pool_id']}/{profile['gate_id']}/"
            f"{normalized_kit_id}/{normalized_skill_id}/{normalized_action}"
        )
        try:
            mqtt_gateway.publish_json(topic=topic, payload=payload, qos=1, retain=False)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MQTT publish failed: {exc}") from exc
        return {
            "kit_id": normalized_kit_id,
            "skill_id": normalized_skill_id,
            "action": normalized_action,
            "topic": topic,
            "payload": payload,
        }

    @router.post("/kits/{kit_id}/invoke")
    def invoke_skill(kit_id: str, body: SkillInvokeRequest) -> Dict[str, Any]:
        return publish_kit_skill_action(
            kit_id=kit_id,
            skill_id=body.skill_id,
            action=body.action,
            payload=dict(body.payload),
        )

    @router.post("/kits/{kit_id}/display")
    def display_override(kit_id: str, body: DisplayRequest) -> Dict[str, Any]:
        payload = {"msg": body.msg, "duration": body.duration}
        return publish_kit_skill_action(
            kit_id=kit_id,
            skill_id="SKILL_DISPLAY",
            action="SET",
            payload=payload,
        )

    @router.post("/kits/{kit_id}/reset")
    def reset_kit(kit_id: str) -> Dict[str, Any]:
        kit_id = kit_id.strip().upper()
        if not state.has_kit(kit_id):
            raise HTTPException(status_code=404, detail=f"KIT {kit_id} not found.")

        profile = state.profile_snapshot()
        topic = f"{profile['pool_id']}/{profile['gate_id']}/{kit_id}/SYS/RESET"
        payload = {"source": "GATE"}
        try:
            mqtt_gateway.publish_json(topic=topic, payload=payload, qos=1, retain=False)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MQTT publish failed: {exc}") from exc
        return {"kit_id": kit_id, "topic": topic}

    @router.get("/skills")
    def skill_catalog() -> Dict[str, Any]:
        return state.skills_catalog()

    @router.get("/events")
    def list_events() -> Dict[str, Any]:
        return {"items": state.serialize_events()}

    @router.get("/events/skills")
    def event_skills() -> Dict[str, Any]:
        catalog = state.skills_catalog()
        return {"items": catalog["flat"], "grouped": catalog["grouped"]}

    @router.get("/events/templates")
    def event_templates() -> Dict[str, Any]:
        return {"items": builtin_event_templates()}

    @router.get("/events/code-framework")
    def event_code_framework() -> Dict[str, Any]:
        return {"code": CODE_FRAMEWORK}

    @router.post("/events/code-test")
    def event_code_test(body: CodeTestRequest) -> Dict[str, Any]:
        code = body.code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="Code payload is empty.")

        try:
            compiled = compile(code, "<event-code-test>", "exec")
        except SyntaxError as exc:
            location = (
                f"line {exc.lineno}, column {exc.offset}" if exc.lineno else "unknown"
            )
            return {"ok": False, "phase": "syntax", "error": f"{exc.msg} ({location})"}

        local_scope: Dict[str, Any] = {}
        try:
            exec(compiled, {"__builtins__": SAFE_BUILTINS}, local_scope)
        except Exception as exc:
            return {
                "ok": False,
                "phase": "compile",
                "error": f"{type(exc).__name__}: {exc}",
            }

        evaluate_fn = local_scope.get("evaluate")
        if not callable(evaluate_fn):
            return {
                "ok": False,
                "phase": "compile",
                "error": "Code mode must define function evaluate(ctx).",
            }

        try:
            result = evaluate_fn(build_code_test_context())
        except Exception as exc:
            return {
                "ok": False,
                "phase": "runtime",
                "error": f"{type(exc).__name__}: {exc}",
            }

        if isinstance(result, bool):
            return {"ok": True, "phase": "runtime", "result_type": "bool", "trigger": result}

        if not isinstance(result, dict):
            return {
                "ok": False,
                "phase": "runtime",
                "error": "evaluate(ctx) must return bool or dict.",
            }

        trigger = bool(result.get("trigger", False))
        action_count = 0
        if "actions" in result:
            raw_actions = result.get("actions")
            if not isinstance(raw_actions, list):
                return {
                    "ok": False,
                    "phase": "runtime",
                    "error": "Code result 'actions' must be a list.",
                }
            action_count = sum(1 for item in raw_actions if isinstance(item, dict))
        elif "action" in result:
            if not isinstance(result.get("action"), dict):
                return {
                    "ok": False,
                    "phase": "runtime",
                    "error": "Code result 'action' must be a dict.",
                }
            action_count = 1

        return {
            "ok": True,
            "phase": "runtime",
            "result_type": "dict",
            "trigger": trigger,
            "actions": action_count,
        }

    @router.post("/events")
    def create_event(body: EventUpsertRequest) -> Dict[str, Any]:
        event = build_event(event_id=f"evt_{uuid.uuid4().hex[:10]}", body=body)
        try:
            state.validate_event_rule(event)
            saved = state.upsert_event(event)
            persist_events()
            return saved.to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/events/{event_id}")
    def update_event(event_id: str, body: EventUpsertRequest) -> Dict[str, Any]:
        try:
            current = state.get_event(event_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found.") from exc

        replacement = build_event(event_id=event_id, body=body)
        replacement.created_at = current.created_at
        replacement.last_triggered_at = current.last_triggered_at
        replacement.status = current.status
        replacement.lock_reason = current.lock_reason
        try:
            state.validate_event_rule(replacement)
            saved = state.upsert_event(replacement)
            persist_events()
            return saved.to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/events/{event_id}/enabled")
    def toggle_event(event_id: str, body: EventToggleRequest) -> Dict[str, Any]:
        try:
            event = state.set_event_enabled(event_id, body.enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        persist_events()
        return event.to_dict()

    @router.delete("/events/{event_id}")
    def delete_event(event_id: str) -> Dict[str, Any]:
        removed = state.delete_event(event_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
        persist_events()
        return {"ok": True, "event_id": event_id}

    @router.get("/stream")
    async def stream_state() -> StreamingResponse:
        async def generator() -> Any:
            last_revision = -1
            while True:
                revision, snapshot = state.snapshot_with_revision()
                if revision != last_revision:
                    payload = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: state\ndata: {payload}\n\n"
                    last_revision = revision
                await asyncio.sleep(state.stream_interval_sec)

        return StreamingResponse(generator(), media_type="text/event-stream")

    return router
