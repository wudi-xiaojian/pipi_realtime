from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ActivityStep:
    id: int
    title: str
    instruction: str
    goal: str = ""
    tips: List[str] = field(default_factory=list)
    common_questions: List[Dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ActivityKnowledge:
    id: str
    name: str
    age: str = ""
    description: str = ""
    goals: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    steps: List[ActivityStep] = field(default_factory=list)
    safety: List[str] = field(default_factory=list)
    common_questions: List[Dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActivityKnowledge":
        steps = [
            ActivityStep(
                id=int(item["id"]),
                title=str(item.get("title", "")),
                instruction=str(item.get("instruction", "")),
                goal=str(item.get("goal", "")),
                tips=[str(tip) for tip in item.get("tips", [])],
                common_questions=[
                    {
                        "question": str(q.get("question", "")),
                        "answer": str(q.get("answer", "")),
                    }
                    for q in item.get("common_questions", [])
                ],
            )
            for item in data.get("steps", [])
        ]

        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            age=str(data.get("age", "")),
            description=str(data.get("description", "")),
            goals=[str(item) for item in data.get("goals", [])],
            materials=[str(item) for item in data.get("materials", [])],
            steps=steps,
            safety=[str(item) for item in data.get("safety", [])],
            common_questions=[
                {
                    "question": str(q.get("question", "")),
                    "answer": str(q.get("answer", "")),
                }
                for q in data.get("common_questions", [])
            ],
        )

    def get_step(self, step_id: int) -> Optional[ActivityStep]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
