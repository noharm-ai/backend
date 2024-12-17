from pydantic import BaseModel
from typing import Optional


class RegulationMovementRequest(BaseModel):
    id: Optional[int] = None
    ids: Optional[list[int]] = None
    action: int
    actionData: dict
    actionDataTemplate: list[dict]
    nextStage: int
