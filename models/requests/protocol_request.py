"""Request model: protocol"""

from pydantic import BaseModel, Field


class ProtocolListRequest(BaseModel):
    """Protocol request parameters"""

    active: bool | None = None
    protocolType: str | None = None
    protocolTypeList: list[int] = None
    statusType: int | None = None
    term: str | None = None


class AdminProtocolListRequest(ProtocolListRequest):
    """Admin protocol list parameters

    Adds cross-schema lookup, used to find a protocol from another schema to
    copy. It lives in a separate model on purpose: the user-facing
    /protocol/list builds ProtocolListRequest straight from the query string,
    so allSchemas must not be reachable from there.
    """

    allSchemas: bool = False


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
