import re
from dataclasses import dataclass
from typing import List, Optional

from backend.knowledge.models import ActivityKnowledge, ActivityStep


@dataclass(frozen=True)
class KnowledgeResult:
    activity_id: str
    activity_name: str
    kind: str
    title: str
    content: str
    step_id: Optional[int] = None
    score: int = 0


class KnowledgeRetriever:
    """Simple keyword retriever for the first local-YAML version.

    This intentionally does not use embeddings or a vector database yet.
    The goal of step 1 is to prove that local activity knowledge can be
    loaded and retrieved reliably before adding an Agent or RAG service.
    """

    def __init__(self, activities: List[ActivityKnowledge]):
        self.activities = activities

    def retrieve(
        self,
        query: str,
        activity_id: Optional[str] = None,
        current_step: Optional[int] = None,
        top_k: int = 5,
    ) -> List[KnowledgeResult]:
        candidates = [
            activity
            for activity in self.activities
            if activity_id is None or activity.id == activity_id
        ]

        query_tokens = self._tokenize(query)
        results: List[KnowledgeResult] = []

        for activity in candidates:
            # Activity-level information.
            activity_text = " ".join(
                [
                    activity.name,
                    activity.description,
                    *activity.goals,
                    *activity.materials,
                ]
            )
            score = self._score(query_tokens, activity_text)
            if score > 0:
                results.append(
                    KnowledgeResult(
                        activity_id=activity.id,
                        activity_name=activity.name,
                        kind="activity",
                        title=activity.name,
                        content=activity.description,
                        score=score,
                    )
                )

            for step in activity.steps:
                step_text = " ".join(
                    [
                        step.title,
                        step.instruction,
                        step.goal,
                        *step.tips,
                    ]
                )
                score = self._score(query_tokens, step_text)

                # If the caller already knows the current step, give it a
                # small deterministic boost rather than replacing retrieval.
                if current_step is not None and step.id == current_step:
                    score += 3

                if score > 0:
                    results.append(
                        KnowledgeResult(
                            activity_id=activity.id,
                            activity_name=activity.name,
                            kind="step",
                            title=step.title,
                            content=step.instruction,
                            step_id=step.id,
                            score=score,
                        )
                    )

                for question in step.common_questions:
                    question_text = " ".join(
                        [
                            question.get("question", ""),
                            question.get("answer", ""),
                        ]
                    )
                    score = self._score(query_tokens, question_text)
                    if score > 0:
                        results.append(
                            KnowledgeResult(
                                activity_id=activity.id,
                                activity_name=activity.name,
                                kind="faq",
                                title=question.get("question", ""),
                                content=question.get("answer", ""),
                                step_id=step.id,
                                score=score,
                            )
                        )

            for question in activity.common_questions:
                question_text = " ".join(
                    [
                        question.get("question", ""),
                        question.get("answer", ""),
                    ]
                )
                score = self._score(query_tokens, question_text)
                if score > 0:
                    results.append(
                        KnowledgeResult(
                            activity_id=activity.id,
                            activity_name=activity.name,
                            kind="faq",
                            title=question.get("question", ""),
                            content=question.get("answer", ""),
                            score=score,
                        )
                    )

        results.sort(
            key=lambda item: item.score,
            reverse=True,
        )
        return results[:top_k]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        # Keep Chinese characters as individual searchable units and keep
        # contiguous Latin/numeric words together.
        return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower())

    @classmethod
    def _score(cls, query_tokens: List[str], text: str) -> int:
        if not query_tokens:
            return 0

        text_tokens = cls._tokenize(text)
        text_set = set(text_tokens)
        return sum(1 for token in query_tokens if token in text_set)
