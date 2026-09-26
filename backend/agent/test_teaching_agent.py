from pathlib import Path

from backend.agent.teaching_agent import TeachingAgent
from backend.knowledge.loader import KnowledgeBaseLoader


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def main() -> None:
    loader = KnowledgeBaseLoader(
        KNOWLEDGE_DIR,
        project_root=PROJECT_ROOT,
    )
    agent = TeachingAgent(
        loader=loader,
        activity_id="stacking_cups",
        current_step=1,
        top_k=5,
    )

    print("=" * 60)
    print("[TeachingAgent] 第 2 步测试")
    print(f"[TeachingAgent] activity = {agent.activity.name}")
    print(f"[TeachingAgent] current_step = {agent.current_step}")
    print("-" * 60)

    questions = [
        "第一步是什么？",
        "纸杯为什么会倒？",
        "我可以搭得更高吗？",
        "第3步怎么做？",
    ]

    for question in questions:
        context = agent.answer_context(question)

        print(f"\n问题: {question}")
        print(f"目标步骤: {context.current_step}")
        print(f"目标步骤名称: {context.current_step_title}")
        print("检索结果:")
        for item in context.results:
            print(
                f"  - [{item['kind']}] "
                f"step={item['step_id']} "
                f"score={item['score']} "
                f"{item['title']}"
            )
        print("\nTeaching Context:")
        print(context.teaching_context)

    print("\n" + "=" * 60)
    print("[TeachingAgent] 测试完成")


if __name__ == "__main__":
    main()
