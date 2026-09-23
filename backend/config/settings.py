import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# Project root
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = PROJECT_ROOT / ".env"


# ============================================================
# Load .env
# ============================================================

if ENV_FILE.exists():
    load_dotenv(
        ENV_FILE,
        override=True,
    )
else:
    print(
        f"[Settings] WARNING: .env 文件不存在: {ENV_FILE}"
    )


# ============================================================
# Debug information
# ============================================================

workspace_id_from_env = os.getenv(
    "QWEN_WORKSPACE_ID",
    "",
).strip()

api_key_from_env = os.getenv(
    "DASHSCOPE_API_KEY",
    "",
).strip()


print("=" * 60)
print("[Settings] Project root:")
print(f"  {PROJECT_ROOT}")

print("[Settings] .env:")
print(f"  {ENV_FILE}")
print(
    f"  exists = {ENV_FILE.exists()}"
)

print("[Settings] Qwen configuration:")
print(
    "  DASHSCOPE_API_KEY = "
    + (
        "已读取"
        if api_key_from_env
        else "未读取"
    )
)

print(
    "  QWEN_WORKSPACE_ID = "
    + (
        "已读取"
        if workspace_id_from_env
        else "未读取"
    )
)

print(
    "  QWEN_REGION = "
    + os.getenv(
        "QWEN_REGION",
        "cn-beijing",
    )
)

print(
    "  QWEN_MODEL = "
    + os.getenv(
        "QWEN_MODEL",
        "qwen-audio-3.1-realtime-plus",
    )
)

print("=" * 60)


# ============================================================
# Settings
# ============================================================

@dataclass(frozen=True)
class Settings:

    # ========================================================
    # Server
    # ========================================================

    host: str = os.getenv(
        "SERVER_HOST",
        "127.0.0.1",
    )

    port: int = int(
        os.getenv(
            "SERVER_PORT",
            "8000",
        )
    )

    # ========================================================
    # Qwen
    # ========================================================

    api_key: str = api_key_from_env

    workspace_id: str = workspace_id_from_env

    region: str = os.getenv(
        "QWEN_REGION",
        "cn-beijing",
    ).strip()

    model: str = os.getenv(
        "QWEN_MODEL",
        "qwen-audio-3.1-realtime-plus",
    ).strip()

    voice: str = os.getenv(
        "QWEN_VOICE",
        "longanqian_v3.1",
    ).strip()

    # ========================================================
    # Audio
    # ========================================================

    input_sample_rate: int = int(
        os.getenv(
            "QWEN_INPUT_SAMPLE_RATE",
            "16000",
        )
    )

    output_sample_rate: int = int(
        os.getenv(
            "QWEN_OUTPUT_SAMPLE_RATE",
            "24000",
        )
    )

    audio_chunk_ms: int = int(
        os.getenv(
            "AUDIO_CHUNK_MS",
            "40",
        )
    )

    # ========================================================
    # VAD
    # ========================================================

    vad_type: str = os.getenv(
        "QWEN_VAD_TYPE",
        "server_vad",
    ).strip()

    vad_threshold: float = float(
        os.getenv(
            "QWEN_VAD_THRESHOLD",
            "0.5",
        )
    )

    vad_silence_duration_ms: int = int(
        os.getenv(
            "QWEN_VAD_SILENCE_DURATION_MS",
            "600",
        )
    )

    # ========================================================
    # Conversation
    # ========================================================

    max_history_turns: int = int(
        os.getenv(
            "QWEN_MAX_HISTORY_TURNS",
            "10",
        )
    )

    system_prompt: str = os.getenv(
        "QWEN_SYSTEM_PROMPT",
        (
            "你是皮皮猴，一个陪伴幼儿进行互动的语音伙伴。"
            "你活泼、温柔、有耐心。"
            "说话要自然、简短、容易让幼儿理解。"
            "一次不要说太多内容。"
            "多鼓励孩子，但不要过度夸张。"
            "如果没有听清楚孩子的话，用简单的问题请孩子再说一次。"
            "不要使用复杂的专业词汇。"
            "回答当前问题后，可以自然地继续和孩子互动。"
        ),
    )

    # ========================================================
    # CORS
    # ========================================================

    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "*",
    )

    # ========================================================
    # Debug
    # ========================================================

    debug: bool = os.getenv(
        "DEBUG",
        "true",
    ).lower() == "true"

    # ========================================================
    # Qwen WebSocket URL
    # ========================================================

    @property
    def qwen_ws_url(self) -> str:

        if not self.workspace_id:

            raise RuntimeError(
                "QWEN_WORKSPACE_ID 未配置，请检查项目根目录 .env"
            )

        if self.region == "cn-beijing":

            host = (
                f"{self.workspace_id}"
                ".cn-beijing.maas.aliyuncs.com"
            )

        elif self.region == "ap-southeast-1":

            host = (
                f"{self.workspace_id}"
                ".ap-southeast-1.maas.aliyuncs.com"
            )

        else:

            raise RuntimeError(
                f"不支持的 QWEN_REGION: {self.region}"
            )

        return (
            f"wss://{host}"
            f"/api-ws/v1/realtime"
            f"?model={self.model}"
        )


# ============================================================
# Global settings
# ============================================================

settings = Settings()