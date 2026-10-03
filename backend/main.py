import sys
import logging
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlalchemy.exc

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from backend.core.logging_security import install_secret_redaction

install_secret_redaction()

# Silence repetitive routine HTTP 200 access logs from polluting the developer terminal
logging.getLogger("uvicorn.access").handlers = []
logging.getLogger("uvicorn.access").propagate = False
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger("nexus")

from dotenv import load_dotenv

# Ensure environment variables from .env are loaded
load_dotenv()

from backend.api.settings import router as settings_router
from backend.api.nexus import router as nexus_router
from backend.api.tts import router as tts_router
from backend.api.auth import router as auth_router
from backend.api.history import router as history_router
from backend.api.skills import router as skills_router
from backend.api.scheduled_tasks import router as scheduled_tasks_router
from backend.api.connectors import router as connectors_router
from backend.api.email import router as email_router
from backend.services.scheduler_service import scheduler_service
from backend.agent.tools.web_automation.extension_bridge import extension_bridge
from backend.core.extension_installer import ensure_installed, get_extension_path
from fastapi import WebSocket, WebSocketDisconnect

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_installed()
    try:
        from backend.connectors.manager import connector_manager
        await connector_manager.initialize_connected_tools("default")
    except Exception as e:
        logger.warning(f"Could not initialize connectors on startup: {e}")
    await scheduler_service.start()
    yield
    await scheduler_service.stop()

app = FastAPI(title="NEXUS", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron renderer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import JSONResponse
from starlette.requests import Request
from sqlalchemy.exc import DBAPIError, OperationalError

@app.exception_handler(TimeoutError)
async def timeout_exception_handler(request: Request, exc: TimeoutError):
    logger.warning(f"[API] Handled timeout on {request.url.path} (database warming up): {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database connection warming up. Please retry shortly.", "retry": True},
    )

@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    logger.warning(f"[API] Handled OperationalError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database connection warming up or temporarily unavailable.", "retry": True},
    )

@app.exception_handler(DBAPIError)
async def dbapi_error_handler(request: Request, exc: DBAPIError):
    logger.warning(f"[API] Handled DBAPIError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Database query could not be completed.", "retry": True},
    )

app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(nexus_router, prefix="/api/nexus", tags=["nexus"])
app.include_router(tts_router, prefix="/api/nexus", tags=["tts"])
app.include_router(tts_router, prefix="/api", tags=["tts"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(history_router, prefix="/api/history", tags=["history"])
app.include_router(skills_router, prefix="/api/skills", tags=["skills"])
app.include_router(scheduled_tasks_router, prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])
app.include_router(connectors_router, prefix="/api/connectors", tags=["connectors"])
app.include_router(email_router, tags=["email"])


@app.exception_handler(TimeoutError)
async def timeout_error_handler(request: Request, exc: TimeoutError):
    logger.warning("[API] Database or operation timed out on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database connection is warming up or temporarily unavailable. Please retry in a moment.",
            "type": "DatabaseTimeoutError",
        },
    )


@app.exception_handler(sqlalchemy.exc.DBAPIError)
async def dbapi_error_handler(request: Request, exc: sqlalchemy.exc.DBAPIError):
    logger.warning("[API] Database error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database is temporarily unreachable or warming up. Please retry shortly.",
            "type": "DatabaseUnavailableError",
        },
    )


@app.websocket("/ws/extension")
async def extension_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await extension_bridge.register_socket(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            extension_bridge.handle_incoming_message(text)
    except WebSocketDisconnect:
        await extension_bridge.unregister_socket(websocket)
    except Exception:
        await extension_bridge.unregister_socket(websocket)


@app.get("/api/extension/status")
async def extension_status():
    return {
        "connected": extension_bridge.is_connected(),
        "extension_path": str(get_extension_path()),
    }


from pydantic import BaseModel


class ExtensionCommandRequest(BaseModel):
    action: str
    payload: dict = {}
    timeout: float = 10.0


@app.post("/api/extension/command")
async def extension_command(req: ExtensionCommandRequest):
    try:
        data = await extension_bridge.send_command(req.action, req.payload, timeout=req.timeout)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "NEXUS"}


@app.get("/api/system/health")
async def system_health():
    from backend.core.auto_healer import auto_healer
    return auto_healer.get_health_report().model_dump()


@app.post("/api/system/recover")
async def system_recover():
    from backend.core.auto_healer import auto_healer
    return auto_healer.recover_system_state()


from fastapi.responses import HTMLResponse


@app.get("/test-harness", response_class=HTMLResponse)
async def test_harness():
    return """<!DOCTYPE html>
<html>
<head><title>NEXUS Extension Verification Page</title></head>
<body style="font-family: sans-serif; padding: 2rem;">
    <h1>NEXUS Extension Test Page</h1>
    <div id="status">Ready</div>
    <p><input id="test-input" type="text" placeholder="Type here..." /></p>
    <p><button id="test-btn" onclick="document.getElementById('status').innerText = 'BUTTON_CLICKED_SUCCESS'; this.innerText = 'Clicked!';">Click Me</button></p>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True, access_log=False)
