from __future__ import annotations

from typing import Any, Dict, List


CODE_FRAMEWORK = """\
def evaluate(ctx):
    # ctx["get"](kit_id, skill_id, default=...) 读取实时值。
    # 若 kit/skill 不存在会抛错并让该 EVENT 进入 ERROR 状态。
    temp = ctx["get"]("KIT_001", "SKILL_TEMP", default=None)
    hum = ctx["get"]("KIT_001", "SKILL_HUM", default=None)

    if temp is None or hum is None:
        return {"trigger": False}

    if temp > 30 and hum > 70:
        return {
            "trigger": True,
            "actions": [
                {
                    "target_kit_id": "KIT_002",
                    "target_skill": "SKILL_DISPLAY",
                    "action": "SET",
                    "payload": {"msg": "HOT&HUM", "duration": 5000},
                }
            ],
        }
    return {"trigger": False}
"""


def builtin_event_templates() -> List[Dict[str, Any]]:
    return [
        {
            "template_id": "temp-display-alert",
            "mode": "form",
            "name": "温度超阈值告警",
            "description": "当温度超过阈值时，向目标设备 DISPLAY 下发告警消息。",
            "payload": {
                "cooldown_ms": 1500,
                "condition": {
                    "source_skill": "SKILL_TEMP",
                    "operator": ">",
                    "threshold": 30,
                },
                "action": {
                    "target_skill": "SKILL_DISPLAY",
                    "action": "SET",
                    "payload": {"msg": "TEMP ALERT", "duration": 5000},
                },
            },
        },
        {
            "template_id": "hum-display-alert",
            "mode": "form",
            "name": "湿度超阈值告警",
            "description": "当湿度超过阈值时，向目标设备 DISPLAY 下发告警消息。",
            "payload": {
                "cooldown_ms": 1500,
                "condition": {
                    "source_skill": "SKILL_HUM",
                    "operator": ">",
                    "threshold": 75,
                },
                "action": {
                    "target_skill": "SKILL_DISPLAY",
                    "action": "SET",
                    "payload": {"msg": "HUM ALERT", "duration": 5000},
                },
            },
        },
        {
            "template_id": "temp-hum-dual-check",
            "mode": "code",
            "name": "温湿双条件联动",
            "description": "复杂逻辑示例：同时满足温度和湿度条件才触发。",
            "payload": {
                "cooldown_ms": 1500,
                "required_skills": [
                    {"kit_id": "KIT_001", "skill_id": "SKILL_TEMP"},
                    {"kit_id": "KIT_001", "skill_id": "SKILL_HUM"},
                ],
                "code": CODE_FRAMEWORK,
            },
        },
    ]
