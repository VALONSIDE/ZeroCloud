from app.mqtt_gateway import MqttGateway


def test_extract_skill_bundle_supports_compact_descriptors():
    payload = {
        "skills": [
            {"id": "SKILL_TEMP", "io": "input"},
            {
                "id": "SKILL_SPK_NOTIFY",
                "io": "output",
                "action": "play",
                "supports_duration": 1,
            },
        ]
    }

    skills, skill_meta = MqttGateway._extract_skill_bundle(payload)

    assert skills == ["SKILL_SPK_NOTIFY", "SKILL_TEMP"]
    assert skill_meta["SKILL_TEMP"]["io_type"] == "input"
    assert skill_meta["SKILL_SPK_NOTIFY"]["io_type"] == "output"
    assert skill_meta["SKILL_SPK_NOTIFY"]["actions"] == ["PLAY"]
    assert skill_meta["SKILL_SPK_NOTIFY"]["supports_duration"] is True


def test_extract_skill_bundle_supports_action_specs():
    payload = {
        "skills": [
            {
                "id": "SKILL_SPEAKER",
                "io": "output",
                "actions": [
                    {
                        "name": "RING",
                        "params": [
                            {
                                "key": "times",
                                "type": "number",
                                "required": True,
                                "min": 1,
                                "max": 10,
                            },
                            {
                                "key": "mode",
                                "type": "enum",
                                "options": ["soft", "hard"],
                            },
                        ],
                    }
                ],
            }
        ]
    }

    skills, skill_meta = MqttGateway._extract_skill_bundle(payload)
    assert skills == ["SKILL_SPEAKER"]
    assert skill_meta["SKILL_SPEAKER"]["actions"] == ["RING"]
    specs = skill_meta["SKILL_SPEAKER"]["action_specs"]["RING"]
    assert specs[0]["key"] == "times"
    assert specs[0]["type"] == "number"
    assert specs[0]["required"] is True
    assert specs[1]["key"] == "mode"
    assert specs[1]["type"] == "enum"
