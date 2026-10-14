import unittest
from pathlib import Path

from backend.agent.teaching_agent import TeachingAgent
from backend.knowledge.loader import KnowledgeBaseLoader
from backend.knowledge.models import ActivityKnowledge, ActivityStep
from backend.knowledge.retriever import KnowledgeRetriever


class RetrievalBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.retriever = KnowledgeRetriever([
            ActivityKnowledge(
                id="cups", name="纸杯搭建",
                steps=[
                    ActivityStep(id=1, title="观察", instruction="观察纸杯形状"),
                    ActivityStep(id=2, title="放稳", instruction="把纸杯放稳"),
                ],
            )
        ])

    def test_unmatched_question_does_not_return_current_step(self):
        for query in ("", "你好", "天气", "hello"):
            with self.subTest(query=query):
                self.assertEqual(
                    self.retriever.retrieve(query, current_step=1), []
                )

    def test_matching_current_step_keeps_ranking_boost(self):
        results = self.retriever.retrieve("纸杯", current_step=2)
        self.assertEqual(results[0].step_id, 2)
        self.assertGreater(results[0].score, results[1].score)

    def test_explicit_step_guidance_still_works(self):
        root = Path(__file__).resolve().parents[2]
        agent = TeachingAgent(
            loader=KnowledgeBaseLoader(root / "knowledge"),
            activity_id="stacking_cups", current_step=1,
        )
        context = agent.answer_context("第3步怎么做？")
        self.assertEqual(context.current_step, 3)
        self.assertTrue(any(
            result["kind"] == "step" and result["step_id"] == 3
            for result in context.results
        ))
        self.assertEqual(agent.current_step, 1)
        self.assertEqual(agent.completed_steps, set())


if __name__ == "__main__":
    unittest.main()
