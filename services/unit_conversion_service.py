"""Service: Unit Conversion related operations"""

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import DefaultMeasureUnitEnum
from repository import unit_conversion_repository


@has_permission(Permission.WRITE_DRUG_ATTRIBUTES)
def get_unit_conversion_for_drug(id_drug: int):
    """Returns unit conversion possibilities for a single drug"""

    configured_measure_units = (
        unit_conversion_repository.get_drugattributes_default_measure_unit_for_drug(
            id_drug=id_drug
        )
    )

    conversion_list = unit_conversion_repository.get_unit_conversion_for_drug(
        id_drug=id_drug
    )

    substanceMeasureUnit = (
        conversion_list[0].default_measureunit if len(conversion_list) > 0 else None
    )

    show_factors = True

    if len(configured_measure_units) > 1:
        # more than one configured unit
        show_factors = False
    elif len(configured_measure_units) == 1:
        if configured_measure_units[0].measureunit_nh != substanceMeasureUnit:
            # configured unit is different from default unit
            show_factors = False

    if len(conversion_list) > 0 and substanceMeasureUnit is None:
        substanceMeasureUnit = DefaultMeasureUnitEnum.MG.value
        show_factors = False

    result = []
    for i in conversion_list:
        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idMeasureUnit": i.idMeasureUnit,
                "factor": i.factor if show_factors else None,
                "measureUnit": i.description,
                "drugMeasureUnitNh": i.measureunit_nh,
                "default": substanceMeasureUnit == i.measureunit_nh,
            }
        )

    return {
        "name": conversion_list[0].name,
        "idDrug": conversion_list[0].id,
        "substanceMeasureUnit": substanceMeasureUnit,
        "conversionList": result,
    }
