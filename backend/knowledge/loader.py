from pathlib import Path
from typing import Dict

import yaml

from backend.knowledge.models import ActivityKnowledge


class KnowledgeBaseLoader:
    """Load local YAML activity knowledge files."""

    def __init__(
        self,
        knowledge_dir: str | Path,
        project_root: str | Path | None = None,
    ):
        # --------------------------------------------------------
        # Project root
        #
        # loader.py:
        #   pipi-realtime/backend/knowledge/loader.py
        #
        # parents[0] -> knowledge
        # parents[1] -> backend
        # parents[2] -> pipi-realtime
        # --------------------------------------------------------
        if project_root is not None:
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = (
                Path(__file__)
                .resolve()
                .parents[2]
            )

        knowledge_path = Path(knowledge_dir)

        # --------------------------------------------------------
        # Relative path:
        #
        #   knowledge
        #
        # becomes:
        #
        #   /Users/xiaojian/PycharmProjects/pipi-realtime/knowledge
        # --------------------------------------------------------
        if not knowledge_path.is_absolute():
            knowledge_path = (
                self.project_root
                / knowledge_path
            )

        self.knowledge_dir = (
            knowledge_path.resolve()
        )

        print(
            "[Knowledge] knowledge directory = "
            f"{self.knowledge_dir}"
        )

    # ============================================================
    # Load one activity
    # ============================================================

    def load_activity(
        self,
        activity_id: str,
    ) -> ActivityKnowledge:

        path = (
            self.knowledge_dir
            / "activities"
            / f"{activity_id}.yaml"
        )

        if not path.exists():
            raise FileNotFoundError(
                f"找不到活动知识库: {path}"
            )

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, dict):
            raise ValueError(
                f"知识库 YAML 格式错误: {path}"
            )

        return ActivityKnowledge.from_dict(
            data
        )

    # ============================================================
    # List activities
    # ============================================================

    def list_activities(self) -> list[str]:

        activity_dir = (
            self.knowledge_dir
            / "activities"
        )

        if not activity_dir.exists():
            return []

        return sorted(
            path.stem
            for path in activity_dir.glob(
                "*.yaml"
            )
        )

    # ============================================================
    # Load all activities
    # ============================================================

    def load_all(
        self,
    ) -> Dict[str, ActivityKnowledge]:

        return {
            activity_id: self.load_activity(
                activity_id
            )
            for activity_id in self.list_activities()
        }