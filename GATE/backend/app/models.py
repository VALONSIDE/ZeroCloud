from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _default_new_until() -> datetime:
    return utc_now() + timedelta(seconds=6)


@dataclass
class GateProfile:
    pool_id: str
    pool_name: str
    gate_id: str
    gate_name: str
    configured: bool = True
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "gate_id": self.gate_id,
            "gate_name": self.gate_name,
            "configured": self.configured,
            "updated_at": to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        default_pool_id: str,
        default_pool_name: str,
        default_gate_id: str,
        default_gate_name: str,
        default_configured: bool,
    ) -> "GateProfile":
        pool_id = str(data.get("pool_id") or default_pool_id).strip().upper()
        gate_id = str(data.get("gate_id") or default_gate_id).strip().upper()
        pool_name = str(data.get("pool_name") or default_pool_name).strip() or pool_id
        gate_name = str(data.get("gate_name") or default_gate_name).strip() or gate_id
        configured = bool(data.get("configured", default_configured))
        updated_at = parse_iso(data.get("updated_at")) or utc_now()
        return cls(
            pool_id=pool_id,
            pool_name=pool_name,
            gate_id=gate_id,
            gate_name=gate_name,
            configured=configured,
            updated_at=updated_at,
        )


@dataclass
class DiscoveredGate:
    gate_id: str
    gate_name: str
    last_seen: datetime = field(default_factory=utc_now)

    def touch(self, gate_name: Optional[str] = None) -> None:
        self.last_seen = utc_now()
        if gate_name:
            self.gate_name = gate_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_name": self.gate_name,
            "last_seen": to_iso(self.last_seen),
        }


@dataclass
class DiscoveredPool:
    pool_id: str
    pool_name: str
    last_seen: datetime = field(default_factory=utc_now)
    gates: Dict[str, DiscoveredGate] = field(default_factory=dict)

    def touch(self, pool_name: Optional[str] = None) -> None:
        self.last_seen = utc_now()
        if pool_name:
            self.pool_name = pool_name

    def register_gate(self, gate_id: str, gate_name: Optional[str]) -> None:
        existing = self.gates.get(gate_id)
        resolved_name = gate_name.strip() if gate_name else gate_id
        if existing is None:
            self.gates[gate_id] = DiscoveredGate(gate_id=gate_id, gate_name=resolved_name)
            return
        existing.touch(resolved_name)

    def to_dict(self) -> Dict[str, Any]:
        gates = [item.to_dict() for item in self.gates.values()]
        gates.sort(key=lambda item: item["gate_id"])
        return {
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "last_seen": to_iso(self.last_seen),
            "gates_total": len(gates),
            "gates": gates,
        }


@dataclass
class PendingKit:
    pool_id: str
    uid: str
    skills: List[str] = field(default_factory=list)
    discovered_at: datetime = field(default_factory=utc_now)
    last_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "uid": self.uid,
            "skills": list(self.skills),
            "discovered_at": to_iso(self.discovered_at),
            "last_payload": dict(self.last_payload),
        }


@dataclass
class KitState:
    pool_id: str
    gate_id: str
    kit_id: str
    display_name: str
    uid: Optional[str] = None
    status: str = "OFFLINE"
    skills: List[str] = field(default_factory=list)
    skill_values: Dict[str, Any] = field(default_factory=dict)
    first_seen: datetime = field(default_factory=utc_now)
    last_seen: datetime = field(default_factory=utc_now)
    new_until: datetime = field(default_factory=_default_new_until)

    def touch(self) -> None:
        self.last_seen = utc_now()

    def mark_online(self) -> None:
        now = utc_now()
        was_offline = self.status != "ONLINE"
        self.status = "ONLINE"
        if was_offline:
            self.new_until = now + timedelta(seconds=6)
        self.last_seen = now

    def mark_offline(self) -> None:
        self.status = "OFFLINE"

    def merge_skills(self, skills: List[str]) -> None:
        merged = set(self.skills)
        for skill in skills:
            if skill:
                merged.add(skill)
        self.skills = sorted(merged)

    def lifecycle_state(self, now: Optional[datetime] = None) -> str:
        current = now or utc_now()
        if self.status != "ONLINE":
            return "DYING"
        if current <= self.new_until:
            return "NEW"
        age = (current - self.last_seen).total_seconds()
        if age <= 3.5:
            return "WORKING"
        return "IDLE"

    def to_dict(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        current = now or utc_now()
        return {
            "pool_id": self.pool_id,
            "gate_id": self.gate_id,
            "kit_id": self.kit_id,
            "display_name": self.display_name,
            "uid": self.uid,
            "status": self.status,
            "lifecycle_state": self.lifecycle_state(current),
            "skills": list(self.skills),
            "skill_values": dict(self.skill_values),
            "first_seen": to_iso(self.first_seen),
            "last_seen": to_iso(self.last_seen),
        }


@dataclass
class SkillRef:
    kit_id: str
    skill_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {"kit_id": self.kit_id, "skill_id": self.skill_id}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillRef":
        return cls(
            kit_id=str(data.get("kit_id", "")).strip().upper(),
            skill_id=str(data.get("skill_id", "")).strip(),
        )


@dataclass
class EventCondition:
    source_kit_id: str
    source_skill: str
    operator: str
    threshold: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_kit_id": self.source_kit_id,
            "source_skill": self.source_skill,
            "operator": self.operator,
            "threshold": self.threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventCondition":
        return cls(
            source_kit_id=str(data.get("source_kit_id", "")).strip().upper(),
            source_skill=str(data.get("source_skill", "")).strip(),
            operator=str(data.get("operator", "==")).strip(),
            threshold=data.get("threshold"),
        )


@dataclass
class EventAction:
    target_kit_id: str
    target_skill: str
    action: str = "SET"
    payload: Dict[str, Any] = field(default_factory=dict)

    def topic_suffix(self) -> str:
        return f"{self.target_skill}/{self.action}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_kit_id": self.target_kit_id,
            "target_skill": self.target_skill,
            "action": self.action,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventAction":
        return cls(
            target_kit_id=str(data.get("target_kit_id", "")).strip().upper(),
            target_skill=str(data.get("target_skill", "")).strip(),
            action=str(data.get("action", "SET")).strip().upper(),
            payload=dict(data.get("payload", {})),
        )


@dataclass
class EventRule:
    event_id: str
    name: str
    enabled: bool
    cooldown_ms: int
    mode: str = "form"
    condition: Optional[EventCondition] = None
    action: Optional[EventAction] = None
    code: str = ""
    required_skills: List[SkillRef] = field(default_factory=list)
    last_triggered_at: Optional[datetime] = None
    status: str = "IDLE"
    lock_reason: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "enabled": self.enabled,
            "cooldown_ms": self.cooldown_ms,
            "mode": self.mode,
            "condition": self.condition.to_dict() if self.condition else None,
            "action": self.action.to_dict() if self.action else None,
            "code": self.code,
            "required_skills": [item.to_dict() for item in self.required_skills],
            "status": self.status,
            "lock_reason": self.lock_reason,
            "last_triggered_at": to_iso(self.last_triggered_at),
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], default_cooldown_ms: int) -> "EventRule":
        condition_raw = data.get("condition")
        action_raw = data.get("action")
        required_skills_raw = data.get("required_skills", [])

        mode = str(data.get("mode", "form")).strip().lower()
        if mode not in {"form", "code"}:
            mode = "form"

        condition = (
            EventCondition.from_dict(condition_raw)
            if isinstance(condition_raw, dict)
            else None
        )
        action = EventAction.from_dict(action_raw) if isinstance(action_raw, dict) else None
        required_skills: List[SkillRef] = []
        if isinstance(required_skills_raw, list):
            for item in required_skills_raw:
                if isinstance(item, dict):
                    required_skills.append(SkillRef.from_dict(item))

        # Backward compatibility with old event format.
        if mode == "form" and condition is None and isinstance(condition_raw, dict):
            condition = EventCondition.from_dict(condition_raw)
        if mode == "form" and action is None and isinstance(action_raw, dict):
            action = EventAction.from_dict(action_raw)

        return cls(
            event_id=str(data.get("event_id", "")).strip(),
            name=str(data.get("name", "Unnamed Event")).strip(),
            enabled=bool(data.get("enabled", True)),
            cooldown_ms=int(data.get("cooldown_ms", default_cooldown_ms)),
            mode=mode,
            condition=condition,
            action=action,
            code=str(data.get("code", "")),
            required_skills=required_skills,
            last_triggered_at=parse_iso(data.get("last_triggered_at")),
            status=str(data.get("status", "IDLE")),
            lock_reason=data.get("lock_reason"),
            created_at=parse_iso(data.get("created_at")) or utc_now(),
            updated_at=parse_iso(data.get("updated_at")) or utc_now(),
        )
