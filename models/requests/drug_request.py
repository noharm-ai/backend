"""Request model: drug related requests"""

from pydantic import BaseModel


class DrugUnitConversionRequest(BaseModel):
    """Request model for drug conversion data"""

    class DrugUnitConversionList(BaseModel):
        id_measure_unit: str
        factor: float

    conversion_list: list[DrugUnitConversionList]
