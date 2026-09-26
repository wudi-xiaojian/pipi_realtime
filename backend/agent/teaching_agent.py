import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from backend.knowledge.loader import KnowledgeBaseLoader
from backend.knowledge.models import ActivityKnowledge
from backend.knowledge.retriever import KnowledgeResult, KnowledgeRetriever


@dataclass(frozen=True)
class TeachingContext:
    """Structured context prepared for the language model."""

    activity_id: str
    activity_name: str
    current_step: Optional[int]
    current_step_title: str
    total_steps: int
    user_question: str
    results: List[Dict[str, Any]]
    teaching_context: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TeachingAgent:
    """
    儿童活动教学状态与知识层。

    当前职责：

    1. 管理当前活动。
    2. 管理当前步骤。
    3. 管理步骤完成状态。
    4. 提供活动进度查询。
    5. 在语音 Agent 确认后推进步骤。
    6. 检索本地 YAML 活动知识。
    7. 将检索结果整理成适合 Qwen 使用的教学上下文。

    注意：

    TeachingAgent 本身不负责视觉判断。

    视觉系统后续只负责提供：
        “当前步骤可能已经完成”

    最终是否完成，应由语音 Agent 与儿童交互确认后，
    再调用 complete_current_step()。
    """

    def __init__(
        self,
        loader: KnowledgeBaseLoader,
        activity_id: str,
        current_step: Optional[int] = 1,
        top_k: int = 5,
    ) -> None:
        self.loader = loader
        self.activity_id = activity_id
        self.current_step = current_step
        self.top_k = top_k

        self.activity = self.loader.load_activity(activity_id)
        self.retriever = KnowledgeRetriever([self.activity])

        # 已完成步骤
        self.completed_steps: set[int] = set()

    # ============================================================
    # Activity
    # ============================================================

    def set_activity(
        self,
        activity_id: str,
    ) -> ActivityKnowledge:
        """
        切换当前活动。

        切换活动时：
        - 当前步骤重新从第1步开始
        - 已完成步骤清空
        """

        self.activity_id = activity_id
        self.activity = self.loader.load_activity(activity_id)
        self.retriever = KnowledgeRetriever([self.activity])

        self.current_step = 1 if self.activity.steps else None
        self.completed_steps.clear()

        return self.activity

    # ============================================================
    # Step
    # ============================================================

    def set_step(
        self,
        step_id: Optional[int],
    ) -> Optional[int]:
        """
        手动设置当前步骤。

        主要用于：
        - 调试
        - 前端控制
        - 后续视觉系统同步状态

        正常教学流程不建议直接使用这个方法推进步骤。
        正常流程应该使用 complete_current_step()。
        """

        if step_id is None:
            self.current_step = None
            return None

        if self.activity.get_step(step_id) is None:
            raise ValueError(
                f"活动 {self.activity_id} 不存在步骤 {step_id}"
            )

        self.current_step = step_id
        return self.current_step

    # ============================================================
    # Progress
    # ============================================================

    @property
    def total_steps(self) -> int:
        """当前活动总步骤数。"""

        return len(self.activity.steps)

    def get_activity_progress(self) -> Dict[str, Any]:
        """
        获取当前活动的完整进度状态。

        这个方法是“步骤状态”的权威来源。

        例如：

        {
            "activity_id": "stacking_cups",
            "activity_name": "神奇的纸杯搭建",
            "current_step": 1,
            "total_steps": 4,
            "current_step_title": "认识纸杯",
            "current_step_instruction": "...",
            "current_step_completed": false,
            "completed_steps": [],
            "next_step": 2,
            "next_step_title": "把第一个纸杯放稳",
            "activity_completed": false
        }
        """

        current_step_obj = (
            self.activity.get_step(self.current_step)
            if self.current_step is not None
            else None
        )

        current_step_completed = (
            self.current_step in self.completed_steps
            if self.current_step is not None
            else False
        )

        activity_completed = (
            self.total_steps > 0
            and len(self.completed_steps) >= self.total_steps
        )

        next_step: Optional[int] = None
        next_step_title = ""

        if (
            self.current_step is not None
            and self.current_step < self.total_steps
        ):
            next_step = self.current_step + 1

            next_step_obj = self.activity.get_step(next_step)

            if next_step_obj is not None:
                next_step_title = next_step_obj.title

        return {
            "activity_id": self.activity.id,
            "activity_name": self.activity.name,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "current_step_title": (
                current_step_obj.title
                if current_step_obj is not None
                else ""
            ),
            "current_step_instruction": (
                current_step_obj.instruction
                if current_step_obj is not None
                else ""
            ),
            "current_step_completed": current_step_completed,
            "completed_steps": sorted(self.completed_steps),
            "next_step": next_step,
            "next_step_title": next_step_title,
            "activity_completed": activity_completed,
        }

    # ============================================================
    # Complete current step
    # ============================================================

    def complete_current_step(self) -> Dict[str, Any]:
        """
        完成当前步骤并进入下一步。

        重要：

        这个方法不负责判断“孩子是不是完成了”。

        调用这个方法意味着：
            语音 Agent 已经通过交互确认当前步骤完成。

        后续视觉系统不应该直接调用这个方法，
        而应该先把“可能完成”的信号交给语音 Agent。
        """

        if self.current_step is None:
            return {
                "ok": False,
                "error": "当前没有正在进行的步骤。",
                "progress": self.get_activity_progress(),
            }

        if self.total_steps == 0:
            return {
                "ok": False,
                "error": "当前活动没有配置步骤。",
                "progress": self.get_activity_progress(),
            }

        current_step = self.current_step

        # 已经完成当前步骤
        if current_step in self.completed_steps:
            return {
                "ok": True,
                "message": f"第 {current_step} 步已经完成。",
                "progress": self.get_activity_progress(),
            }

        # 标记完成
        self.completed_steps.add(current_step)

        # 最后一步
        if current_step >= self.total_steps:
            return {
                "ok": True,
                "message": "活动已经完成。",
                "progress": self.get_activity_progress(),
            }

        # 进入下一步
        self.current_step = current_step + 1

        return {
            "ok": True,
            "message": (
                f"第 {current_step} 步完成，"
                f"现在进入第 {self.current_step} 步。"
            ),
            "progress": self.get_activity_progress(),
        }

    # ============================================================
    # Knowledge retrieval
    # ============================================================

    def answer_context(
        self,
        user_question: str,
    ) -> TeachingContext:
        """
        查询活动知识。

        注意：

        这里负责回答：
        - 怎么做
        - 为什么
        - 注意什么
        - 失败怎么办
        - 某一步具体怎么做

        但不负责决定：
        - 总共有几步
        - 当前是哪一步
        - 当前是否完成
        - 是否进入下一步

        这些应该通过 get_activity_progress() 获取。
        """

        question = (user_question or "").strip()

        if not question:
            raise ValueError("user_question 不能为空")

        explicit_step = self._extract_step_number(question)

        search_step = (
            explicit_step
            if explicit_step is not None
            else self.current_step
        )

        results = self.retriever.retrieve(
            query=question,
            activity_id=self.activity_id,
            current_step=search_step,
            top_k=self.top_k,
        )

        # Step questions such as:
        # “第一步是什么？”
        # “第三步怎么做？”
        #
        # 如果检索没有直接找到对应步骤，
        # 则直接补充该步骤。
        if self._is_step_query(question) and search_step is not None:
            step = self.activity.get_step(search_step)

            if step is not None and not any(
                item.kind == "step"
                and item.step_id == search_step
                for item in results
            ):
                results.insert(
                    0,
                    KnowledgeResult(
                        activity_id=self.activity.id,
                        activity_name=self.activity.name,
                        kind="step",
                        title=step.title,
                        content=step.instruction,
                        step_id=step.id,
                        score=100,
                    ),
                )

        results = self._sort_for_teaching(
            results,
            search_step,
            is_step_query=self._is_step_query(question),
        )

        step = (
            self.activity.get_step(search_step)
            if search_step
            else None
        )

        return TeachingContext(
            activity_id=self.activity.id,
            activity_name=self.activity.name,
            current_step=search_step,
            current_step_title=(
                step.title
                if step
                else ""
            ),
            total_steps=self.total_steps,
            user_question=question,
            results=[
                self._result_to_dict(item)
                for item in results
            ],
            teaching_context=self._build_teaching_context(
                question=question,
                step_id=search_step,
                results=results,
            ),
        )

    # ============================================================
    # Knowledge helpers
    # ============================================================

    @staticmethod
    def _result_to_dict(
        result: KnowledgeResult,
    ) -> Dict[str, Any]:
        return {
            "kind": result.kind,
            "title": result.title,
            "content": result.content,
            "step_id": result.step_id,
            "score": result.score,
        }

    @staticmethod
    def _sort_for_teaching(
        results: List[KnowledgeResult],
        step_id: Optional[int],
        is_step_query: bool,
    ) -> List[KnowledgeResult]:

        def key(
            item: KnowledgeResult,
        ) -> tuple:
            same_step = (
                1
                if (
                    step_id is not None
                    and item.step_id == step_id
                )
                else 0
            )

            kind_priority = {
                "step": 3,
                "faq": 2,
                "activity": 1,
            }.get(
                item.kind,
                0,
            )

            if is_step_query:
                return (
                    same_step,
                    kind_priority,
                    item.score,
                )

            return (
                item.score,
                kind_priority,
                same_step,
            )

        return sorted(
            results,
            key=key,
            reverse=True,
        )

    @staticmethod
    def _build_teaching_context(
        question: str,
        step_id: Optional[int],
        results: List[KnowledgeResult],
    ) -> str:

        lines = [
            "你正在指导儿童完成一个手工活动。",
            f"孩子的问题：{question}",
            "回答要求：",
            "- 使用儿童容易理解的语言。",
            "- 一次只指导一个主要动作，不要一次讲完所有步骤。",
            "- 优先依据下面的活动知识回答，不要编造活动步骤。",
            "- 可以适当鼓励孩子，但不要过度夸张。",
        ]

        if step_id is not None:
            lines.append(
                f"当前/目标步骤：第 {step_id} 步。"
            )

        if results:
            lines.append("相关知识：")

            for index, item in enumerate(
                results[:5],
                start=1,
            ):
                step_text = (
                    f"第 {item.step_id} 步"
                    if item.step_id is not None
                    else "通用"
                )

                lines.append(
                    f"{index}. "
                    f"[{item.kind}] "
                    f"{step_text} "
                    f"{item.title}："
                    f"{item.content}"
                )

        else:
            lines.append(
                "相关知识：没有检索到足够的活动知识。"
            )

            lines.append(
                "此时不要假装知道具体步骤，"
                "可以请孩子换一种方式描述问题。"
            )

        return "\n".join(lines)

    # ============================================================
    # Text parsing
    # ============================================================

    @staticmethod
    def _extract_step_number(
        text: str,
    ) -> Optional[int]:

        patterns = [
            r"第\s*(\d+)\s*步",
            r"(?:step|STEP)\s*(\d+)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
            )

            if match:
                return int(match.group(1))

        chinese_numbers = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }

        match = re.search(
            r"第\s*([一二三四五六七八九十]+)\s*步",
            text,
        )

        if match:
            value = match.group(1)

            if value in chinese_numbers:
                return chinese_numbers[value]

        return None

    @staticmethod
    def _is_step_query(
        text: str,
    ) -> bool:

        return any(
            keyword in text
            for keyword in (
                "第几步",
                "第几步怎么",
                "第一步",
                "第二步",
                "第三步",
                "第四步",
                "第五步",
                "下一步",
                "上一步",
                "当前步骤",
            )
        ) or "step" in text.lower()