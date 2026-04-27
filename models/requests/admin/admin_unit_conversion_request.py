from pydantic import BaseModel


class AdminUnitConversionLLMRequest(BaseModel):
    """Request model for LLM-based unit conversion suggestion."""

    class ConversionItem(BaseModel):
        idMeasureUnit: str
        description: str

    sctid: int
    drugName: str
    conversionList: list[ConversionItem]
