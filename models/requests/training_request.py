"""Request model: training related requests"""

from typing import Optional

from pydantic import BaseModel


class TrainingItemFinishRequest(BaseModel):
    """Request model for registering that a user finished a training item"""

    durationSeconds: Optional[int] = None
