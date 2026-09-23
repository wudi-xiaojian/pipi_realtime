from pathlib import Path

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config.settings import settings
from backend.realtime.session import RealtimeSession


# ============================================================
# Project paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


# ============================================================
# FastAPI
# ============================================================

app = FastAPI(
    title="PiPi Realtime Agent",
    version="0.1.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Static files
# ============================================================

app.mount(
    "/web",
    StaticFiles(
        directory=WEB_DIR
    ),
    name="web",
)


# ============================================================
# Home
# ============================================================

@app.get("/")
async def index():

    return FileResponse(
        WEB_DIR / "index.html"
    )


# ============================================================
# Health
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "service": "pipi-realtime",
    }


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):

    await websocket.accept()

    print(
        "[WebSocket] Browser connected"
    )

    session = RealtimeSession(
        websocket
    )

    try:

        # ------------------------------------------------------
        # Start Qwen
        # ------------------------------------------------------

        await session.start()

        # ------------------------------------------------------
        # Browser receive loop
        # ------------------------------------------------------

        while True:

            try:

                message = (
                    await websocket.receive()
                )

            except WebSocketDisconnect:

                print(
                    "[WebSocket] Browser disconnected"
                )

                break

            # --------------------------------------------------
            # IMPORTANT:
            #
            # FastAPI/Starlette can return a disconnect
            # message instead of raising immediately.
            #
            # Never call receive() again after this.
            # --------------------------------------------------

            message_type = message.get(
                "type"
            )

            if (
                message_type
                == "websocket.disconnect"
            ):

                print(
                    "[WebSocket] Disconnect message received"
                )

                break

            # --------------------------------------------------
            # Binary audio
            # --------------------------------------------------

            if "bytes" in message:

                audio_data = message.get(
                    "bytes"
                )

                if audio_data:

                    await session.handle_browser_message(
                        audio_data
                    )

            # --------------------------------------------------
            # JSON control message
            # --------------------------------------------------

            elif "text" in message:

                text_data = message.get(
                    "text"
                )

                if text_data:

                    await session.handle_browser_message(
                        text_data
                    )

    except WebSocketDisconnect:

        print(
            "[WebSocket] Browser disconnected"
        )

    except Exception as exc:

        print(
            f"[WebSocket] Error: {exc}"
        )

        # 浏览器可能已经断开，因此不要强制发送错误
        try:

            await session.send_browser_event(
                {
                    "type": "error",
                    "message": str(exc),
                }
            )

        except Exception:
            pass

    finally:

        try:

            await session.close()

        except Exception as exc:

            print(
                "[WebSocket] "
                f"Session close error: {exc}"
            )

        print(
            "[WebSocket] Session closed"
        )


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )