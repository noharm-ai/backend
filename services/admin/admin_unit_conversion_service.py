import json
from datetime import datetime

import boto3
import requests
from markupsafe import escape as escape_html
from sqlalchemy import and_, func, text

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.appendix import MeasureUnit, MeasureUnitConvert
from models.enums import DefaultMeasureUnitEnum, SegmentTypeEnum
from models.main import (
    Drug,
    DrugAttributes,
    Outlier,
    PrescriptionAgg,
    Substance,
    User,
    db,
)
from models.requests.admin.admin_unit_conversion_request import SetFactorRequest
from models.segment import Segment
from services import drug_service as main_drug_service
from services.admin import (
    admin_drug_service,
)
from utils import status


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_predictions(conversion_list: list) -> list:
    to_infer = []
    for index, conversion_item in enumerate(conversion_list):
        destiny_unit = (
            conversion_item.get("substanceMeasureUnit", DefaultMeasureUnitEnum.MG.value)
            if conversion_item.get("substanceMeasureUnit", None)
            else DefaultMeasureUnitEnum.MG.value
        )

        if conversion_item.get("prediction", None) is None:
            # Sanitize user input to prevent XSS
            name = conversion_item.get("name")
            sctid = conversion_item.get("sctid")

            to_infer.append(
                {
                    "id": index,
                    "nome": escape_html(str(name)) if name is not None else None,
                    "unidade_noharm": destiny_unit,
                    "fkunidademedida": conversion_item.get("idMeasureUnit"),
                    "sctid": escape_html(str(sctid)) if sctid is not None else None,
                }
            )

    if to_infer:
        if not Config.SERVICE_INFERENCE:
            raise ValueError("SERVICE_INFERENCE not set")

        try:
            response = requests.post(
                f"{Config.SERVICE_INFERENCE}conversion-units/infer",
                json={"conversion_unit_list": to_infer},
                timeout=25,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException:
            raise ValidationError(
                "Serviço de inferência indisponível",
                "errors.serviceUnavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response_object = response.json()

        for item in response_object:
            try:
                if item.get("probability", 0) < 80:
                    conversion_list[item.get("id")]["prediction"] = "Curadoria"
                else:
                    conversion_list[item.get("id")]["prediction"] = float(
                        item.get("prediction")
                    )
            except ValueError:
                conversion_list[item.get("id")]["prediction"] = "Curadoria"

            conversion_list[item.get("id")]["probability"] = item.get("probability")

    return conversion_list


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def get_conversion_list(id_segment):
    nh_default_units = (
        db.session.query(MeasureUnit)
        .filter(
            MeasureUnit.measureunit_nh.in_(
                [
                    DefaultMeasureUnitEnum.MCG.value,
                    DefaultMeasureUnitEnum.MG.value,
                    DefaultMeasureUnitEnum.ML.value,
                    DefaultMeasureUnitEnum.UI.value,
                ]
            )
        )
        .all()
    )

    if not nh_default_units:
        raise ValidationError(
            "Pendência de configuração das unidades de medida",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    default_units = {}
    for du in nh_default_units:
        default_units[du.measureunit_nh] = {
            "idMeasureUnit": du.id,
            "description": du.description,
        }

    active_drugs = (
        db.session.query(
            Outlier.idDrug.label("idDrug"),
            func.sum(Outlier.countNum).label("prescribed_quantity"),
        )
        .group_by(Outlier.idDrug)
        .cte("active_drugs")
    )

    prescribed_units = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idMeasureUnit.label("idMeasureUnit"),
        )
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(PrescriptionAgg.idMeasureUnit != "")
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idMeasureUnit)
    )

    current_units = (
        db.session.query(
            MeasureUnitConvert.idDrug.label("idDrug"),
            MeasureUnitConvert.idMeasureUnit.label("idMeasureUnit"),
        )
        .filter(MeasureUnitConvert.idMeasureUnit != None)
        .filter(MeasureUnitConvert.idMeasureUnit != "")
        .group_by(MeasureUnitConvert.idDrug, MeasureUnitConvert.idMeasureUnit)
    )

    price_units = (
        db.session.query(
            DrugAttributes.idDrug.label("idDrug"),
            DrugAttributes.idMeasureUnitPrice.label("idMeasureUnit"),
        )
        .filter(DrugAttributes.idMeasureUnitPrice != None)
        .filter(DrugAttributes.idMeasureUnitPrice != "")
        .group_by(DrugAttributes.idDrug, DrugAttributes.idMeasureUnitPrice)
    )

    units = prescribed_units.union(price_units, current_units).cte("units")

    conversion_list = (
        db.session.query(
            func.count().over(),
            Drug.id,
            Drug.name,
            units.c.idMeasureUnit,
            MeasureUnitConvert.factor,
            MeasureUnit.description,
            Drug.sctid,
            Substance.default_measureunit,
            MeasureUnit.measureunit_nh,
            active_drugs.c.prescribed_quantity,
            Substance.tags,
        )
        .join(active_drugs, Drug.id == active_drugs.c.idDrug)
        .join(units, Drug.id == units.c.idDrug)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idSegment == id_segment,
                MeasureUnitConvert.idMeasureUnit == units.c.idMeasureUnit,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == units.c.idMeasureUnit)
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .order_by(Drug.name, MeasureUnitConvert.factor)
        .all()
    )

    result = []
    drug_defaultunit = set()
    for i in conversion_list:
        prediction = None
        probability = None
        if i.default_measureunit == i.measureunit_nh:
            drug_defaultunit.add(i.id)

            if i.measureunit_nh:
                prediction = 1
                probability = 100

        result.append(
            {
                "id": f"{i.id}-{i.idMeasureUnit}",
                "idDrug": i[1],
                "name": escape_html(str(i[2])) if i[2] is not None else None,
                "idMeasureUnit": i[3],
                "factor": i[4],
                "idSegment": escape_html(str(id_segment)),
                "measureUnit": escape_html(str(i[5])) if i[5] is not None else None,
                "sctid": escape_html(str(i.sctid)) if i.sctid is not None else None,
                "substanceMeasureUnit": i.default_measureunit,
                "drugMeasureUnitNh": i.measureunit_nh,
                "prediction": prediction,
                "probability": probability,
                "prescribedQuantity": i.prescribed_quantity,
                "substanceTags": i.tags,
            }
        )

    for i in conversion_list:
        if i.id not in drug_defaultunit and i.default_measureunit:
            drug_defaultunit.add(i.id)

            d_unit = default_units.get(i.default_measureunit, None)

            if d_unit:
                result.append(
                    {
                        "id": f"{i.id}-{d_unit.get('idMeasureUnit')}",
                        "idDrug": i.id,
                        "name": escape_html(str(i.name))
                        if i.name is not None
                        else None,
                        "idMeasureUnit": d_unit.get("idMeasureUnit"),
                        "factor": None,
                        "idSegment": escape_html(str(id_segment)),
                        "measureUnit": escape_html(str(d_unit.get("description")))
                        if d_unit.get("description") is not None
                        else None,
                        "sctid": escape_html(str(i.sctid))
                        if i.sctid is not None
                        else None,
                        "substanceMeasureUnit": i.default_measureunit,
                        "drugMeasureUnitNh": i.measureunit_nh,
                        "prediction": 1,
                        "probability": 100,
                        "prescribed_quantity": i.prescribed_quantity,
                        "substanceTags": i.tags,
                    }
                )

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def save_conversions(
    id_drug, id_segment, id_measure_unit_default, conversion_list, user_context: User
):
    if (
        id_drug == None
        or id_segment == None
        or id_measure_unit_default == None
        or conversion_list == None
        or len(conversion_list) == 0
    ):
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    for uc in conversion_list:
        try:
            factor = float(uc["factor"]) if uc["factor"] is not None else None
            uc["factor"] = factor
        except (ValueError, TypeError):
            raise ValidationError(
                "Fator de conversão deve ser um número válido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        if uc["factor"] is None or uc["factor"] == 0:
            raise ValidationError(
                "Fator de conversão inválido",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

    # update all segments
    updated_segments = []
    segments = db.session.query(Segment).all()

    for s in segments:
        updated_segments.append(s.description)

        # set drug attributes
        da = (
            db.session.query(DrugAttributes)
            .filter(DrugAttributes.idDrug == id_drug)
            .filter(DrugAttributes.idSegment == s.id)
            .first()
        )

        if da is None:
            da = main_drug_service.create_attributes_from_reference(
                id_drug=id_drug, id_segment=s.id, user=user_context
            )

        da.idMeasureUnit = id_measure_unit_default
        da.update = datetime.today()
        da.user = user_context.id

        db.session.flush()

        # update conversions
        _update_conversion_list(
            conversion_list=conversion_list,
            id_drug=id_drug,
            id_segment=s.id,
            user=user_context,
        )

        admin_drug_service.calculate_dosemax_uniq(id_drug=id_drug, id_segment=s.id)

    # call lambda to generate scores (do not wait for response)
    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "command": "lambda_scores.process_drug_scores",
                "schema": user_context.schema,
                "id_user": user_context.id,
                "id_drug": id_drug,
            }
        ),
    )

    return {"updated": updated_segments}


def _update_conversion_list(conversion_list, id_drug, id_segment, user):
    for uc in conversion_list:
        insert_units = text(
            f"""
            insert into {user.schema}.unidadeconverte
                (idsegmento, fkmedicamento, fkunidademedida, fator)
            values
                (:id_segment, :id_drug, :id_measure_unit, :factor)
            on conflict (idsegmento, fkmedicamento, fkunidademedida)
            do update set fator = :factor
        """
        )

        db.session.execute(
            insert_units,
            {
                "id_segment": id_segment,
                "id_drug": id_drug,
                "id_measure_unit": uc["idMeasureUnit"],
                "factor": uc["factor"],
            },
        )


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def add_default_units(user_context: User):
    schema = user_context.schema

    admin_drug_service.fix_inconsistency()

    query = text(
        f"""
        with unidades as (
            select
                fkmedicamento, min(fkunidademedida) as fkunidademedida
            from (
                select
                    fkmedicamento, fkunidademedida
                from {schema}.prescricaoagg p
                where
                    p.fkunidademedida is not null
                    and p.fkunidademedida <> ''
                    and p.fkmedicamento in (
                        select fkmedicamento from {schema}.medatributos m where m.fkunidademedida is null
                    )
                group by fkmedicamento, fkunidademedida
            ) a
            group by fkmedicamento
            having count(*) = 1
        ), unidades_segmento as (
            select fkmedicamento, fkunidademedida, s.idsegmento  from unidades, {schema}.segmento s
        )
        update
            {schema}.medatributos ma
        set
            fkunidademedida = unidades_segmento.fkunidademedida
        from
            unidades_segmento
        where
            ma.fkmedicamento = unidades_segmento.fkmedicamento
            and ma.idsegmento = unidades_segmento.idsegmento
            and ma.fkunidademedida is null
    """
    )

    insert_units = text(
        f"""
        insert into {schema}.unidadeconverte
            (idsegmento, fkmedicamento, fkunidademedida, fator)
        select
            m.idsegmento, m.fkmedicamento, m.fkunidademedida, 1
        from
            {schema}.medatributos m
        where
            m.fkunidademedida is not null
            and m.fkunidademedida != ''
        on conflict (idsegmento, fkmedicamento, fkunidademedida)
        do nothing
    """
    )

    result = db.session.execute(query)

    db.session.execute(insert_units)

    return result


@has_permission(Permission.ADMIN_UNIT_CONVERSION)
def copy_unit_conversion(id_segment_origin, id_segment_destiny, user_context: User):
    schema = user_context.schema

    if id_segment_origin == None or id_segment_destiny == None:
        raise ValidationError(
            "Segmento Inválido", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    if id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem deve ser diferente do segmento destino",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
        with conversao_origem as (
            select
                ma.fkmedicamento, ma.idsegmento, ma.fkunidademedida
            from
                {schema}.medatributos ma
                inner join {schema}.medatributos madestino on (
                    ma.fkmedicamento = madestino.fkmedicamento
                    and madestino.idsegmento  = :idSegmentDestiny
                    and ma.fkunidademedida = madestino.fkunidademedida
                )
            where
                ma.idsegmento = :idSegmentOrigin
        )
        insert into {schema}.unidadeconverte (idsegmento, fkunidademedida, fator, fkmedicamento) (
            select
                :idSegmentDestiny as idsegmento,
                u.fkunidademedida,
                u.fator,
                u.fkmedicamento
            from
                {schema}.unidadeconverte u
                inner join conversao_origem on (
                    u.fkmedicamento = conversao_origem.fkmedicamento
                    and u.idsegmento = conversao_origem.idsegmento
                )
        )
        on conflict (fkunidademedida, idsegmento, fkmedicamento)
        do update set fator = excluded.fator
    """
    )

    return db.session.execute(
        query,
        {"idSegmentOrigin": id_segment_origin, "idSegmentDestiny": id_segment_destiny},
    )


@has_permission(Permission.ADMIN_DRUGS)
def sut_substanceunit_factor(request_data: SetFactorRequest):
    drug_info = (
        db.session.query(DrugAttributes, Drug, Substance, Segment, MeasureUnit)
        .join(Drug, DrugAttributes.idDrug == Drug.id)
        .join(Segment, DrugAttributes.idSegment == Segment.id)
        .join(Substance, Drug.sctid == Substance.id)
        .outerjoin(MeasureUnit, DrugAttributes.idMeasureUnit == MeasureUnit.id)
        .filter(DrugAttributes.idDrug == request_data.idDrug)
        .filter(DrugAttributes.idSegment == request_data.idSegment)
        .first()
    )

    if drug_info == None:
        raise ValidationError(
            "Registro inexistente", "errors.invalidRecord", status.HTTP_400_BAD_REQUEST
        )

    attributes: DrugAttributes = drug_info.DrugAttributes
    substance: Substance = drug_info.Substance
    default_measure_unit: MeasureUnit = drug_info.MeasureUnit
    segment: Segment = drug_info.Segment

    if not attributes.idMeasureUnit:
        raise ValidationError(
            "Medicamento não possui unidade padrão definida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not substance.default_measureunit:
        raise ValidationError(
            "Substância não possui unidade padrão definida",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        default_measure_unit
        and default_measure_unit.measureunit_nh == substance.default_measureunit
    ):
        raise ValidationError(
            "A unidade de medida da substância é igual a do medicamento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    measureunit = (
        db.session.query(MeasureUnit)
        .filter(MeasureUnit.measureunit_nh == substance.default_measureunit)
        .first()
    )

    if not measureunit:
        raise ValidationError(
            f"Não há relação para a unidade: {substance.default_measureunit}",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    conversion = (
        db.session.query(MeasureUnitConvert)
        .filter(
            MeasureUnitConvert.idDrug == request_data.idDrug,
            MeasureUnitConvert.idSegment == request_data.idSegment,
            MeasureUnitConvert.idMeasureUnit == measureunit.id,
        )
        .first()
    )

    factor = 1 / request_data.factor

    if conversion is None:
        conversion = MeasureUnitConvert()
        conversion.idMeasureUnit = measureunit.id
        conversion.idDrug = request_data.idDrug
        conversion.idSegment = request_data.idSegment
        conversion.factor = factor

        db.session.add(conversion)
    else:
        conversion.factor = factor
        db.session.flush()

    # update ref max dose
    subst_max_dose = None
    subst_max_dose_weight = None

    if segment.type == SegmentTypeEnum.ADULT.value:
        subst_max_dose = substance.maxdose_adult
        subst_max_dose_weight = substance.maxdose_adult_weight

    if segment.type == SegmentTypeEnum.PEDIATRIC.value:
        subst_max_dose = substance.maxdose_pediatric
        subst_max_dose_weight = substance.maxdose_pediatric_weight

    attributes.ref_maxdose = subst_max_dose * factor if subst_max_dose else None
    attributes.ref_maxdose_weight = (
        subst_max_dose_weight * factor if subst_max_dose_weight else None
    )
    db.session.flush()

    return {
        "idDrug": attributes.idDrug,
        "idSegment": attributes.idSegment,
        "refMaxDose": attributes.ref_maxdose,
        "refMaxDoseWeight": attributes.ref_maxdose_weight,
    }
