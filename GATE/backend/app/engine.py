from __future__ import annotations

from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional, Tuple
import time

from .models import EventAction, EventRule, utc_now
from .state import RuntimeState


PublishFn = Callable[[str, Dict[str, Any], int, bool], None]
AnnounceFn = Callable[[], None]
_MISSING = object()

SAFE_BUILTINS: Dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
}


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def evaluate_condition(left: Any, operator: str, right: Any) -> bool:
    left_num = _as_float(left)
    right_num = _as_float(right)

    if operator == "==":
        if left_num is not None and right_num is not None:
            return left_num == right_num
        return str(left) == str(right)

    if operator == "!=":
        if left_num is not None and right_num is not None:
            return left_num != right_num
        return str(left) != str(right)

    if left_num is None or right_num is None:
        return False

    if operator == ">":
        return left_num > right_num
    if operator == ">=":
        return left_num >= right_num
    if operator == "<":
        return left_num < right_num
    if operator == "<=":
        return left_num <= right_num
    raise ValueError(f"Unsupported operator: {operator}")


class FrameEngine:
    def __init__(self, state: RuntimeState, publish: PublishFn, frame_hz: float) -> None:
        self.state = state
        self.publish = publish
        self.frame_hz = frame_hz
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="magi-frame-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _lock_event(self, event: EventRule, reason: str) -> None:
        event.status = "LOCKED"
        event.lock_reason = reason

    def _build_topic(self, action: EventAction) -> str:
        profile = self.state.profile
        return (
            f"{profile.pool_id}/{profile.gate_id}/{action.target_kit_id}/"
            f"{action.topic_suffix()}"
        )

    def _validate_action_target_unlocked(self, action: EventAction) -> None:
        target_kit = self.state.kits_by_id.get(action.target_kit_id)
        if target_kit is None:
            raise ValueError(f"KIT {action.target_kit_id} not found.")
        if action.target_skill not in target_kit.skills:
            raise ValueError(
                f"SKILL {action.target_skill} not found on KIT {action.target_kit_id}."
            )

    def _can_trigger(self, event: EventRule, now_ts: float) -> bool:
        if event.last_triggered_at is None:
            return True
        elapsed_ms = (now_ts - event.last_triggered_at.timestamp()) * 1000.0
        return elapsed_ms >= event.cooldown_ms

    def _evaluate_form_event_unlocked(
        self, event: EventRule, now_ts: float
    ) -> List[Dict[str, Any]]:
        if event.condition is None or event.action is None:
            raise ValueError("Form event missing condition/action.")

        source = self.state.kits_by_id.get(event.condition.source_kit_id)
        target = self.state.kits_by_id.get(event.action.target_kit_id)
        if source is None:
            event.enabled = False
            event.status = "DEAD"
            event.lock_reason = f"Source KIT removed: {event.condition.source_kit_id}"
            return []
        if source.status != "ONLINE":
            self._lock_event(event, "Source KIT offline")
            return []
        if target is None:
            event.enabled = False
            event.status = "DEAD"
            event.lock_reason = f"Target KIT removed: {event.action.target_kit_id}"
            return []
        if target.status != "ONLINE":
            self._lock_event(event, "Target KIT offline")
            return []
        if event.condition.source_skill not in source.skills:
            raise ValueError(
                f"SKILL {event.condition.source_skill} not found on KIT {source.kit_id}."
            )
        if event.action.target_skill not in target.skills:
            raise ValueError(
                f"SKILL {event.action.target_skill} not found on KIT {target.kit_id}."
            )

        source_value = source.skill_values.get(event.condition.source_skill)
        if source_value is None:
            event.status = "IDLE"
            event.lock_reason = None
            return []

        matched = evaluate_condition(
            source_value, event.condition.operator, event.condition.threshold
        )
        if not matched:
            event.status = "IDLE"
            event.lock_reason = None
            return []

        if not self._can_trigger(event, now_ts):
            event.status = "WORKING"
            event.lock_reason = None
            return []

        event.last_triggered_at = utc_now()
        event.status = "WORKING"
        event.lock_reason = None
        event.touch()
        return [{"topic": self._build_topic(event.action), "payload": dict(event.action.payload)}]

    def _parse_action_from_dict(self, raw: Dict[str, Any]) -> EventAction:
        action = EventAction(
            target_kit_id=str(raw.get("target_kit_id", "")).strip().upper(),
            target_skill=str(raw.get("target_skill", "")).strip(),
            action=str(raw.get("action", "SET")).strip().upper(),
            payload=dict(raw.get("payload", {})),
        )
        if not action.target_kit_id or not action.target_skill:
            raise ValueError("Code action requires target_kit_id and target_skill.")
        return action

    def _code_context_unlocked(self) -> Dict[str, Any]:
        kits = self.state.kits_by_id

        def get_skill(kit_id: str, skill_id: str, default: Any = _MISSING) -> Any:
            normalized_kit = str(kit_id).strip().upper()
            normalized_skill = str(skill_id).strip()
            kit = kits.get(normalized_kit)
            if kit is None:
                raise KeyError(f"KIT {normalized_kit} not found.")
            if normalized_skill not in kit.skills:
                raise KeyError(
                    f"SKILL {normalized_skill} not found on KIT {normalized_kit}."
                )
            if normalized_skill in kit.skill_values:
                return kit.skill_values[normalized_skill]
            if default is not _MISSING:
                return default
            raise KeyError(
                f"SKILL {normalized_skill} has no value yet on KIT {normalized_kit}."
            )

        def is_online(kit_id: str) -> bool:
            normalized_kit = str(kit_id).strip().upper()
            kit = kits.get(normalized_kit)
            return bool(kit and kit.status == "ONLINE")

        return {
            "pool_id": self.state.profile.pool_id,
            "gate_id": self.state.profile.gate_id,
            "now_unix": time.time(),
            "get": get_skill,
            "is_online": is_online,
            "kits": {
                kit_id: {
                    "status": kit.status,
                    "name": kit.display_name,
                    "skills": list(kit.skills),
                    "values": dict(kit.skill_values),
                }
                for kit_id, kit in kits.items()
            },
        }

    def _parse_code_result_unlocked(
        self, event: EventRule, result: Any
    ) -> Tuple[bool, List[EventAction]]:
        if isinstance(result, bool):
            if not result:
                return False, []
            return True, [event.action] if event.action else []

        if isinstance(result, dict):
            trigger = bool(result.get("trigger", False))
            if not trigger:
                return False, []

            if "actions" in result:
                raw_actions = result.get("actions")
                if not isinstance(raw_actions, list):
                    raise ValueError("Code result 'actions' must be a list.")
                actions = [
                    self._parse_action_from_dict(item)
                    for item in raw_actions
                    if isinstance(item, dict)
                ]
            elif "action" in result and isinstance(result["action"], dict):
                actions = [self._parse_action_from_dict(result["action"])]
            elif event.action is not None:
                actions = [event.action]
            else:
                actions = []
            return True, actions

        raise ValueError("Code event evaluate(ctx) must return bool or dict.")

    def _evaluate_code_event_unlocked(
        self, event: EventRule, now_ts: float
    ) -> List[Dict[str, Any]]:
        if not event.code.strip():
            raise ValueError("Code event has empty script.")

        for ref in event.required_skills:
            kit = self.state.kits_by_id.get(ref.kit_id)
            if kit is None:
                event.enabled = False
                event.status = "DEAD"
                event.lock_reason = f"KIT removed: {ref.kit_id}"
                return []
            if ref.skill_id not in kit.skills:
                raise ValueError(f"SKILL {ref.skill_id} not found on KIT {ref.kit_id}.")
            if kit.status != "ONLINE":
                self._lock_event(event, f"Required KIT offline: {ref.kit_id}")
                return []

        local_scope: Dict[str, Any] = {}
        exec(event.code, {"__builtins__": SAFE_BUILTINS}, local_scope)
        evaluate_fn = local_scope.get("evaluate")
        if not callable(evaluate_fn):
            raise ValueError("Code mode must define function evaluate(ctx).")

        result = evaluate_fn(self._code_context_unlocked())
        trigger, actions = self._parse_code_result_unlocked(event, result)
        if not trigger:
            event.status = "IDLE"
            event.lock_reason = None
            return []

        if not self._can_trigger(event, now_ts):
            event.status = "WORKING"
            event.lock_reason = None
            return []

        commands: List[Dict[str, Any]] = []
        for action in actions:
            self._validate_action_target_unlocked(action)
            commands.append(
                {"topic": self._build_topic(action), "payload": dict(action.payload)}
            )

        event.last_triggered_at = utc_now()
        event.status = "WORKING"
        event.lock_reason = None
        event.touch()
        return commands

    def _run(self) -> None:
        frame_interval = 1.0 / self.frame_hz
        counter = 0
        counter_start = time.perf_counter()

        while not self._stop.is_set():
            frame_start = time.perf_counter()
            now_ts = time.time()
            commands: List[Dict[str, Any]] = []
            changed = False

            with self.state.lock:
                for event in self.state.events.values():
                    before = (event.status, event.lock_reason, event.last_triggered_at)
                    if not event.enabled:
                        blocked_reason = self.state._event_enable_block_reason_unlocked(event)
                        if event.status == "DEAD":
                            if blocked_reason and event.lock_reason != blocked_reason:
                                event.lock_reason = blocked_reason
                        elif blocked_reason:
                            lowered = blocked_reason.lower()
                            next_status = "LOCKED" if "offline" in lowered else "ERROR"
                            if (
                                event.status != next_status
                                or event.lock_reason != blocked_reason
                            ):
                                event.status = next_status
                                event.lock_reason = blocked_reason
                        elif event.status != "IDLE" or event.lock_reason is not None:
                            event.status = "IDLE"
                            event.lock_reason = None
                        if (event.status, event.lock_reason, event.last_triggered_at) != before:
                            changed = True
                        continue

                    if event.status == "DEAD":
                        if (event.status, event.lock_reason, event.last_triggered_at) != before:
                            changed = True
                        continue

                    try:
                        mode = str(event.mode).strip().lower()
                        if mode == "form":
                            commands.extend(
                                self._evaluate_form_event_unlocked(event, now_ts)
                            )
                        elif mode == "code":
                            commands.extend(
                                self._evaluate_code_event_unlocked(event, now_ts)
                            )
                        else:
                            event.status = "ERROR"
                            event.lock_reason = f"Unsupported mode: {event.mode}"
                    except Exception as exc:
                        event.status = "ERROR"
                        event.lock_reason = str(exc)
                    if (event.status, event.lock_reason, event.last_triggered_at) != before:
                        changed = True

                if commands or changed:
                    self.state.revision += 1

            for command in commands:
                try:
                    self.publish(
                        command["topic"], command["payload"], 1, False  # qos  # retain
                    )
                    self.state.clear_runtime_error("engine")
                except Exception as exc:
                    self.state.set_runtime_error(
                        "engine", f"Publish failed for {command['topic']}: {exc}"
                    )

            counter += 1
            elapsed_counter = time.perf_counter() - counter_start
            if elapsed_counter >= 1.0:
                self.state.set_frame_tps(counter / elapsed_counter)
                counter = 0
                counter_start = time.perf_counter()

            elapsed = time.perf_counter() - frame_start
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)


class Housekeeper:
    def __init__(
        self,
        state: RuntimeState,
        offline_timeout_sec: float,
        interval_sec: float,
        announce: Optional[AnnounceFn] = None,
        announce_interval_sec: float = 5.0,
    ) -> None:
        self.state = state
        self.offline_timeout_sec = offline_timeout_sec
        self.interval_sec = interval_sec
        self.announce = announce
        self.announce_interval_sec = announce_interval_sec
        self._stop = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="magi-housekeeper", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        last_announce = 0.0
        while not self._stop.is_set():
            self.state.mark_offline_if_stale(self.offline_timeout_sec)
            self.state.refresh_event_locks()
            if self.announce is not None:
                now_ts = time.time()
                if (now_ts - last_announce) >= self.announce_interval_sec:
                    try:
                        self.announce()
                        self.state.clear_runtime_error("announce")
                    except Exception as exc:
                        self.state.set_runtime_error("announce", str(exc))
                    last_announce = now_ts
            self._stop.wait(self.interval_sec)
