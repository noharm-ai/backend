from datetime import datetime
from typing import List

from sqlalchemy import and_, distinct, func, text
from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import MeasureUnit, MeasureUnitConvert
from models.enums import SegmentTypeEnum
from models.main import Drug, DrugAttributes, Outlier, Substance, User, db
from models.segment import Segment
from repository import drug_attributes_repository, drugs_repository
from repository.admin import admin_drug_repository
from services import drug_service as main_drug_service
from services.admin import admin_ai_service
from utils import dateutils, status


@has_permission(Permission.ADMIN_DRUGS)
def get_drug_list(
    has_substance=None,
    has_price_conversion=None,
    has_default_unit=None,
    has_price_unit=None,
    has_inconsistency=None,
    has_missing_conversion=None,
    attribute_list=[],
    term=None,
    substance=None,
    limit=10,
    offset=0,
    id_segment_list=None,
    has_ai_substance=None,
    ai_accuracy_range=None,
    has_max_dose=None,
    source_list=None,
    tp_ref_max_dose=None,
    substance_list=[],
    tp_substance_list=None,
    id_drug_list=[],
):
    results = drugs_repository.get_admin_drug_list(
        has_substance=has_substance,
        has_price_conversion=has_price_conversion,
        has_default_unit=has_default_unit,
        has_price_unit=has_price_unit,
        has_inconsistency=has_inconsistency,
        has_missing_conversion=has_missing_conversion,
        attribute_list=attribute_list,
        term=term,
        substance=substance,
        limit=limit,
        offset=offset,
        id_segment_list=id_segment_list,
        has_ai_substance=has_ai_substance,
        ai_accuracy_range=ai_accuracy_range,
        has_max_dose=has_max_dose,
        source_list=source_list,
        tp_ref_max_dose=tp_ref_max_dose,
        substance_list=substance_list,
        tp_substance_list=tp_substance_list,
        id_drug_list=id_drug_list,
    )

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
                "idDrug": i[0],
                "name": i[1],
                "idSegment": i[2],
                "segment": i[3],
                "idMeasureUnitDefault": i[4],
                "idMeasureUnitPrice": i[5],
                "measureUnitPriceFactor": i[8],
                "price": i[6],
                "sctid": i[7],
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


@has_permission(Permission.ADMIN_DRUGS)
def update_price_factor(id_drug, id_segment, factor):
    attributes = (
        db.session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )

    if attributes == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if attributes.idMeasureUnitPrice == None:
        raise ValidationError(
            "Medicamento não possui unidade de custo definida",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    conversion = MeasureUnitConvert.query.get(
        (attributes.idMeasureUnitPrice, id_drug, id_segment)
    )

    if conversion is None:
        conversion = MeasureUnitConvert()
        conversion.idMeasureUnit = attributes.idMeasureUnitPrice
        conversion.idDrug = id_drug
        conversion.idSegment = id_segment
        conversion.factor = factor

        db.session.add(conversion)
    else:
        conversion.factor = factor

        db.session.flush()


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
            calc_dose_max=False,
        )

    return len(inconsistent_drugs)


@has_permission(Permission.ADMIN_DRUGS)
def copy_drug_attributes(
    id_segment_origin,
    id_segment_destiny,
    user_context: User,
    user_permissions: List[Permission],
    attributes,
    from_admin_schema=True,
    overwrite_all=False,
):
    if not from_admin_schema and id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem igual ao segmento destino",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        overwrite_all
        and Permission.ADMIN_DRUGS__OVERWRITE_ATTRIBUTES not in user_permissions
    ):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not from_admin_schema and not id_segment_origin:
        raise ValidationError(
            "Segmento origem inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not id_segment_destiny:
        raise ValidationError(
            "Segmento destino inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    return admin_drug_repository.copy_attributes(
        from_admin_schema=from_admin_schema,
        id_segment_origin=id_segment_origin,
        id_segment_destiny=id_segment_destiny,
        attributes=attributes,
        user_context=user_context,
        overwrite_all=overwrite_all,
    )


@has_permission(Permission.ADMIN_DRUGS)
def predict_substance(id_drugs: List[int], user_context: User):
    if len(id_drugs) == 0 or len(id_drugs) > 200:
        raise ValidationError(
            "Parâmetro inválido (min=1; max=200)",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    drugs = (
        db.session.query(Drug)
        .filter(Drug.sctid == None)
        .filter(Drug.id.in_(id_drugs))
        .order_by(Drug.id)
        .all()
    )

    ia_results = admin_ai_service.get_substance(drugs)

    for i in ia_results:
        db.session.query(Drug).filter(Drug.id == i["idDrug"]).update(
            {
                "sctid": i["sctid"],
                "ai_accuracy": i["accuracy"],
                "updated_at": datetime.today(),
                "updated_by": user_context.id,
            },
            synchronize_session="fetch",
        )

        main_drug_service.copy_substance_default_attributes(
            i["idDrug"], i["sctid"], user_context, calc_dose_max=False
        )

    return ia_results


@has_permission(Permission.ADMIN_DRUGS)
def add_new_drugs_to_outlier(user_context: User):
    query = text(
        f"""
            insert into {user_context.schema}.outlier
                (fkmedicamento, idsegmento, contagem, doseconv, frequenciadia, escore, update_at, update_by)
            select
                pm.fkmedicamento, p.idsegmento, 0, 0, 0, 4, :updateAt, :updateBy
            from
	            {user_context.schema}.presmed pm
	            inner join {user_context.schema}.prescricao p on (pm.fkprescricao = p.fkprescricao)
            where
                p.update_at > now() - interval '5 days'
                and pm.idoutlier is null
                and p.idsegmento is not null
                and not exists (
                    select 1
                    from {user_context.schema}.outlier o
                    where o.fkmedicamento = pm.fkmedicamento and o.idsegmento = p.idsegmento
                )
            group by
	            pm.fkmedicamento, p.idsegmento
        """
    )

    return db.session.execute(
        query,
        {
            "updateAt": datetime.today(),
            "updateBy": user_context.id,
        },
    )


@has_permission(Permission.ADMIN_DRUGS)
def get_drugs_missing_substance():
    drugs = (
        db.session.query(func.distinct(Drug.id))
        .select_from(Outlier)
        .join(Drug, Drug.id == Outlier.idDrug)
        .filter(Drug.sctid == None)
        .order_by(Drug.id)
        .all()
    )

    id_drugs = []
    for d in drugs:
        id_drugs.append(d[0])

    return id_drugs


@has_permission(Permission.ADMIN_DRUGS, Permission.WRITE_DRUG_ATTRIBUTES)
def calculate_dosemax_uniq(id_drug: int, id_segment: int):
    """
    Calculates dosemax based on substance reference for one medatributos record
    """

    drug_attributes = drugs_repository.get_drug_attributes(
        id_drug=id_drug, id_segment=id_segment
    )
    conversions = drugs_repository.get_conversions(id_drug=id_drug)

    if not drug_attributes:
        return None

    attributes: DrugAttributes = drug_attributes[0].DrugAttributes
    segment: Segment = drug_attributes[0].Segment

    maxdose_ref = get_max_dose_ref(
        attributes=drug_attributes[0].DrugAttributes,
        drug=drug_attributes[0].Drug,
        substance=drug_attributes[0].Substance,
        segment=segment,
        conversions=conversions,
    )

    attributes.ref_maxdose = maxdose_ref.get("dosemax", None)
    attributes.ref_maxdose_weight = maxdose_ref.get("dosemaxWeight", None)

    if maxdose_ref["type"] == "converted":
        attributes.maxDose = (
            attributes.ref_maxdose_weight
            if attributes.useWeight
            else attributes.ref_maxdose
        )
    else:
        attributes.maxDose = None

    db.session.flush()

    return attributes


@has_permission(Permission.ADMIN_DRUGS)
def calculate_dosemax_bulk(user_context: User):
    """
    Calculates dosemax based on substance reference from all records in medatributos table.
    Updates dosemax attribute if its empty or updated by internal staff
    """

    current_drugs = drugs_repository.get_drug_attributes()
    conversions = drugs_repository.get_conversions()
    update_list = []

    converted = 0
    not_converted = 0
    no_reference = 0
    updated = 0

    for item in current_drugs:
        attributes: DrugAttributes = item.DrugAttributes
        drug: Drug = item.Drug
        substance: Substance = item.Substance
        segment: Segment = item.Segment

        max_dose_ref = get_max_dose_ref(
            attributes=attributes,
            drug=drug,
            substance=substance,
            segment=segment,
            conversions=conversions,
        )

        if max_dose_ref["type"] == "converted":
            converted += 1
            update_list.append(max_dose_ref)

        not_converted += 1 if max_dose_ref["type"] == "not_converted" else 0
        no_reference += 1 if max_dose_ref["type"] == "no_reference" else 0

    if update_list:
        drug_attributes_repository.update_dose_max(
            update_list=update_list, schema=user_context.schema
        )

        copy_result = drug_attributes_repository.copy_dose_max_from_ref(
            schema=user_context.schema, update_by=user_context.id
        )
        updated = copy_result.rowcount

    return {
        "converted": converted,
        "notConverted": not_converted,
        "noReference": no_reference,
        "updated": updated,
    }


@has_permission(Permission.ADMIN_DRUGS, Permission.WRITE_DRUG_ATTRIBUTES)
def get_max_dose_ref(
    attributes: DrugAttributes,
    drug: Drug,
    segment: Segment,
    substance: Substance,
    conversions: list[(MeasureUnitConvert, MeasureUnit)],
):
    """
    Calculates dosemax based on substance reference.
    """

    ref_dose = None
    ref_dose_weight = None
    max_decimals = 3

    def get_conversion(id_drug: int, id_segment: int, measureunit_nh: str):
        c_list = filter(
            lambda item: item.MeasureUnitConvert.idDrug == id_drug
            and item.MeasureUnitConvert.idSegment == id_segment
            and item.MeasureUnit.measureunit_nh == measureunit_nh,
            conversions,
        )

        result = next(c_list, None)

        if result:
            return result.MeasureUnitConvert.factor

        return None

    if not segment.type:
        raise ValidationError(
            "Tipo de segmento não está configurado",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if segment.type == SegmentTypeEnum.ADULT.value:
        ref_dose = substance.maxdose_adult
        ref_dose_weight = substance.maxdose_adult_weight
    if segment.type == SegmentTypeEnum.PEDIATRIC.value:
        ref_dose = substance.maxdose_pediatric
        ref_dose_weight = substance.maxdose_pediatric_weight

    result = {
        "idDrug": drug.id,
        "idSegment": attributes.idSegment,
    }

    if ref_dose or ref_dose_weight:
        conversion = get_conversion(
            id_drug=drug.id,
            id_segment=attributes.idSegment,
            measureunit_nh=substance.default_measureunit,
        )

        if conversion:
            result["type"] = "converted"

            if ref_dose:
                result["dosemax"] = round(ref_dose * conversion, max_decimals)

            if ref_dose_weight:
                result["dosemaxWeight"] = round(
                    ref_dose_weight * conversion, max_decimals
                )
        else:
            result["type"] = "not_converted"
    else:
        result["type"] = "no_reference"

    return result
