"""Service: admin drug related operations"""

from sqlalchemy import and_, distinct, text
from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import SegmentTypeEnum
from models.main import Drug, DrugAttributes, Outlier, Substance, User, db
from models.requests.admin.admin_drug_request import AdminDrugListRequest
from repository import drugs_repository
from services import drug_service as main_drug_service
from utils import dateutils, status


@has_permission(Permission.ADMIN_DRUGS)
def get_drug_list(request_data: AdminDrugListRequest):
    results = drugs_repository.get_admin_drug_list(request_data=request_data)

    items = []
    for i in results:
        subst_max_dose = None
        subst_max_dose_weight = None

        if i.segment_type == SegmentTypeEnum.ADULT.value:
            subst_max_dose = i.maxdose_adult
            subst_max_dose_weight = i.maxdose_adult_weight

        if i.segment_type == SegmentTypeEnum.PEDIATRIC.value:
            subst_max_dose = i.maxdose_pediatric
            subst_max_dose_weight = i.maxdose_pediatric_weight

        items.append(
            {
                "idDrug": str(i[0]),
                "name": i[1],
                "idSegment": i[2],
                "segment": i[3],
                "idMeasureUnitDefault": i[4],
                "idMeasureUnitPrice": i[5],
                "measureUnitPriceFactor": i[8],
                "price": i[6],
                "sctid": str(i[7]) if i[7] else None,
                "substance": i[10],
                "segmentOutlier": i[11],
                "substanceAccuracy": i[12],
                "maxDose": i.maxDose,
                "useWeight": i.useWeight,
                "measureUnitDefaultName": i.measure_unit_default_name,
                "refMaxDose": i.ref_maxdose,
                "refMaxDoseWeight": i.ref_maxdose_weight,
                "substanceMaxDose": subst_max_dose,
                "substanceMaxDoseWeight": subst_max_dose_weight,
                "substanceMeasureUnit": i.default_measureunit,
                "measureUnitNH": i.measureunit_nh,
                "responsible": i.responsible,
                "updateAt": dateutils.to_iso(i.update),
                "drugCount": i.drug_count,
                "doseRange": i.division,
            }
        )

    count = 0
    if len(results) > 0:
        count = results[0].total

    return {"list": items, "count": count}


@has_permission(Permission.ADMIN_DRUGS)
def get_drug_ref(sctid: int):
    subst = (
        db.session.query(Substance)
        .filter(Substance.id == sctid)
        .options(undefer(Substance.admin_text))
        .first()
    )

    if subst == None:
        raise ValidationError(
            "Substância inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return {"name": subst.name, "ref": subst.admin_text}


@has_permission(Permission.ADMIN_DRUGS, Permission.WRITE_SEGMENT_SCORE)
def fix_inconsistency(user_context: User):
    schema = user_context.schema

    # normalize medatributos
    query_normalize = text(
        f"""
        update
            {schema}.medatributos
        set
            fkunidademedida = null
        where
            fkunidademedida = ''
    """
    )

    db.session.execute(query_normalize)

    inconsistent_drugs = (
        db.session.query(distinct(Outlier.idDrug), Drug.sctid)
        .select_from(Outlier)
        .join(Drug, Drug.id == Outlier.idDrug)
        .outerjoin(
            DrugAttributes,
            and_(
                Outlier.idDrug == DrugAttributes.idDrug,
                Outlier.idSegment == DrugAttributes.idSegment,
            ),
        )
        .filter(DrugAttributes.idDrug == None)
        .filter(Drug.sctid != None)
        .all()
    )

    for d in inconsistent_drugs:
        main_drug_service.copy_substance_default_attributes(
            id_drug=d[0],
            sctid=d[1],
            user=user_context,
            overwrite=False,
        )

    return len(inconsistent_drugs)
