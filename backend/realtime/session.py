import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import WebSocket

from backend.agent.teaching_agent import TeachingAgent
from backend.config.settings import settings
from backend.knowledge.loader import KnowledgeBaseLoader
from backend.realtime.qwen_client import QwenRealtimeClient


class RealtimeSession:
    """
    One browser connection corresponds to one Qwen Realtime session.

    Current flow:

        Browser audio
            ↓
        Qwen Realtime
            ↓
        Function Calling
            ↓
        TeachingAgent
            ↓
        Local YAML knowledge base
            ↓
        Qwen Realtime follow-up response

    Step completion flow:

        PiPi Vision
            ↓
        vision_completion_candidate
            ↓
        Qwen主动询问儿童
            ↓
        儿童确认
            ↓
        complete_current_step
            ↓
        下一步骤
    """

    # ============================================================
    # Tool names
    # ============================================================

    TEACHING_TOOL_NAME = "search_teaching_knowledge"

    PROGRESS_TOOL_NAME = "get_activity_progress"

    COMPLETE_STEP_TOOL_NAME = "complete_current_step"

    def __init__(
        self,
        browser_ws: WebSocket,
    ):
        self.browser_ws = browser_ws

        self.qwen: Optional[QwenRealtimeClient] = None

        self.running = False

        self.qwen_receive_task: Optional[
            asyncio.Task
        ] = None

        self.browser_connected = True

        # 当前 Qwen 是否正在输出回答
        self.response_active = False

        # --------------------------------------------------------
        # Teaching Agent
        # --------------------------------------------------------

        knowledge_dir = Path(
            settings.knowledge_dir
        )

        loader = KnowledgeBaseLoader(
            knowledge_dir
        )

        self.teaching_agent = TeachingAgent(
            loader=loader,
            activity_id=settings.default_activity_id,
            current_step=settings.default_activity_step,
            top_k=settings.knowledge_top_k,
        )

    # ============================================================
    # Tool definitions
    # ============================================================

    @classmethod
    def teaching_tools(
        cls,
    ) -> list[Dict[str, Any]]:

        return [

            # ====================================================
            # 1. Search knowledge
            # ====================================================

            {
                "type": "function",
                "function": {
                    "name": cls.TEACHING_TOOL_NAME,

                    "description": (
                        "查询当前儿童手工活动的本地知识库。"
                        "这个工具只用于查询活动内容、具体步骤怎么做、"
                        "为什么、失败怎么办、材料、注意事项等知识。"
                        "不要使用这个工具判断活动一共有几步、"
                        "当前是第几步、当前步骤是否完成、"
                        "下一步是什么。"
                        "这些状态必须使用 "
                        "get_activity_progress 查询。"
                    ),

                    "parameters": {
                        "type": "object",

                        "properties": {
                            "question": {
                                "type": "string",
                                "description": (
                                    "孩子刚刚提出的手工活动问题。"
                                ),
                            },
                        },

                        "required": [
                            "question"
                        ],
                    },
                },
            },

            # ====================================================
            # 2. Get activity progress
            # ====================================================

            {
                "type": "function",
                "function": {
                    "name": cls.PROGRESS_TOOL_NAME,

                    "description": (
                        "查询当前儿童手工活动的实时进度状态。"
                        "当孩子询问总共有几个步骤、"
                        "现在进行到第几步、"
                        "当前步骤是什么、"
                        "下一步是什么、"
                        "当前步骤是否完成、"
                        "活动是否完成时，必须使用这个工具。"
                        "不要自己猜测步骤数量或当前步骤。"
                    ),

                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },

            # ====================================================
            # 3. Complete current step
            # ====================================================

            {
                "type": "function",
                "function": {
                    "name": cls.COMPLETE_STEP_TOOL_NAME,

                    "description": (
                        "在儿童已经通过语音明确确认当前步骤完成后，"
                        "完成当前步骤并进入下一步骤。"
                        "不要因为视觉系统单独判断可能完成，"
                        "就直接调用这个工具。"
                        "如果视觉系统只是提示当前步骤可能完成，"
                        "应该先主动询问儿童确认，"
                        "得到明确确认后再调用这个工具。"
                        "如果儿童没有明确确认，不要调用。"
                    ),

                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    # ============================================================
    # Start
    # ============================================================

    async def start(
        self,
    ) -> None:

        system_prompt = (
            self._build_system_prompt()
        )

        self.qwen = QwenRealtimeClient(
            api_key=settings.api_key,
            websocket_url=settings.qwen_ws_url,
            workspace_id=settings.workspace_id,
            voice=settings.voice,
            system_prompt=system_prompt,
            vad_type=settings.vad_type,
            vad_threshold=settings.vad_threshold,
            vad_silence_duration_ms=(
                settings.vad_silence_duration_ms
            ),
            max_history_turns=(
                settings.max_history_turns
            ),
            debug=settings.debug,
            tools=self.teaching_tools(),
        )

        await self.qwen.connect()

        self.running = True

        await self.send_browser_event(
            {
                "type": "session_ready",
                "message": (
                    "Qwen Realtime 已连接"
                ),
                "activity": (
                    self.teaching_agent
                    .get_activity_progress()
                ),
            }
        )

        self.qwen_receive_task = (
            asyncio.create_task(
                self.forward_qwen_events()
            )
        )

    # ============================================================
    # System prompt
    # ============================================================

    def _build_system_prompt(
        self,
    ) -> str:

        activity = (
            self.teaching_agent.activity
        )

        return (
            f"{settings.system_prompt}\n\n"

            "你现在正在作为儿童手工活动教学助手。\n"

            f"当前活动："
            f"{activity.name}"
            f"（{activity.id}）\n\n"

            "教学规则：\n"

            "1. 如果孩子询问活动知识、"
            "具体怎么做、为什么、失败怎么办、"
            "材料或注意事项，使用 "
            "search_teaching_knowledge。\n"

            "2. 如果孩子询问活动一共有几个步骤、"
            "当前第几步、当前步骤是什么、"
            "下一步是什么、当前步骤是否完成、"
            "活动是否完成，必须使用 "
            "get_activity_progress。"
            "不要自己猜测。\n"

            "3. 如果孩子询问当前步骤怎么做，"
            "可以先使用 get_activity_progress "
            "确认当前步骤，再使用 "
            "search_teaching_knowledge 查询具体内容。\n"

            "4. 一次主要指导一个动作，"
            "不要一次把后面的所有步骤都说完。\n"

            "5. 如果孩子只是闲聊，可以正常聊天，"
            "不必调用知识库。\n"

            "6. 如果知识库没有相关内容，"
            "要诚实说明，不要假装知道。\n"

            "7. 步骤完成不能只依赖视觉判断。"
            "视觉系统只能提供“可能完成”的提示。\n"

            "8. 当视觉系统提示当前步骤可能完成时，"
            "你应该主动和孩子进行一句简短的确认对话，"
            "例如："
            "“你已经完成了吗？我们要不要进行下一步呀？”\n"

            "9. 只有孩子明确确认当前步骤完成之后，"
            "才调用 complete_current_step。\n"

            "10. 如果孩子说还没有完成、"
            "想继续、或者看起来不确定，"
            "不要调用 complete_current_step，"
            "继续帮助孩子完成当前步骤。\n"

            "11. 你不仅要被动回答孩子的问题，"
            "在教学过程中也可以主动发起简短、"
            "自然、适合儿童的互动，"
            "但不要连续频繁打断孩子。"
        )

    # ============================================================
    # Browser messages
    # ============================================================

    async def handle_browser_message(
        self,
        message: Any,
    ) -> None:

        if (
            not self.running
            or not self.qwen
        ):
            return

        # --------------------------------------------------------
        # Audio
        # --------------------------------------------------------

        if isinstance(message, bytes):

            if message:
                await self.qwen.send_audio(
                    message
                )

            return

        # --------------------------------------------------------
        # JSON
        # --------------------------------------------------------

        if not isinstance(
            message,
            str,
        ):
            return

        try:
            data = json.loads(
                message
            )

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

        message_type = data.get(
            "type"
        )

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
        # Cancel
        # --------------------------------------------------------

        elif message_type == "cancel":

            await self.cancel_response()

        # --------------------------------------------------------
        # Set activity
        # --------------------------------------------------------

        elif message_type == "set_activity":

            activity_id = data.get(
                "activity_id"
            )

            if not activity_id:
                return

            try:

                activity = (
                    self.teaching_agent
                    .set_activity(
                        activity_id
                    )
                )

            except Exception as exc:

                await self.send_browser_event(
                    {
                        "type": "error",
                        "message": (
                            f"切换活动失败: {exc}"
                        ),
                    }
                )

                return

            await self.send_browser_event(
                {
                    "type": "activity_updated",
                    "activity": (
                        self.teaching_agent
                        .get_activity_progress()
                    ),
                }
            )

        # --------------------------------------------------------
        # Set step
        # --------------------------------------------------------

        elif message_type == "set_step":

            step_id = data.get(
                "step"
            )

            try:

                step_id = (
                    int(step_id)
                    if step_id is not None
                    else None
                )

                self.teaching_agent.set_step(
                    step_id
                )

            except (
                TypeError,
                ValueError,
            ) as exc:

                await self.send_browser_event(
                    {
                        "type": "error",
                        "message": (
                            f"设置步骤失败: {exc}"
                        ),
                    }
                )

                return

            await self.send_browser_event(
                {
                    "type": "step_updated",
                    "activity": (
                        self.teaching_agent
                        .get_activity_progress()
                    ),
                }
            )

        # --------------------------------------------------------
        # Vision candidate
        # --------------------------------------------------------

        elif (
            message_type
            == "vision_completion_candidate"
        ):

            await self.handle_vision_completion_candidate(
                data
            )

    # ============================================================
    # Vision → Voice Agent
    # ============================================================

    async def handle_vision_completion_candidate(
        self,
        data: Dict[str, Any],
    ) -> None:
        """
        接收视觉系统的“可能完成”信号。

        注意：

        这里绝对不会直接完成步骤。

        流程：

            Vision
                ↓
            candidate
                ↓
            Qwen
                ↓
            主动询问儿童
                ↓
            儿童确认
                ↓
            complete_current_step
        """

        if (
            not self.qwen
            or not self.running
        ):
            return

        progress = (
            self.teaching_agent
            .get_activity_progress()
        )

        current_step = (
            progress.get(
                "current_step"
            )
        )

        if current_step is None:
            return

        candidate_step = data.get(
            "step"
        )

        # 如果视觉明确给出了步骤，
        # 且不是当前步骤，则暂时忽略。
        if candidate_step is not None:

            try:
                candidate_step = int(
                    candidate_step
                )
            except (
                TypeError,
                ValueError,
            ):
                candidate_step = None

        if (
            candidate_step is not None
            and candidate_step != current_step
        ):
            return

        evidence = data.get(
            "evidence",
            "",
        )

        confidence = data.get(
            "confidence"
        )

        # --------------------------------------------------------
        # 给 Qwen 一个“外部事件”
        # --------------------------------------------------------

        if evidence:

            vision_text = (
                "视觉系统刚刚提供了一个候选完成信号。"
                f"当前是第 {current_step} 步。"
                f"视觉依据：{evidence}"
            )

        else:

            vision_text = (
                "视觉系统刚刚判断当前步骤"
                f"（第 {current_step} 步）"
                "可能已经完成。"
            )

        if confidence is not None:

            vision_text += (
                f"视觉置信度约为 {confidence}。"
            )

        vision_text += (
            "\n\n"
            "请不要直接把这个步骤标记为完成。"
            "请主动用一句简短、自然、适合儿童的中文"
            "询问孩子是否已经完成当前步骤。"
            "等待孩子明确确认后，再决定是否调用 "
            "complete_current_step。"
        )

        # --------------------------------------------------------
        # 注入 Qwen conversation
        # --------------------------------------------------------

        await self.qwen.send_event(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": vision_text,
                        }
                    ],
                },
            }
        )

        # --------------------------------------------------------
        # 主动触发 Agent 回应
        # --------------------------------------------------------

        await self.qwen.create_response()

        await self.send_browser_event(
            {
                "type": "vision_completion_candidate",
                "step": current_step,
                "confidence": confidence,
                "evidence": evidence,
                "message": (
                    "视觉认为当前步骤可能完成，"
                    "已通知语音 Agent 主动询问儿童。"
                ),
            }
        )

    # ============================================================
    # Cancel
    # ============================================================

    async def cancel_response(
        self,
    ) -> None:

        if (
            not self.qwen
            or not self.response_active
        ):
            return

        self.response_active = False

        await self.qwen.cancel_response()

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

        event_type = event.get(
            "type"
        )

        # --------------------------------------------------------
        # Session created
        # --------------------------------------------------------

        if event_type == "session.created":

            await self.send_browser_event(
                {
                    "type": "qwen_event",
                    "event": "session_created",
                }
            )

        # --------------------------------------------------------
        # Session updated
        # --------------------------------------------------------

        elif event_type == "session.updated":

            await self.send_browser_event(
                {
                    "type": "qwen_event",
                    "event": "session_updated",
                }
            )

        # --------------------------------------------------------
        # User speech started
        # --------------------------------------------------------

        elif (
            event_type
            == "input_audio_buffer.speech_started"
        ):

            if self.response_active:

                self.response_active = False

                await self.qwen.cancel_response()

            await self.send_browser_event(
                {
                    "type": "speech_started",
                    "interrupt": True,
                }
            )

        # --------------------------------------------------------
        # User speech stopped
        # --------------------------------------------------------

        elif (
            event_type
            == "input_audio_buffer.speech_stopped"
        ):

            await self.send_browser_event(
                {
                    "type": "speech_stopped",
                }
            )

        # --------------------------------------------------------
        # User transcript delta
        # --------------------------------------------------------

        elif (
            event_type
            == "conversation.item.input_audio_transcription.delta"
        ):

            text = event.get(
                "delta",
                "",
            )

            if text:

                await self.send_browser_event(
                    {
                        "type": "user_transcript_delta",
                        "text": text,
                    }
                )

        # --------------------------------------------------------
        # User transcript completed
        # --------------------------------------------------------

        elif (
            event_type
            == "conversation.item.input_audio_transcription.completed"
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

        # --------------------------------------------------------
        # Response created
        # --------------------------------------------------------

        elif event_type == "response.created":

            self.response_active = True

            await self.send_browser_event(
                {
                    "type": "state",
                    "state": "thinking",
                }
            )

        # --------------------------------------------------------
        # Function calling
        # --------------------------------------------------------

        elif (
            event_type
            == "response.function_call_arguments.done"
        ):

            await self._handle_function_call(
                event
            )

        # --------------------------------------------------------
        # Assistant audio
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # Assistant transcript delta
        # --------------------------------------------------------

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
                        "type": "assistant_transcript_delta",
                        "text": text,
                    }
                )

        # --------------------------------------------------------
        # Assistant transcript done
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # Response done
        # --------------------------------------------------------

        elif event_type == "response.done":

            response = event.get(
                "response",
                {}
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

        # --------------------------------------------------------
        # Error
        # --------------------------------------------------------

        elif event_type == "error":

            error = event.get(
                "error",
                {}
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

        # --------------------------------------------------------
        # Debug
        # --------------------------------------------------------

        else:

            if settings.debug:

                await self.send_browser_event(
                    {
                        "type": "debug_event",
                        "event": event_type,
                    }
                )

    # ============================================================
    # Function call handler
    # ============================================================

    async def _handle_function_call(
        self,
        event: Dict[str, Any],
    ) -> None:

        if not self.qwen:
            return

        name = event.get(
            "name",
            ""
        )

        call_id = event.get(
            "call_id",
            ""
        )

        arguments_text = event.get(
            "arguments",
            "{}"
        )

        # --------------------------------------------------------
        # Parse arguments
        # --------------------------------------------------------

        try:

            arguments = json.loads(
                arguments_text or "{}"
            )

        except json.JSONDecodeError:

            arguments = {}

        output: Dict[str, Any]

        # ========================================================
        # Tool 1: knowledge
        # ========================================================

        if name == self.TEACHING_TOOL_NAME:

            question = str(
                arguments.get(
                    "question",
                    "",
                )
            ).strip()

            if not question:

                output = {
                    "ok": False,
                    "error": (
                        "缺少 question 参数"
                    ),
                }

            else:

                try:

                    context = (
                        self.teaching_agent
                        .answer_context(
                            question
                        )
                    )

                    output = {
                        "ok": True,
                        "activity_id": (
                            context.activity_id
                        ),
                        "activity_name": (
                            context.activity_name
                        ),
                        "current_step": (
                            context.current_step
                        ),
                        "current_step_title": (
                            context.current_step_title
                        ),
                        "total_steps": (
                            context.total_steps
                        ),
                        "knowledge": (
                            context.results
                        ),
                        "teaching_context": (
                            context.teaching_context
                        ),
                    }

                except Exception as exc:

                    output = {
                        "ok": False,
                        "error": str(exc),
                    }

            if settings.debug:

                print(
                    "[TeachingAgent] "
                    "tool call:",
                    name,
                    "question=",
                    question,
                )

        # ========================================================
        # Tool 2: progress
        # ========================================================

        elif name == self.PROGRESS_TOOL_NAME:

            output = {
                "ok": True,
                "progress": (
                    self.teaching_agent
                    .get_activity_progress()
                ),
            }

            if settings.debug:

                print(
                    "[TeachingAgent] "
                    "progress:",
                    output["progress"],
                )

        # ========================================================
        # Tool 3: complete current step
        # ========================================================

        elif (
            name
            == self.COMPLETE_STEP_TOOL_NAME
        ):

            result = (
                self.teaching_agent
                .complete_current_step()
            )

            output = result

            if settings.debug:

                print(
                    "[TeachingAgent] "
                    "complete_current_step:",
                    result,
                )

        # ========================================================
        # Unknown tool
        # ========================================================

        else:

            output = {
                "ok": False,
                "error": (
                    f"未知工具调用: {name}"
                ),
            }

        # --------------------------------------------------------
        # Browser event
        # --------------------------------------------------------

        await self.send_browser_event(
            {
                "type": "teaching_tool",
                "tool": name,
                "activity": (
                    self.teaching_agent
                    .get_activity_progress()
                ),
            }
        )

        # --------------------------------------------------------
        # Send function result
        # --------------------------------------------------------

        await self.qwen.send_function_call_output(
            call_id=call_id,
            output=json.dumps(
                output,
                ensure_ascii=False,
            ),
        )

        # --------------------------------------------------------
        # Trigger follow-up response
        # --------------------------------------------------------

        await self.qwen.create_response()

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

    async def close(
        self,
    ) -> None:

        if not self.running:
            return

        self.running = False
        self.browser_connected = False

        task = self.qwen_receive_task

        self.qwen_receive_task = None

        if (
            task
            and not task.done()
        ):

            task.cancel()

            try:
                await task

            except asyncio.CancelledError:
                pass

            except Exception:
                pass

        if self.qwen:

            await self.qwen.close()

            self.qwen = None