"""Request model: protocol"""

from pydantic import BaseModel, Field


class ProtocolListRequest(BaseModel):
    """Protocol request parameters"""

    active: bool | None = None
    protocolType: str | None = None
    protocolTypeList: list[int] = None
    statusType: int | None = None


class ProtocolDescriptionRequest(BaseModel):
    """Protocol description request parameters"""

    idProtocol: int


class ProtocolTraceRequest(BaseModel):
    """Protocol trace request parameters"""

    idPrescription: int
    idProtocol: int | None = None


class ProtocolConfig(BaseModel):
    """Protocol: structure of a protocol configuration"""

    result: dict
    trigger: str
    variables: list[dict]


class ProtocolTestSampleRequest(BaseModel):
    """Protocol test: sample prescriptions of the current day to test against"""

    protocolType: int
    idSegment: int | None = None
    limit: int = Field(default=100, ge=1, le=200)


class ProtocolTestRequest(BaseModel):
    """Protocol test: evaluate an unsaved config against a chunk of prescriptions"""

    config: ProtocolConfig
    protocolType: int
    idPrescriptionList: list[int] = Field(min_length=1, max_length=10)
    detailed: bool = False
    name: str = "Protocolo em teste"


class ProtocolUpsertRequest(BaseModel):
    """Protocol create/update request params"""

    id: int = None
    name: str
    protocolType: int
    statusType: int
    config: ProtocolConfig


class ProtocolAiVariable(BaseModel):
    """Protocol AI: declared variable as prompt context (name + human summary)"""

    name: str = Field(min_length=1, max_length=50)
    summary: str = Field(default="", max_length=300)


class ProtocolAiGenerateTriggerRequest(BaseModel):
    """Protocol AI: generate a trigger expression from a natural-language hint"""

    hint: str = Field(min_length=3, max_length=500)
    variables: list[ProtocolAiVariable] = Field(min_length=1, max_length=50)
    currentTrigger: str | None = Field(default=None, max_length=1000)


class ProtocolAiReviewTriggerRequest(BaseModel):
    """Protocol AI: review a trigger expression for semantic issues"""

    trigger: str = Field(min_length=1, max_length=1000)
    variables: list[ProtocolAiVariable] = Field(min_length=1, max_length=50)
    resultMessage: str | None = Field(default=None, max_length=500)
    resultDescription: str | None = Field(default=None, max_length=1000)
