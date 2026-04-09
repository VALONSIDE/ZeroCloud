from __future__ import annotations

from typing import Any, Dict, List
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
    def _extract_skills(payload: Dict[str, Any]) -> List[str]:
        raw_skills = payload.get("skills", [])
        if not isinstance(raw_skills, list):
            return []
        skills: List[str] = []
        for skill in raw_skills:
            text = str(skill).strip()
            if text:
                skills.append(text)
        return skills

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
            skills = self._extract_skills(payload)
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
            skills = self._extract_skills(payload)
            uid_hint = payload.get("uid")
            self.state.upsert_kit_status(
                pool_id=pool_id,
                gate_id=gate_id or "",
                kit_id=kit_id,
                status=status,
                skills=skills,
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
