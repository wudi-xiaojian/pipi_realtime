import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import WebSocket

from backend.config.settings import settings
from backend.realtime.qwen_client import (
    QwenRealtimeClient,
)


class RealtimeSession:
    """
    One browser connection corresponds to one
    Qwen Realtime session.
    """

    def __init__(
        self,
        browser_ws: WebSocket,
    ):
        self.browser_ws = browser_ws

        self.qwen: Optional[
            QwenRealtimeClient
        ] = None

        self.running = False

        self.qwen_receive_task: Optional[
            asyncio.Task
        ] = None

        self.browser_connected = True

        # 当前 Qwen 是否正在输出回答
        self.response_active = False

    # ============================================================
    # Start
    # ============================================================

    async def start(self) -> None:

        self.qwen = QwenRealtimeClient(
            api_key=settings.api_key,
            websocket_url=settings.qwen_ws_url,
            workspace_id=settings.workspace_id,
            voice=settings.voice,
            system_prompt=settings.system_prompt,
            vad_type=settings.vad_type,
            vad_threshold=settings.vad_threshold,
            vad_silence_duration_ms=(
                settings.vad_silence_duration_ms
            ),
            max_history_turns=(
                settings.max_history_turns
            ),
            debug=settings.debug,
        )

        await self.qwen.connect()

        self.running = True

        await self.send_browser_event(
            {
                "type": "session_ready",
                "message": "Qwen Realtime 已连接",
            }
        )

        self.qwen_receive_task = (
            asyncio.create_task(
                self.forward_qwen_events()
            )
        )

    # ============================================================
    # Browser messages
    # ============================================================

    async def handle_browser_message(
        self,
        message: Any,
    ) -> None:

        if not self.running:
            return

        if not self.qwen:
            return

        # --------------------------------------------------------
        # Audio
        # --------------------------------------------------------

        if isinstance(message, bytes):

            if not message:
                return

            await self.qwen.send_audio(
                message
            )

            return

        # --------------------------------------------------------
        # JSON control message
        # --------------------------------------------------------

        if not isinstance(message, str):
            return

        try:

            data = json.loads(message)

        except json.JSONDecodeError:

            await self.send_browser_event(
                {
                    "type": "error",
                    "message": (
                        "浏览器发送了无效 JSON"
                    ),
                }
            )

            return

        message_type = data.get("type")

        # --------------------------------------------------------
        # Start
        # --------------------------------------------------------

        if message_type == "start":

            await self.send_browser_event(
                {
                    "type": "state",
                    "state": "listening",
                }
            )

        # --------------------------------------------------------
        # Stop
        # --------------------------------------------------------

        elif message_type == "stop":

            await self.cancel_response()

            await self.send_browser_event(
                {
                    "type": "state",
                    "state": "idle",
                }
            )

        # --------------------------------------------------------
        # Ping
        # --------------------------------------------------------

        elif message_type == "ping":

            await self.send_browser_event(
                {
                    "type": "pong",
                }
            )

        # --------------------------------------------------------
        # Manual cancel
        # --------------------------------------------------------

        elif message_type == "cancel":

            await self.cancel_response()

    # ============================================================
    # Cancel
    # ============================================================

    async def cancel_response(
        self,
    ) -> None:

        if not self.qwen:
            return

        if not self.response_active:
            return

        self.response_active = False

        await self.qwen.cancel_response()

        # 让浏览器立刻清空本地播放队列
        await self.send_browser_event(
            {
                "type": "playback_cancel",
            }
        )

    # ============================================================
    # Qwen event loop
    # ============================================================

    async def forward_qwen_events(
        self,
    ) -> None:

        if not self.qwen:
            return

        try:

            async for event in (
                self.qwen.receive_events()
            ):

                if not self.running:
                    break

                await self.handle_qwen_event(
                    event
                )

        except asyncio.CancelledError:

            return

        except Exception as exc:

            if self.running:

                await self.send_browser_event(
                    {
                        "type": "error",
                        "message": (
                            f"Qwen 连接异常: {exc}"
                        ),
                    }
                )

    # ============================================================
    # Qwen events
    # ============================================================

    async def handle_qwen_event(
        self,
        event: Dict[str, Any],
    ) -> None:

        event_type = event.get("type")

        # ========================================================
        # Session
        # ========================================================

        if event_type == "session.created":

            await self.send_browser_event(
                {
                    "type": "qwen_event",
                    "event": "session_created",
                }
            )

        elif event_type == "session.updated":

            await self.send_browser_event(
                {
                    "type": "qwen_event",
                    "event": "session_updated",
                }
            )

        # ========================================================
        # User speech started
        # ========================================================

        elif (
            event_type
            == "input_audio_buffer.speech_started"
        ):

            # ----------------------------------------------------
            # 关键：
            #
            # 用户开始说话
            # ↓
            # 立即取消正在生成的回答
            # ----------------------------------------------------

            if self.response_active:

                self.response_active = False

                await self.qwen.cancel_response()

            # ----------------------------------------------------
            # 浏览器立即清空已经排队的音频
            # ----------------------------------------------------

            await self.send_browser_event(
                {
                    "type": "speech_started",
                    "interrupt": True,
                }
            )

        # ========================================================
        # User speech stopped
        # ========================================================

        elif (
            event_type
            == "input_audio_buffer.speech_stopped"
        ):

            await self.send_browser_event(
                {
                    "type": "speech_stopped",
                }
            )

        # ========================================================
        # User transcription delta
        # ========================================================

        elif (
            event_type
            == (
                "conversation.item."
                "input_audio_transcription.delta"
            )
        ):

            text = event.get(
                "delta",
                "",
            )

            if text:

                await self.send_browser_event(
                    {
                        "type": (
                            "user_transcript_delta"
                        ),
                        "text": text,
                    }
                )

        # ========================================================
        # User transcription complete
        # ========================================================

        elif (
            event_type
            == (
                "conversation.item."
                "input_audio_transcription.completed"
            )
        ):

            text = event.get(
                "transcript",
                "",
            )

            await self.send_browser_event(
                {
                    "type": "user_transcript",
                    "text": text,
                }
            )

        # ========================================================
        # Response created
        # ========================================================

        elif event_type == "response.created":

            self.response_active = True

            await self.send_browser_event(
                {
                    "type": "state",
                    "state": "thinking",
                }
            )

        # ========================================================
        # Assistant audio
        # ========================================================

        elif event_type == "response.audio.delta":

            audio = event.get(
                "delta",
                "",
            )

            if audio:

                self.response_active = True

                await self.send_browser_event(
                    {
                        "type": "assistant_audio",
                        "audio": audio,
                    }
                )

        # ========================================================
        # Assistant transcript
        # ========================================================

        elif (
            event_type
            == "response.audio_transcript.delta"
        ):

            text = event.get(
                "delta",
                "",
            )

            if text:

                await self.send_browser_event(
                    {
                        "type": (
                            "assistant_transcript_delta"
                        ),
                        "text": text,
                    }
                )

        elif (
            event_type
            == "response.audio_transcript.done"
        ):

            text = event.get(
                "transcript",
                "",
            )

            await self.send_browser_event(
                {
                    "type": "assistant_transcript",
                    "text": text,
                }
            )

        # ========================================================
        # Response done
        # ========================================================

        elif event_type == "response.done":

            response = event.get(
                "response",
                {},
            )

            status = response.get(
                "status",
                "completed",
            )

            self.response_active = False

            await self.send_browser_event(
                {
                    "type": "response_done",
                    "status": status,
                }
            )

            # 如果 cancelled，浏览器一定清播放
            if status == "cancelled":

                await self.send_browser_event(
                    {
                        "type": "playback_cancel",
                    }
                )

            await self.send_browser_event(
                {
                    "type": "state",
                    "state": "idle",
                }
            )

        # ========================================================
        # Error
        # ========================================================

        elif event_type == "error":

            error = event.get(
                "error",
                {},
            )

            message = error.get(
                "message",
                "Qwen 返回未知错误",
            )

            await self.send_browser_event(
                {
                    "type": "error",
                    "message": message,
                }
            )

        # ========================================================
        # Debug
        # ========================================================

        else:

            if settings.debug:

                await self.send_browser_event(
                    {
                        "type": "debug_event",
                        "event": event_type,
                    }
                )

    # ============================================================
    # Browser output
    # ============================================================

    async def send_browser_event(
        self,
        event: Dict[str, Any],
    ) -> None:

        if not self.browser_connected:
            return

        try:

            await self.browser_ws.send_text(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
            )

        except Exception:

            self.browser_connected = False

    # ============================================================
    # Close
    # ============================================================

    async def close(self) -> None:

        if not self.running:
            return

        self.running = False
        self.browser_connected = False

        # --------------------------------------------------------
        # Stop Qwen event task
        # --------------------------------------------------------

        task = self.qwen_receive_task

        self.qwen_receive_task = None

        if task and not task.done():

            task.cancel()

            try:
                await task

            except asyncio.CancelledError:
                pass

            except Exception:
                pass

        # --------------------------------------------------------
        # Close Qwen
        # --------------------------------------------------------

        if self.qwen:

            await self.qwen.close()

            self.qwen = None