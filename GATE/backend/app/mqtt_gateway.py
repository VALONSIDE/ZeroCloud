from __future__ import annotations

from typing import Any, Dict, List, Tuple
import json

import paho.mqtt.client as mqtt

from .config import Settings
from .state import RuntimeState


class MqttGateway:
    def __init__(self, settings: Settings, state: RuntimeState) -> None:
        self.settings = settings
        self.state = state
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
        if settings.mqtt_username:
            self.client.username_pw_set(
                username=settings.mqtt_username, password=settings.mqtt_password
            )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self) -> None:
        self.client.connect_async(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            self.settings.mqtt_keepalive,
        )
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish_json(
        self, topic: str, payload: Dict[str, Any], qos: int = 1, retain: bool = False
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result = self.client.publish(topic=topic, payload=body, qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed ({result.rc}) on topic {topic}.")

    def announce_profile(self) -> None:
        profile = self.state.profile_snapshot()
        if not profile.get("configured"):
            return
        topic = (
            f"{profile['pool_id']}/{profile['gate_id']}/SYS_GATE/PROFILE/ANNOUNCE"
        )
        payload = {
            "kind": "GATE_PROFILE",
            "pool_id": profile["pool_id"],
            "pool_name": profile["pool_name"],
            "gate_id": profile["gate_id"],
            "gate_name": profile["gate_name"],
        }
        self.publish_json(topic=topic, payload=payload, qos=1, retain=True)
        self.state.observe_pool(
            pool_id=profile["pool_id"],
            gate_id=profile["gate_id"],
            pool_name=profile["pool_name"],
            gate_name=profile["gate_name"],
        )

    @staticmethod
    def _normalize_action_fields(raw_fields: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_fields, list):
            return []
        fields: List[Dict[str, Any]] = []
        for raw in raw_fields:
            if not isinstance(raw, dict):
                continue
            key = str(
                raw.get("key") or raw.get("name") or raw.get("id") or ""
            ).strip()
            if not key:
                continue
            field: Dict[str, Any] = {"key": key}
            field_type = str(raw.get("type", "string")).strip().lower()
            if field_type not in {"string", "number", "boolean", "enum", "json"}:
                field_type = "string"
            field["type"] = field_type
            if "label" in raw:
                field["label"] = str(raw.get("label", "")).strip() or key
            if "required" in raw:
                field["required"] = bool(raw.get("required"))
            if "default" in raw:
                field["default"] = raw.get("default")
            if isinstance(raw.get("min"), (int, float)):
                field["min"] = raw.get("min")
            if isinstance(raw.get("max"), (int, float)):
                field["max"] = raw.get("max")
            options = raw.get("options")
            if isinstance(options, list):
                option_values = [str(item) for item in options if str(item).strip()]
                if option_values:
                    field["options"] = option_values
            if "placeholder" in raw:
                field["placeholder"] = str(raw.get("placeholder", "")).strip()
            fields.append(field)
        return fields

    @classmethod
    def _normalize_actions(
        cls, raw_actions: Any
    ) -> Tuple[List[str], Dict[str, List[Dict[str, Any]]]]:
        actions: set[str] = set()
        action_specs: Dict[str, List[Dict[str, Any]]] = {}

        if isinstance(raw_actions, str):
            text = raw_actions.strip().upper()
            if text:
                actions.add(text)
            return sorted(actions), action_specs

        if isinstance(raw_actions, list):
            for item in raw_actions:
                if isinstance(item, str):
                    text = item.strip().upper()
                    if text:
                        actions.add(text)
                    continue
                if not isinstance(item, dict):
                    continue
                action_name = str(
                    item.get("name") or item.get("action") or item.get("id") or ""
                ).strip().upper()
                if not action_name:
                    continue
                actions.add(action_name)
                raw_fields = (
                    item.get("params")
                    if "params" in item
                    else item.get("payload")
                    if "payload" in item
                    else item.get("args")
                    if "args" in item
                    else item.get("fields")
                )
                fields = cls._normalize_action_fields(raw_fields)
                if fields:
                    action_specs[action_name] = fields
            return sorted(actions), action_specs

        if isinstance(raw_actions, dict):
            # Mapping form: {"SET":[...fields...], "PLAY":[...]}
            for action_name, raw in raw_actions.items():
                normalized_action = str(action_name).strip().upper()
                if not normalized_action:
                    continue
                actions.add(normalized_action)
                fields = cls._normalize_action_fields(raw)
                if fields:
                    action_specs[normalized_action] = fields
            return sorted(actions), action_specs

        return [], {}

    @staticmethod
    def _decode_payload(raw: bytes) -> Dict[str, Any]:
        text = raw.decode("utf-8", errors="ignore")
        if text.strip() == "":
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
        if isinstance(payload, dict):
            return payload
        return {"value": payload}

    @staticmethod
    def _extract_skill_bundle(
        payload: Dict[str, Any],
    ) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
        raw_skills = payload.get("skills", [])
        if not isinstance(raw_skills, list):
            raw_skills = []

        skills: List[str] = []
        skill_meta: Dict[str, Dict[str, Any]] = {}

        for raw_skill in raw_skills:
            if isinstance(raw_skill, str):
                skill_id = raw_skill.strip()
                if skill_id:
                    skills.append(skill_id)
                continue

            if not isinstance(raw_skill, dict):
                continue

            skill_id = str(
                raw_skill.get("skill_id")
                or raw_skill.get("id")
                or raw_skill.get("name")
                or ""
            ).strip()
            if not skill_id:
                continue
            skills.append(skill_id)

            meta: Dict[str, Any] = {}
            io_type = str(
                raw_skill.get("io_type") or raw_skill.get("io") or ""
            ).strip().lower()
            if io_type in {"input", "output"}:
                meta["io_type"] = io_type

            supports_duration = raw_skill.get("supports_duration")
            if isinstance(supports_duration, bool):
                meta["supports_duration"] = supports_duration
            elif isinstance(supports_duration, (int, float)):
                meta["supports_duration"] = bool(supports_duration)

            actions_raw = raw_skill.get("actions", raw_skill.get("action"))
            normalized_actions, action_specs = MqttGateway._normalize_actions(actions_raw)
            extra_actions, extra_specs = MqttGateway._normalize_actions(
                raw_skill.get("action_specs")
            )
            if extra_actions:
                normalized_actions = sorted(set(normalized_actions).union(set(extra_actions)))
            if extra_specs:
                merged_specs = dict(action_specs)
                merged_specs.update(extra_specs)
                action_specs = merged_specs
            if normalized_actions:
                meta["actions"] = normalized_actions
            if action_specs:
                meta["action_specs"] = action_specs

            if meta:
                skill_meta[skill_id] = meta

        raw_meta = payload.get("skills_meta")
        if isinstance(raw_meta, dict):
            for skill_id, raw in raw_meta.items():
                if not isinstance(raw, dict):
                    continue
                key = str(skill_id).strip()
                if not key:
                    continue
                skills.append(key)
                merged = dict(skill_meta.get(key, {}))

                io_type = str(raw.get("io_type", "")).strip().lower()
                if io_type in {"input", "output"}:
                    merged["io_type"] = io_type

                supports_duration = raw.get("supports_duration")
                if isinstance(supports_duration, bool):
                    merged["supports_duration"] = supports_duration
                elif isinstance(supports_duration, (int, float)):
                    merged["supports_duration"] = bool(supports_duration)

                actions_raw = raw.get("actions", raw.get("action"))
                normalized_actions, action_specs = MqttGateway._normalize_actions(
                    actions_raw
                )
                extra_actions, extra_specs = MqttGateway._normalize_actions(
                    raw.get("action_specs")
                )
                if extra_actions:
                    normalized_actions = sorted(
                        set(normalized_actions).union(set(extra_actions))
                    )
                if extra_specs:
                    merged_specs = dict(action_specs)
                    merged_specs.update(extra_specs)
                    action_specs = merged_specs
                if normalized_actions:
                    merged["actions"] = normalized_actions
                if action_specs:
                    merged["action_specs"] = action_specs
                if merged:
                    skill_meta[key] = merged

        return sorted(set(skills)), skill_meta

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Any,
    ) -> None:
        del userdata, flags, properties
        if reason_code.value != 0:
            self.state.set_mqtt_status(False, f"Connect rejected: {reason_code}")
            return

        client.subscribe("#", qos=1)
        self.state.set_mqtt_status(True)
        try:
            self.announce_profile()
        except Exception as exc:
            self.state.set_runtime_error("mqtt", f"Announce failed: {exc}")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Any,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        self.state.set_mqtt_status(False, f"Disconnected: {reason_code}")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata
        topic = msg.topic
        parts = topic.split("/")
        if len(parts) < 2:
            return

        pool_id = parts[0].strip().upper()
        if not pool_id:
            return

        payload = self._decode_payload(msg.payload)
        gate_id = (
            parts[1].strip().upper()
            if len(parts) > 1 and parts[1] not in {"PENDING", "PROVISION"}
            else None
        )
        profile = self.state.profile_snapshot()
        if (
            not profile.get("configured")
            and gate_id
            and gate_id == profile.get("gate_id")
        ):
            # Ignore retained traffic from the old local identity after factory reset.
            return
        self.state.observe_pool(pool_id=pool_id, gate_id=gate_id)

        if len(parts) >= 5 and parts[2] == "SYS_GATE" and parts[3] == "PROFILE" and parts[4] == "ANNOUNCE":
            self.state.observe_pool(
                pool_id=pool_id,
                gate_id=gate_id,
                pool_name=str(payload.get("pool_name", "")).strip() or pool_id,
                gate_name=str(payload.get("gate_name", "")).strip() or (gate_id or ""),
            )
            return

        if parts[1] == "PENDING" and len(parts) >= 3:
            uid = parts[2]
            skills, _ = self._extract_skill_bundle(payload)
            self.state.upsert_pending(
                pool_id=pool_id,
                uid=uid,
                skills=skills,
                payload=payload,
            )
            return

        if len(parts) < 4:
            return

        kit_id = parts[2]
        skill_or_status = parts[3]
        if skill_or_status == "STATUS":
            status = str(payload.get("status", "ONLINE")).upper()
            skills, skill_meta = self._extract_skill_bundle(payload)
            uid_hint = payload.get("uid")
            self.state.upsert_kit_status(
                pool_id=pool_id,
                gate_id=gate_id or "",
                kit_id=kit_id,
                status=status,
                skills=skills,
                skill_meta=skill_meta,
                uid_hint=uid_hint,
            )
            return

        # Command topics like .../SKILL_DISPLAY/SET are outbound control paths.
        if len(parts) >= 5:
            return

        value = payload.get("value") if "value" in payload else payload
        self.state.upsert_skill_value(
            pool_id=pool_id,
            gate_id=gate_id or "",
            kit_id=kit_id,
            skill_id=skill_or_status,
            value=value,
        )
