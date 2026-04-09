from dataclasses import dataclass
from pathlib import Path
import os


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    return int(value)


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    pool_id: str
    pool_name: str
    gate_id: str
    gate_name: str
    profile_configured: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_keepalive: int
    mqtt_client_id: str
    frame_hz: float
    housekeeper_interval_sec: float
    offline_timeout_sec: float
    default_event_cooldown_ms: int
    stream_interval_sec: float
    api_host: str
    api_port: int
    announce_interval_sec: float
    data_dir: Path
    frontend_dist: Path
    profile_store: Path
    kit_store: Path


def load_settings() -> Settings:
    backend_root = Path(__file__).resolve().parents[1]
    project_root = backend_root.parent

    pool_id = os.getenv("ZC_POOL_ID", "POOL_ZC").strip().upper()
    gate_id = os.getenv("ZC_GATE_ID", "GATE_01").strip().upper()
    pool_name = os.getenv("ZC_POOL_NAME", pool_id).strip() or pool_id
    gate_name = os.getenv("ZC_GATE_NAME", gate_id).strip() or gate_id
    profile_configured = os.getenv("ZC_PROFILE_CONFIGURED", "0").strip() not in {
        "0",
        "false",
        "False",
    }
    mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
    mqtt_port = _env_int("MQTT_PORT", 1883)
    mqtt_username = os.getenv("MQTT_USERNAME", "")
    mqtt_password = os.getenv("MQTT_PASSWORD", "")
    mqtt_keepalive = _env_int("MQTT_KEEPALIVE", 30)

    mqtt_client_id = os.getenv("MQTT_CLIENT_ID", f"{gate_id}_MAGI")

    data_dir = Path(os.getenv("ZC_DATA_DIR", str(backend_root / "data")))
    frontend_dist = Path(
        os.getenv("ZC_FRONTEND_DIST", str(project_root / "frontend" / "dist"))
    )
    profile_store = Path(os.getenv("ZC_PROFILE_STORE", str(data_dir / "profile.json")))
    kit_store = Path(os.getenv("ZC_KIT_STORE", str(data_dir / "kits.json")))

    return Settings(
        pool_id=pool_id,
        pool_name=pool_name,
        gate_id=gate_id,
        gate_name=gate_name,
        profile_configured=profile_configured,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_username=mqtt_username,
        mqtt_password=mqtt_password,
        mqtt_keepalive=mqtt_keepalive,
        mqtt_client_id=mqtt_client_id,
        frame_hz=_env_float("MAGI_FRAME_HZ", 60.0),
        housekeeper_interval_sec=_env_float("HOUSEKEEPER_INTERVAL_SEC", 1.0),
        offline_timeout_sec=_env_float("OFFLINE_TIMEOUT_SEC", 10.0),
        default_event_cooldown_ms=_env_int("DEFAULT_EVENT_COOLDOWN_MS", 1000),
        stream_interval_sec=_env_float("STATE_STREAM_INTERVAL_SEC", 0.4),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=_env_int("API_PORT", 8080),
        announce_interval_sec=_env_float("POOL_ANNOUNCE_INTERVAL_SEC", 5.0),
        data_dir=data_dir,
        frontend_dist=frontend_dist,
        profile_store=profile_store,
        kit_store=kit_store,
    )
