"""Request model: admin drug list request"""

from typing import Optional

from pydantic import BaseModel


class AdminDrugListRequest(BaseModel):
    """Request model for admin drug list endpoint"""

    hasPriceConversion: Optional[bool] = None
    hasSubstance: Optional[bool] = None
    hasDefaultUnit: Optional[bool] = None
    hasPriceUnit: Optional[bool] = None
    hasInconsistency: Optional[bool] = None
    hasAISubstance: Optional[bool] = None
    aiAccuracyRange: Optional[list] = None
    attributeList: Optional[list] = []
    term: Optional[str] = None
    substance: Optional[str] = None
    idSegmentList: Optional[list[int]] = None
    hasMaxDose: Optional[bool] = None
    limit: Optional[int] = 10
    offset: Optional[int] = 0
    tpRefMaxDose: Optional[str] = None
    substanceList: Optional[list] = []
    tpSubstanceList: Optional[str] = "in"
    minDrugCount: Optional[int] = None
    tpAttributeList: Optional[str] = "in"
    idDrugList: Optional[list[int]] = []
    hasSubstanceMaxDoseWeightAdult: Optional[bool] = None
    hasSubstanceMaxDoseWeightPediatric: Optional[bool] = None
