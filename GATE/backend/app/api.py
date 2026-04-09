from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .event_templates import CODE_FRAMEWORK, builtin_event_templates
from .models import EventAction, EventCondition, EventRule, SkillRef
from .mqtt_gateway import MqttGateway
from .schemas import (
    AdoptRequest,
    DisplayRequest,
    EventToggleRequest,
    EventUpsertRequest,
    KitRenameRequest,
    ProfileNamesRequest,
    ProfileRequest,
)
from .state import RuntimeState
from .storage import save_event_rows, save_json_object


def create_router(
    state: RuntimeState,
    mqtt_gateway: MqttGateway,
    event_store: Path,
    profile_store: Path,
    kit_store: Path,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def persist_events() -> None:
        save_event_rows(event_store, state.serialize_events())

    def persist_profile() -> None:
        save_json_object(profile_store, state.serialize_profile())

    def persist_kit_aliases() -> None:
        save_json_object(kit_store, state.serialize_kit_aliases())

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
            "gate_id": profile["gate_id"],
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
            return {"ok": True, "removed": removed}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"KIT {kit_id} not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/kits/{kit_id}/display")
    def display_override(kit_id: str, body: DisplayRequest) -> Dict[str, Any]:
        kit_id = kit_id.strip().upper()
        if not state.has_kit(kit_id):
            raise HTTPException(status_code=404, detail=f"KIT {kit_id} not found.")

        profile = state.profile_snapshot()
        topic = f"{profile['pool_id']}/{profile['gate_id']}/{kit_id}/SKILL_DISPLAY/SET"
        payload = {"msg": body.msg, "duration": body.duration}
        try:
            mqtt_gateway.publish_json(topic=topic, payload=payload, qos=1, retain=False)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MQTT publish failed: {exc}") from exc
        return {"kit_id": kit_id, "topic": topic, "payload": payload}

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
