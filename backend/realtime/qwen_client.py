import base64
import json
from typing import Any, AsyncIterator, Dict, Optional

import websockets


class QwenRealtimeClient:
    """
    Qwen Realtime WebSocket client.

    Browser
        ↓
    Python WebSocket
        ↓
    Qwen Realtime
    """

    def __init__(
        self,
        api_key: str,
        websocket_url: str,
        workspace_id: str,
        voice: str,
        system_prompt: str,
        vad_type: str,
        vad_threshold: float,
        vad_silence_duration_ms: int,
        max_history_turns: int,
        debug: bool = False,
    ):
        self.api_key = api_key
        self.websocket_url = websocket_url
        self.workspace_id = workspace_id

        self.voice = voice
        self.system_prompt = system_prompt

        self.vad_type = vad_type
        self.vad_threshold = vad_threshold
        self.vad_silence_duration_ms = (
            vad_silence_duration_ms
        )

        self.max_history_turns = max_history_turns

        self.debug = debug

        self.websocket = None
        self.connected = False

        self._closing = False

    # ============================================================
    # Connect
    # ============================================================

    async def connect(self) -> None:
        """
        Establish connection to Qwen Realtime.
        """

        if not self.api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY 未配置。"
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-DashScope-WorkSpace": self.workspace_id,
        }

        self._closing = False

        self.websocket = await websockets.connect(
            self.websocket_url,
            additional_headers=headers,

            # ----------------------------------------------------
            # Keepalive
            # ----------------------------------------------------
            #
            # 不要设置得太激进。
            #
            ping_interval=30,
            ping_timeout=30,
            #
            # 给实时语音连接更多容错时间。
            #
            max_size=None,
        )

        self.connected = True

        if self.debug:
            print(
                "[Qwen] WebSocket connected:",
                self.websocket_url,
            )

        await self.update_session()

    # ============================================================
    # Session
    # ============================================================

    async def update_session(self) -> None:
        """
        Configure Qwen Realtime session.

        This must happen before the first audio packet.
        """

        event = {
            "type": "session.update",
            "session": {
                "modalities": [
                    "audio",
                    "text",
                ],
                "voice": self.voice,
                "instructions": self.system_prompt,
                "max_history_turns": (
                    self.max_history_turns
                ),
                "turn_detection": {
                    "type": self.vad_type,
                    "threshold": self.vad_threshold,
                    "silence_duration_ms": (
                        self.vad_silence_duration_ms
                    ),
                },
            },
        }

        await self.send_event(event)

    # ============================================================
    # Audio
    # ============================================================

    async def send_audio(
        self,
        pcm_data: bytes,
    ) -> None:
        """
        Send raw PCM audio to Qwen.

        Input:
            16-bit
            16 kHz
            mono
        """

        if not pcm_data:
            return

        if not self.connected:
            return

        if not self.websocket:
            return

        encoded_audio = base64.b64encode(
            pcm_data
        ).decode("ascii")

        event = {
            "type": "input_audio_buffer.append",
            "audio": encoded_audio,
        }

        await self.send_event(event)

    # ============================================================
    # Generic event
    # ============================================================

    async def send_event(
        self,
        event: Dict[str, Any],
    ) -> None:

        if not self.connected:
            return

        if not self.websocket:
            return

        message = json.dumps(
            event,
            ensure_ascii=False,
        )

        try:
            await self.websocket.send(
                message
            )

        except Exception as exc:

            if self.debug and not self._closing:
                print(
                    "[Qwen] Send error:",
                    exc,
                )

    # ============================================================
    # Receive
    # ============================================================

    async def receive_events(
        self,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Receive events from Qwen continuously.
        """

        if not self.websocket:
            return

        try:

            async for message in self.websocket:

                if isinstance(message, bytes):
                    continue

                try:
                    event = json.loads(message)

                except json.JSONDecodeError:

                    if self.debug:
                        print(
                            "[Qwen] Invalid JSON:",
                            message,
                        )

                    continue

                if self.debug:

                    event_type = event.get(
                        "type"
                    )

                    print(
                        f"[Qwen] event: {event_type}"
                    )

                yield event

        except Exception as exc:

            if self._closing:
                return

            if self.debug:
                print(
                    "[Qwen] Receive error:",
                    exc,
                )

            raise

    # ============================================================
    # Cancel response
    # ============================================================

    async def cancel_response(
        self,
    ) -> None:
        """
        Immediately cancel current Qwen response.

        This is used for barge-in.
        """

        if not self.connected:
            return

        if not self.websocket:
            return

        try:

            await self.send_event(
                {
                    "type": "response.cancel",
                }
            )

            if self.debug:
                print(
                    "[Qwen] response.cancel sent"
                )

        except Exception as exc:

            if self.debug:
                print(
                    "[Qwen] Cancel error:",
                    exc,
                )

    # ============================================================
    # Close
    # ============================================================

    async def close(self) -> None:

        if self._closing:
            return

        self._closing = True
        self.connected = False

        websocket = self.websocket
        self.websocket = None

        if websocket:

            try:
                await websocket.close()

            except Exception:
                pass