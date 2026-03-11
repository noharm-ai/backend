"""Service: Unit Conversion related operations"""

from decorators.has_permission_decorator import Permission, has_permission
from repository import unit_conversion_repository


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def get_unit_conversion_for_drug(id_drug: int):
    """Returns unit conversion possibilities for a single drug"""

    conversion_list = unit_conversion_repository.get_unit_conversion_for_drug(
        id_drug=id_drug
    )

    result = []
    for i in conversion_list:
        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idMeasureUnit": i.idMeasureUnit,
                "factor": i.factor,
                "measureUnit": i.description,
                "drugMeasureUnitNh": i.measureunit_nh,
            }
        )

    return {
        "name": conversion_list[0].name,
        "idDrug": conversion_list[0].id,
        "substanceMeasureUnit": conversion_list[0].default_measureunit,
        "conversionList": result,
    }
