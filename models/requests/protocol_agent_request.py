"""Request model: protocol creation co-pilot (agent chat)"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProtocolAgentChatMessage(BaseModel):
    """One prior chat turn (transcript is held by the frontend)"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ProtocolAgentDraft(BaseModel):
    """Current (possibly incomplete) protocol form state"""

    name: Optional[str] = Field(default=None, max_length=250)
    protocolType: Optional[int] = None
    config: Optional[dict] = None


class ProtocolAgentChatRequest(BaseModel):
    """Protocol co-pilot: one stateless chat turn"""

    messages: list[ProtocolAgentChatMessage] = Field(
        default_factory=list, max_length=40
    )
    draft: ProtocolAgentDraft = Field(default_factory=ProtocolAgentDraft)
    message: str = Field(min_length=1, max_length=2000)
