from __future__ import annotations

import ipaddress
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers.control import router as control_router
from app.routers.data import router as data_router
from app.routers.logs import router as logs_router
from app.routers.model import router as model_router
from app.routers.paper import router as paper_router
from app.routers.status import router as status_router
from app.services.auto_pipeline import start_auto_pipeline_scheduler, stop_auto_pipeline_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_auto_pipeline_scheduler()
    try:
        yield
    finally:
        stop_auto_pipeline_scheduler()

app = FastAPI(
    title="Aistock Control Panel API",
    version="0.1.0",
    description="Observability, workflow control, and paper-trading integration API for the A-share quant workflow.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3030", "http://127.0.0.1:3030", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in get_settings().panel_api_allowed_cidrs:
        networks.append(ipaddress.ip_network(cidr, strict=False))
    return tuple(networks)


def _allowed_service_ips() -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    allowed: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for service_name in get_settings().panel_api_allowed_service_names:
        try:
            infos = socket.getaddrinfo(service_name, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for info in infos:
            raw_ip = info[4][0]
            if raw_ip in seen:
                continue
            seen.add(raw_ip)
            try:
                allowed.append(ipaddress.ip_address(raw_ip))
            except ValueError:
                continue
    return tuple(allowed)


ALLOWED_NETWORKS = _allowed_networks()


@app.middleware("http")
async def restrict_api_clients(request: Request, call_next):
    client = request.client
    if client is None:
        return JSONResponse(status_code=403, content={"detail": "API client IP missing."})

    try:
        client_ip = ipaddress.ip_address(client.host)
    except ValueError:
        return JSONResponse(status_code=403, content={"detail": "API client IP invalid."})

    if any(client_ip in network for network in ALLOWED_NETWORKS) or client_ip in _allowed_service_ips():
        return await call_next(request)

    return JSONResponse(status_code=403, content={"detail": "API access is restricted to localhost and trusted local services."})


app.include_router(status_router)
app.include_router(logs_router)
app.include_router(data_router)
app.include_router(model_router)
app.include_router(paper_router)
app.include_router(control_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": "Aistock Control Panel API",
        "routes": [
            "/api/status/batch",
            "/api/status/workflow",
            "/api/status/pipeline",
            "/api/logs/batch",
            "/api/data/summary",
            "/api/data/pipeline",
            "/api/data/explorer/catalog",
            "/api/data/explorer/query",
            "/api/data/explorer/export",
            "/api/data/stocks",
            "/api/data/stock/{code}",
            "/api/model/latest",
            "/api/model/picks",
            "/api/paper/status",
            "/api/paper/overview",
            "/api/paper/targets",
            "/api/paper/positions",
            "/api/paper/orders",
            "/api/paper/history",
            "/api/control/batch/start",
            "/api/control/batch/stop",
            "/api/control/pipeline/start",
            "/api/control/pipeline/stop",
            "/api/control/step/{step_key}/start",
            "/api/control/step/{step_key}/stop",
            "/api/control/paper/start",
            "/api/control/paper/stop",
        ],
    }
