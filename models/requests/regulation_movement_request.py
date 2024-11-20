from pydantic import BaseModel


class RegulationMovementRequest(BaseModel):
    id: int
    action: int
    actionData: dict
    nextStage: int
