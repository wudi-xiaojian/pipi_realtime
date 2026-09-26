from pathlib import Path

from backend.knowledge.loader import KnowledgeBaseLoader
from backend.knowledge.retriever import KnowledgeRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def main() -> None:
    loader = KnowledgeBaseLoader(KNOWLEDGE_DIR)

    print("=" * 60)
    print("[Knowledge] 本地 YAML 知识库测试")
    print(f"[Knowledge] directory = {KNOWLEDGE_DIR}")
    print(f"[Knowledge] activities = {loader.list_activities()}")

    activity = loader.load_activity("stacking_cups")

    print(f"[Knowledge] activity = {activity.name}")
    print(f"[Knowledge] steps = {len(activity.steps)}")
    print("-" * 60)

    retriever = KnowledgeRetriever([activity])

    queries = [
        ("第一步是什么？", 1),
        ("纸杯为什么会倒？", None),
        ("我可以搭得更高吗？", None),
    ]

    for query, current_step in queries:
        print(f"问题: {query}")
        results = retriever.retrieve(
            query=query,
            activity_id="stacking_cups",
            current_step=current_step,
            top_k=3,
        )

        if not results:
            print("  没有找到相关知识")
            continue

        for index, result in enumerate(results, start=1):
            print(
                f"  {index}. [{result.kind}] "
                f"step={result.step_id} "
                f"score={result.score} "
                f"{result.title}"
            )
            print(f"     {result.content}")

        print()

    print("=" * 60)
    print("[Knowledge] 测试完成")


if __name__ == "__main__":
    main()
