from __future__ import annotations

from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re

from .models import (
    DiscoveredPool,
    EventRule,
    GateProfile,
    KitState,
    PendingKit,
    SkillRef,
    utc_now,
)


ID_PATTERN = re.compile(r"^[A-Z0-9_-]{2,32}$")
KIT_CUSTOM_ID_PATTERN = re.compile(r"^KIT_[A-Z0-9]{1,5}$")


def _pending_key(pool_id: str, uid: str) -> str:
    return f"{pool_id}:{uid}"


class RuntimeState:
    def __init__(
        self,
        profile: GateProfile,
        default_event_cooldown_ms: int,
        stream_interval_sec: float,
    ) -> None:
        self.profile = profile
        self.default_event_cooldown_ms = default_event_cooldown_ms
        self.stream_interval_sec = stream_interval_sec

        self.lock = RLock()
        self.pending_by_key: Dict[str, PendingKit] = {}
        self.kits_by_id: Dict[str, KitState] = {}
        self.kit_aliases: Dict[str, str] = {}
        self.uid_to_kit: Dict[str, str] = {}
        self.events: Dict[str, EventRule] = {}
        self.discovered_pools: Dict[str, DiscoveredPool] = {}

        self.revision = 0
        self.frame_tps = 0.0
        self.mqtt_connected = False
        self.runtime_errors: Dict[str, str] = {}
        self.started_at = utc_now()

        self._observe_pool_unlocked(
            pool_id=profile.pool_id,
            gate_id=profile.gate_id,
            pool_name=profile.pool_name,
            gate_name=profile.gate_name,
        )

    def _bump_unlocked(self) -> None:
        self.revision += 1

    def profile_snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return self.profile.to_dict()

    def serialize_profile(self) -> Dict[str, Any]:
        with self.lock:
            return self.profile.to_dict()

    def update_profile(
        self,
        pool_id: str,
        pool_name: str,
        gate_id: str,
        gate_name: str,
        configured: bool = True,
    ) -> Dict[str, Any]:
        pool_id = pool_id.strip().upper()
        gate_id = gate_id.strip().upper()
        pool_name = pool_name.strip() or pool_id
        gate_name = gate_name.strip() or gate_id
        if not ID_PATTERN.match(pool_id):
            raise ValueError("Invalid POOL ID format.")
        if not ID_PATTERN.match(gate_id):
            raise ValueError("Invalid GATE ID format.")

        with self.lock:
            old_pool = self.profile.pool_id
            old_gate = self.profile.gate_id
            self.profile = GateProfile(
                pool_id=pool_id,
                pool_name=pool_name,
                gate_id=gate_id,
                gate_name=gate_name,
                configured=configured,
            )
            self._observe_pool_unlocked(pool_id, gate_id, pool_name, gate_name)

            if old_pool != pool_id:
                self.pending_by_key = {
                    key: item
                    for key, item in self.pending_by_key.items()
                    if item.pool_id == pool_id
                }
            if old_pool != pool_id or old_gate != gate_id:
                self.kits_by_id = {}
                self.uid_to_kit = {}

            self._bump_unlocked()
            return self.profile.to_dict()

    def update_profile_names(self, pool_name: str, gate_name: str) -> Dict[str, Any]:
        resolved_pool_name = pool_name.strip() or self.profile.pool_id
        resolved_gate_name = gate_name.strip() or self.profile.gate_id
        with self.lock:
            self.profile.pool_name = resolved_pool_name
            self.profile.gate_name = resolved_gate_name
            self.profile.updated_at = utc_now()
            self._observe_pool_unlocked(
                self.profile.pool_id,
                self.profile.gate_id,
                resolved_pool_name,
                resolved_gate_name,
            )
            self._bump_unlocked()
            return self.profile.to_dict()

    def observe_pool(
        self,
        pool_id: str,
        gate_id: Optional[str] = None,
        pool_name: Optional[str] = None,
        gate_name: Optional[str] = None,
    ) -> None:
        with self.lock:
            if self._observe_pool_unlocked(pool_id, gate_id, pool_name, gate_name):
                self._bump_unlocked()

    def _observe_pool_unlocked(
        self,
        pool_id: str,
        gate_id: Optional[str],
        pool_name: Optional[str],
        gate_name: Optional[str],
    ) -> bool:
        normalized_pool = pool_id.strip().upper()
        if not normalized_pool:
            return False

        changed = False
        resolved_pool_name = (pool_name or "").strip() or normalized_pool
        pool = self.discovered_pools.get(normalized_pool)
        if pool is None:
            pool = DiscoveredPool(
                pool_id=normalized_pool,
                pool_name=resolved_pool_name,
            )
            self.discovered_pools[normalized_pool] = pool
            changed = True
        else:
            previous_name = pool.pool_name
            pool.touch(resolved_pool_name)
            if previous_name != pool.pool_name:
                changed = True

        if gate_id:
            normalized_gate = gate_id.strip().upper()
            if normalized_gate:
                before = pool.gates.get(normalized_gate)
                previous_gate_name = before.gate_name if before is not None else None
                pool.register_gate(normalized_gate, gate_name)
                if before is None:
                    changed = True
                else:
                    if gate_name and previous_gate_name != gate_name.strip():
                        changed = True
        return changed

    def list_discovered_pools(self) -> List[Dict[str, Any]]:
        with self.lock:
            current_pool = self.profile.pool_id
            current_gate = self.profile.gate_id
            items = [pool.to_dict() for pool in self.discovered_pools.values()]
        for item in items:
            item["active"] = item["pool_id"] == current_pool
            item["active_gate"] = any(
                gate["gate_id"] == current_gate for gate in item.get("gates", [])
            )
        items.sort(key=lambda row: row["pool_id"])
        return items

    def load_kit_aliases(self, raw: Dict[str, Any]) -> None:
        with self.lock:
            self.kit_aliases = {}
            for kit_id, name in raw.items():
                normalized_kit_id = str(kit_id).strip().upper()
                resolved_name = str(name).strip()
                if normalized_kit_id and resolved_name:
                    self.kit_aliases[normalized_kit_id] = resolved_name
            for kit in self.kits_by_id.values():
                alias = self.kit_aliases.get(kit.kit_id)
                if alias:
                    kit.display_name = alias
            self._bump_unlocked()

    def serialize_kit_aliases(self) -> Dict[str, Any]:
        with self.lock:
            output = dict(self.kit_aliases)
        return dict(sorted(output.items()))

    def set_mqtt_status(self, connected: bool, message: Optional[str] = None) -> None:
        with self.lock:
            self.mqtt_connected = connected
            if message:
                self.runtime_errors["mqtt"] = message
            elif "mqtt" in self.runtime_errors:
                del self.runtime_errors["mqtt"]
            self._bump_unlocked()

    def set_runtime_error(self, component: str, message: str) -> None:
        with self.lock:
            self.runtime_errors[component] = message
            self._bump_unlocked()

    def clear_runtime_error(self, component: str) -> None:
        with self.lock:
            if component in self.runtime_errors:
                del self.runtime_errors[component]
                self._bump_unlocked()

    def set_frame_tps(self, value: float) -> None:
        with self.lock:
            self.frame_tps = value
            self._bump_unlocked()

    def upsert_pending(
        self, pool_id: str, uid: str, skills: List[str], payload: Dict[str, Any]
    ) -> None:
        normalized_pool = pool_id.strip().upper()
        normalized_uid = uid.strip()
        if not normalized_pool or not normalized_uid:
            return

        with self.lock:
            self._observe_pool_unlocked(normalized_pool, None, payload.get("pool_name"), None)
            key = _pending_key(normalized_pool, normalized_uid)
            existing = self.pending_by_key.get(key)
            if existing is None:
                self.pending_by_key[key] = PendingKit(
                    pool_id=normalized_pool,
                    uid=normalized_uid,
                    skills=sorted({skill for skill in skills if skill}),
                    last_payload=dict(payload),
                )
            else:
                existing.skills = sorted(set(existing.skills).union(set(skills)))
                existing.last_payload = dict(payload)
            self._bump_unlocked()

    def list_pending(self) -> List[Dict[str, Any]]:
        with self.lock:
            values = [item.to_dict() for item in self.pending_by_key.values()]
        values.sort(key=lambda row: row["discovered_at"] or "")
        return values

    def _allocate_kit_id_unlocked(self, requested_kit_id: Optional[str]) -> str:
        if requested_kit_id:
            candidate = requested_kit_id.strip().upper()
            if not KIT_CUSTOM_ID_PATTERN.match(candidate):
                raise ValueError(
                    "KIT ID must follow KIT_[A-Z0-9]{1,5}, e.g. KIT_A1 or KIT_00001."
                )
            if candidate in self.kits_by_id:
                raise ValueError(f"KIT ID {candidate} already exists.")
            return candidate

        max_index = 0
        for kit_id in set(self.kits_by_id.keys()).union(self.kit_aliases.keys()):
            if kit_id.startswith("KIT_"):
                suffix = kit_id[4:]
                if suffix.isdigit():
                    max_index = max(max_index, int(suffix))

        next_index = max_index + 1
        while True:
            candidate = f"KIT_{next_index:05d}"
            if candidate not in self.kits_by_id:
                return candidate
            next_index += 1

    def prepare_adoption(
        self,
        uid: str,
        requested_kit_id: Optional[str],
        pending_pool_id: Optional[str] = None,
    ) -> Tuple[str, str, List[str], bool]:
        with self.lock:
            normalized_uid = uid.strip()
            pending: Optional[PendingKit] = None
            resolved_pending_pool = ""
            if pending_pool_id:
                candidate_pool = pending_pool_id.strip().upper()
                key = _pending_key(candidate_pool, normalized_uid)
                pending = self.pending_by_key.get(key)
                resolved_pending_pool = candidate_pool
            else:
                for item in self.pending_by_key.values():
                    if item.uid == normalized_uid:
                        pending = item
                        resolved_pending_pool = item.pool_id
                        break
            if pending is None:
                raise KeyError(uid)

            existing_kit_id = self.uid_to_kit.get(normalized_uid)
            if existing_kit_id is None:
                for kit in self.kits_by_id.values():
                    if kit.uid == normalized_uid:
                        existing_kit_id = kit.kit_id
                        self.uid_to_kit[normalized_uid] = existing_kit_id
                        break

            if existing_kit_id:
                if (
                    requested_kit_id
                    and requested_kit_id.strip().upper() != existing_kit_id
                ):
                    raise ValueError(
                        f"UID {normalized_uid} is already bound to {existing_kit_id}."
                    )
                existing_skills = []
                existing_kit = self.kits_by_id.get(existing_kit_id)
                if existing_kit is not None:
                    existing_skills = list(existing_kit.skills)
                merged_skills = list(set(pending.skills).union(set(existing_skills)))
                return (
                    resolved_pending_pool,
                    existing_kit_id,
                    sorted(merged_skills),
                    True,
                )

            kit_id = self._allocate_kit_id_unlocked(requested_kit_id)
            return resolved_pending_pool, kit_id, list(pending.skills), False

    def commit_adoption(
        self,
        uid: str,
        pending_pool_id: str,
        kit_id: str,
        skills: List[str],
        display_name: Optional[str],
    ) -> Dict[str, Any]:
        with self.lock:
            key = _pending_key(pending_pool_id.strip().upper(), uid.strip())
            pending = self.pending_by_key.pop(key, None)
            if pending is None:
                raise KeyError(uid)

            existing_kit_id = self.uid_to_kit.get(uid)
            if existing_kit_id is None:
                for kit in self.kits_by_id.values():
                    if kit.uid == uid:
                        existing_kit_id = kit.kit_id
                        self.uid_to_kit[uid] = existing_kit_id
                        break

            if existing_kit_id:
                existing = self.kits_by_id.get(existing_kit_id)
                resolved_name = (
                    (display_name or "").strip()
                    or self.kit_aliases.get(existing_kit_id)
                    or existing_kit_id
                )
                self.kit_aliases[existing_kit_id] = resolved_name

                if existing is None:
                    self.kits_by_id[existing_kit_id] = KitState(
                        pool_id=self.profile.pool_id,
                        gate_id=self.profile.gate_id,
                        kit_id=existing_kit_id,
                        display_name=resolved_name,
                        uid=uid,
                        status="OFFLINE",
                        skills=sorted(set(skills)),
                    )
                else:
                    existing.display_name = resolved_name
                    existing.pool_id = self.profile.pool_id
                    existing.gate_id = self.profile.gate_id
                    existing.uid = uid
                    existing.merge_skills(skills)
                    existing.touch()
                self.uid_to_kit[uid] = existing_kit_id
                self._bump_unlocked()
                return {
                    "kit_id": existing_kit_id,
                    "kit_name": resolved_name,
                    "merged_existing": True,
                }

            resolved_name = (display_name or "").strip() or kit_id
            self.kit_aliases[kit_id] = resolved_name
            self.uid_to_kit[uid] = kit_id
            self.kits_by_id[kit_id] = KitState(
                pool_id=self.profile.pool_id,
                gate_id=self.profile.gate_id,
                kit_id=kit_id,
                display_name=resolved_name,
                uid=uid,
                status="OFFLINE",
                skills=sorted(set(skills)),
            )
            self._bump_unlocked()
            return {
                "kit_id": kit_id,
                "kit_name": resolved_name,
                "merged_existing": False,
            }

    def has_kit(self, kit_id: str) -> bool:
        with self.lock:
            return kit_id in self.kits_by_id

    def rename_kit(self, kit_id: str, name: str) -> Dict[str, Any]:
        normalized_kit_id = kit_id.strip().upper()
        resolved_name = name.strip()
        if not resolved_name:
            raise ValueError("KIT display name cannot be empty.")
        with self.lock:
            kit = self.kits_by_id.get(normalized_kit_id)
            if kit is None:
                raise KeyError(normalized_kit_id)
            kit.display_name = resolved_name
            self.kit_aliases[normalized_kit_id] = resolved_name
            self._bump_unlocked()
            return kit.to_dict()

    def delete_kit(self, kit_id: str, force: bool) -> Dict[str, Any]:
        normalized_kit_id = kit_id.strip().upper()
        with self.lock:
            kit = self.kits_by_id.get(normalized_kit_id)
            if kit is None:
                raise KeyError(normalized_kit_id)
            if kit.status == "ONLINE":
                raise ValueError("KIT is online. Only offline KIT can be force deleted.")
            if not force:
                raise ValueError("Set force=true to confirm offline KIT deletion.")

            self.kits_by_id.pop(normalized_kit_id, None)
            self.kit_aliases.pop(normalized_kit_id, None)
            for uid, mapped_kit in list(self.uid_to_kit.items()):
                if mapped_kit == normalized_kit_id:
                    del self.uid_to_kit[uid]
            self._bump_unlocked()
            return kit.to_dict()

    def _find_uid_for_kit_unlocked(self, kit_id: str) -> Optional[str]:
        for uid, mapped_kit_id in self.uid_to_kit.items():
            if mapped_kit_id == kit_id:
                return uid
        return None

    def upsert_kit_status(
        self,
        pool_id: str,
        gate_id: str,
        kit_id: str,
        status: str,
        skills: Optional[List[str]] = None,
        uid_hint: Optional[str] = None,
    ) -> None:
        normalized_pool = pool_id.strip().upper()
        normalized_gate = gate_id.strip().upper()
        normalized_kit = kit_id.strip().upper()
        if not normalized_pool or not normalized_gate or not normalized_kit:
            return

        with self.lock:
            self._observe_pool_unlocked(normalized_pool, normalized_gate, None, None)
            if (
                normalized_pool != self.profile.pool_id
                or normalized_gate != self.profile.gate_id
            ):
                return

            kit = self.kits_by_id.get(normalized_kit)
            if kit is None:
                uid = uid_hint or self._find_uid_for_kit_unlocked(normalized_kit)
                display_name = self.kit_aliases.get(normalized_kit, normalized_kit)
                kit = KitState(
                    pool_id=normalized_pool,
                    gate_id=normalized_gate,
                    kit_id=normalized_kit,
                    display_name=display_name,
                    uid=uid,
                )
                self.kits_by_id[normalized_kit] = kit

            if uid_hint:
                kit.uid = uid_hint
                self.uid_to_kit[uid_hint] = normalized_kit

            normalized_status = status.upper()
            if normalized_status == "ONLINE":
                kit.mark_online()
            else:
                kit.mark_offline()
                kit.touch()

            if skills:
                kit.merge_skills(skills)

            self._bump_unlocked()

    def upsert_skill_value(
        self,
        pool_id: str,
        gate_id: str,
        kit_id: str,
        skill_id: str,
        value: Any,
    ) -> None:
        normalized_pool = pool_id.strip().upper()
        normalized_gate = gate_id.strip().upper()
        normalized_kit = kit_id.strip().upper()
        normalized_skill = skill_id.strip()
        if (
            not normalized_pool
            or not normalized_gate
            or not normalized_kit
            or not normalized_skill
        ):
            return

        with self.lock:
            self._observe_pool_unlocked(normalized_pool, normalized_gate, None, None)
            if (
                normalized_pool != self.profile.pool_id
                or normalized_gate != self.profile.gate_id
            ):
                return

            kit = self.kits_by_id.get(normalized_kit)
            if kit is None:
                uid = self._find_uid_for_kit_unlocked(normalized_kit)
                display_name = self.kit_aliases.get(normalized_kit, normalized_kit)
                kit = KitState(
                    pool_id=normalized_pool,
                    gate_id=normalized_gate,
                    kit_id=normalized_kit,
                    display_name=display_name,
                    uid=uid,
                )
                self.kits_by_id[normalized_kit] = kit

            kit.mark_online()
            if normalized_skill not in kit.skills:
                kit.skills.append(normalized_skill)
                kit.skills.sort()
            kit.skill_values[normalized_skill] = value
            self._bump_unlocked()

    def mark_offline_if_stale(self, timeout_sec: float) -> bool:
        now = utc_now()
        changed = False
        with self.lock:
            for kit in self.kits_by_id.values():
                if kit.status != "ONLINE":
                    continue
                age = (now - kit.last_seen).total_seconds()
                if age > timeout_sec:
                    kit.mark_offline()
                    changed = True
            if changed:
                self._bump_unlocked()
        return changed

    def _validate_skill_ref_unlocked(self, kit_id: str, skill_id: str) -> None:
        normalized_kit = kit_id.strip().upper()
        normalized_skill = skill_id.strip()
        kit = self.kits_by_id.get(normalized_kit)
        if kit is None:
            raise ValueError(f"KIT {normalized_kit} not found.")
        if normalized_skill not in kit.skills:
            raise ValueError(
                f"SKILL {normalized_skill} not found on KIT {normalized_kit}."
            )

    def validate_event_rule(self, event: EventRule) -> None:
        with self.lock:
            if event.mode == "form":
                if event.condition is None or event.action is None:
                    raise ValueError("Form mode requires condition and action.")
                self._validate_skill_ref_unlocked(
                    event.condition.source_kit_id,
                    event.condition.source_skill,
                )
                self._validate_skill_ref_unlocked(
                    event.action.target_kit_id,
                    event.action.target_skill,
                )
                return

            if event.mode == "code":
                if not event.code.strip():
                    raise ValueError("Code mode requires non-empty code.")
                for ref in event.required_skills:
                    self._validate_skill_ref_unlocked(ref.kit_id, ref.skill_id)
                if event.action is not None:
                    self._validate_skill_ref_unlocked(
                        event.action.target_kit_id,
                        event.action.target_skill,
                    )
                return

            raise ValueError(f"Unsupported event mode: {event.mode}")

    def refresh_event_locks(self) -> None:
        with self.lock:
            changed = False
            for event in self.events.values():
                if not event.enabled:
                    if event.status != "IDLE" or event.lock_reason is not None:
                        event.status = "IDLE"
                        event.lock_reason = None
                        changed = True
                    continue

                if event.mode == "form":
                    if event.condition is None or event.action is None:
                        if event.status != "ERROR" or event.lock_reason != "Invalid form event":
                            event.status = "ERROR"
                            event.lock_reason = "Invalid form event"
                            changed = True
                        continue
                    source = self.kits_by_id.get(event.condition.source_kit_id)
                    target = self.kits_by_id.get(event.action.target_kit_id)
                    if source is None or source.status != "ONLINE":
                        if (
                            event.status != "LOCKED"
                            or event.lock_reason != "Source KIT offline"
                        ):
                            event.status = "LOCKED"
                            event.lock_reason = "Source KIT offline"
                            changed = True
                        continue
                    if target is None or target.status != "ONLINE":
                        if (
                            event.status != "LOCKED"
                            or event.lock_reason != "Target KIT offline"
                        ):
                            event.status = "LOCKED"
                            event.lock_reason = "Target KIT offline"
                            changed = True
                        continue
                    if event.condition.source_skill not in source.skills:
                        if (
                            event.status != "ERROR"
                            or event.lock_reason != "Source SKILL not found"
                        ):
                            event.status = "ERROR"
                            event.lock_reason = "Source SKILL not found"
                            changed = True
                        continue
                    if event.action.target_skill not in target.skills:
                        if (
                            event.status != "ERROR"
                            or event.lock_reason != "Target SKILL not found"
                        ):
                            event.status = "ERROR"
                            event.lock_reason = "Target SKILL not found"
                            changed = True
                        continue
                    if event.status in {"LOCKED", "ERROR"}:
                        event.status = "IDLE"
                        event.lock_reason = None
                        changed = True
                    continue

                if event.mode == "code":
                    failed_reason: Optional[str] = None
                    for ref in event.required_skills:
                        kit = self.kits_by_id.get(ref.kit_id)
                        if kit is None:
                            failed_reason = f"KIT {ref.kit_id} not found"
                            event.status = "ERROR"
                            break
                        if ref.skill_id not in kit.skills:
                            failed_reason = (
                                f"SKILL {ref.skill_id} not found on KIT {ref.kit_id}"
                            )
                            event.status = "ERROR"
                            break
                        if kit.status != "ONLINE":
                            failed_reason = f"Required KIT offline: {ref.kit_id}"
                            event.status = "LOCKED"
                            break
                    if failed_reason is not None:
                        if event.lock_reason != failed_reason:
                            event.lock_reason = failed_reason
                            changed = True
                        continue
                    if event.status in {"LOCKED", "ERROR"}:
                        event.status = "IDLE"
                        event.lock_reason = None
                        changed = True
                    continue

                if event.status != "ERROR" or event.lock_reason != "Unknown event mode":
                    event.status = "ERROR"
                    event.lock_reason = "Unknown event mode"
                    changed = True

            if changed:
                self._bump_unlocked()

    def load_events(self, rows: Iterable[Dict[str, Any]]) -> None:
        with self.lock:
            self.events = {}
            for row in rows:
                event = EventRule.from_dict(row, self.default_event_cooldown_ms)
                if event.event_id:
                    self.events[event.event_id] = event
            self._bump_unlocked()

    def _normalize_event_unlocked(self, event: EventRule) -> None:
        event.mode = event.mode.strip().lower()
        if event.condition:
            event.condition.source_kit_id = event.condition.source_kit_id.strip().upper()
            event.condition.source_skill = event.condition.source_skill.strip()
            event.condition.operator = event.condition.operator.strip()
        if event.action:
            event.action.target_kit_id = event.action.target_kit_id.strip().upper()
            event.action.target_skill = event.action.target_skill.strip()
            event.action.action = event.action.action.strip().upper()
        normalized_required: List[SkillRef] = []
        for item in event.required_skills:
            normalized_required.append(
                SkillRef(kit_id=item.kit_id.strip().upper(), skill_id=item.skill_id.strip())
            )
        event.required_skills = normalized_required

    def upsert_event(self, event: EventRule) -> EventRule:
        with self.lock:
            self._normalize_event_unlocked(event)
            event.touch()
            self.events[event.event_id] = event
            self._bump_unlocked()
            return event

    def get_event(self, event_id: str) -> EventRule:
        with self.lock:
            event = self.events.get(event_id)
            if event is None:
                raise KeyError(event_id)
            return event

    def set_event_enabled(self, event_id: str, enabled: bool) -> EventRule:
        with self.lock:
            event = self.events.get(event_id)
            if event is None:
                raise KeyError(event_id)
            event.enabled = enabled
            event.touch()
            if not enabled:
                event.status = "IDLE"
                event.lock_reason = None
            self._bump_unlocked()
            return event

    def delete_event(self, event_id: str) -> bool:
        with self.lock:
            removed = self.events.pop(event_id, None)
            if removed is not None:
                self._bump_unlocked()
                return True
            return False

    def serialize_events(self) -> List[Dict[str, Any]]:
        with self.lock:
            values = [event.to_dict() for event in self.events.values()]
        values.sort(key=lambda row: row["name"])
        return values

    def skills_catalog(self) -> Dict[str, Any]:
        with self.lock:
            kits = list(self.kits_by_id.values())
        grouped: List[Dict[str, Any]] = []
        flat: List[Dict[str, Any]] = []
        kits.sort(key=lambda item: item.kit_id)
        for kit in kits:
            skill_rows: List[Dict[str, Any]] = []
            for skill in sorted(kit.skills):
                value = kit.skill_values.get(skill)
                skill_rows.append({"skill_id": skill, "last_value": value})
                flat.append(
                    {
                        "kit_id": kit.kit_id,
                        "kit_name": kit.display_name,
                        "skill_id": skill,
                        "last_value": value,
                        "status": kit.status,
                    }
                )
            grouped.append(
                {
                    "kit_id": kit.kit_id,
                    "kit_name": kit.display_name,
                    "status": kit.status,
                    "skills": skill_rows,
                }
            )
        flat.sort(key=lambda row: (row["kit_id"], row["skill_id"]))
        return {"grouped": grouped, "flat": flat}

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            now = utc_now()
            profile = self.profile.to_dict()
            pending = [item.to_dict() for item in self.pending_by_key.values()]
            kits = [item.to_dict(now=now) for item in self.kits_by_id.values()]
            events = [item.to_dict() for item in self.events.values()]
            discovered = [item.to_dict() for item in self.discovered_pools.values()]
            revision = self.revision
            frame_tps = self.frame_tps
            mqtt_connected = self.mqtt_connected
            runtime_errors = dict(self.runtime_errors)

        pending.sort(key=lambda item: item["discovered_at"] or "")
        kits.sort(key=lambda item: item["kit_id"])
        events.sort(key=lambda item: item["name"])
        discovered.sort(key=lambda item: item["pool_id"])
        skills = self.skills_catalog()

        online_kits = sum(1 for item in kits if item["status"] == "ONLINE")
        locked_events = sum(1 for item in events if item["status"] == "LOCKED")
        error_events = sum(1 for item in events if item["status"] == "ERROR")

        return {
            "revision": revision,
            "pool_id": profile["pool_id"],
            "gate_id": profile["gate_id"],
            "profile": profile,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "metrics": {
                "frame_tps": frame_tps,
                "kits_total": len(kits),
                "kits_online": online_kits,
                "pending_total": len(pending),
                "events_total": len(events),
                "events_locked": locked_events,
                "events_error": error_events,
                "discovered_pools_total": len(discovered),
                "mqtt_connected": mqtt_connected,
            },
            "runtime_errors": runtime_errors,
            "discovered_pools": discovered,
            "pool_table": discovered,
            "pending": pending,
            "kits": kits,
            "skills": skills,
            "events": events,
            "topology": {
                "pool_id": profile["pool_id"],
                "pool_name": profile["pool_name"],
                "gate": {
                    "gate_id": profile["gate_id"],
                    "gate_name": profile["gate_name"],
                    "kits": [
                        {
                            "kit_id": kit["kit_id"],
                            "kit_name": kit["display_name"],
                            "status": kit["status"],
                            "lifecycle_state": kit["lifecycle_state"],
                        }
                        for kit in kits
                    ],
                },
            },
        }

    def snapshot_with_revision(self) -> Tuple[int, Dict[str, Any]]:
        snap = self.snapshot()
        return int(snap["revision"]), snap
