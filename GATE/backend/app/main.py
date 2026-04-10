from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from .api import create_router
from .config import load_settings
from .engine import FrameEngine, Housekeeper
from .models import GateProfile
from .mqtt_gateway import MqttGateway
from .state import RuntimeState
from .storage import load_event_rows, load_json_object


settings = load_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
event_store = settings.data_dir / "events.json"
profile_store = settings.profile_store
kit_store = settings.kit_store

default_profile = GateProfile(
    pool_id=settings.pool_id,
    pool_name=settings.pool_name,
    gate_id=settings.gate_id,
    gate_name=settings.gate_name,
    configured=settings.profile_configured,
)
stored_profile = load_json_object(profile_store, default={})
profile = GateProfile.from_dict(
    data=stored_profile,
    default_pool_id=default_profile.pool_id,
    default_pool_name=default_profile.pool_name,
    default_gate_id=default_profile.gate_id,
    default_gate_name=default_profile.gate_name,
    default_configured=default_profile.configured,
)

runtime_state = RuntimeState(
    profile=profile,
    default_event_cooldown_ms=settings.default_event_cooldown_ms,
    stream_interval_sec=settings.stream_interval_sec,
)
runtime_state.load_kit_aliases(load_json_object(kit_store, default={}))
runtime_state.load_events(load_event_rows(event_store))

mqtt_gateway = MqttGateway(settings, runtime_state)
frame_engine = FrameEngine(
    state=runtime_state, publish=mqtt_gateway.publish_json, frame_hz=settings.frame_hz
)
housekeeper = Housekeeper(
    state=runtime_state,
    offline_timeout_sec=settings.offline_timeout_sec,
    interval_sec=settings.housekeeper_interval_sec,
    announce=mqtt_gateway.announce_profile,
    announce_interval_sec=settings.announce_interval_sec,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    mqtt_gateway.start()
    frame_engine.start()
    housekeeper.start()
    try:
        yield
    finally:
        housekeeper.stop()
        frame_engine.stop()
        mqtt_gateway.stop()


app = FastAPI(
    title="ZeroCloud GATE / MAGI",
    version="3.1.0",
    description="ZeroCloud Edge Brain on POOL-GATE-KIT architecture.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    create_router(
        runtime_state,
        mqtt_gateway,
        event_store=event_store,
        profile_store=profile_store,
        kit_store=kit_store,
        default_pool_id=settings.pool_id,
        default_pool_name=settings.pool_name,
        default_gate_id=settings.gate_id,
        default_gate_name=settings.gate_name,
    )
)

if settings.frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")


@app.get("/")
def root():
    profile = runtime_state.profile_snapshot()
    return {
        "service": "ZeroCloud GATE",
        "status": "ready",
        "pool_id": profile["pool_id"],
        "gate_id": profile["gate_id"],
        "hint": "Build frontend at ./frontend to serve web console from backend.",
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
