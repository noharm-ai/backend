from sqlalchemy import and_, or_, func, text, distinct
from sqlalchemy.orm import undefer
from typing import List
from datetime import datetime

from models.main import db, User, PrescriptionAgg
from models.prescription import (
    Segment,
    MeasureUnit,
    MeasureUnitConvert,
    Outlier,
    Drug,
    DrugAttributes,
    Substance,
)
from models.enums import RoleEnum, DrugAdminSegment, DrugAttributesAuditTypeEnum
from services.admin import admin_ai_service
from services import drug_service as main_drug_service
from decorators.has_permission_decorator import has_permission, Permission
from utils import status
from exception.validation_error import ValidationError


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
):
    SegmentOutlier = db.aliased(Segment)
    ConversionsAgg = db.aliased(MeasureUnitConvert)
    MeasureUnitAgg = db.aliased(MeasureUnit)

    presc_query = (
        db.session.query(
            Outlier.idDrug.label("idDrug"), Outlier.idSegment.label("idSegment")
        )
        .group_by(Outlier.idDrug, Outlier.idSegment)
        .subquery()
    )

    conversions_query = (
        db.session.query(
            PrescriptionAgg.idDrug.label("idDrug"),
            PrescriptionAgg.idSegment.label("idSegment"),
        )
        .select_from(PrescriptionAgg)
        .join(
            MeasureUnitAgg,
            PrescriptionAgg.idMeasureUnit == MeasureUnitAgg.id,
        )
        .outerjoin(
            ConversionsAgg,
            and_(
                ConversionsAgg.idSegment == PrescriptionAgg.idSegment,
                ConversionsAgg.idDrug == PrescriptionAgg.idDrug,
                ConversionsAgg.idMeasureUnit == PrescriptionAgg.idMeasureUnit,
            ),
        )
        .filter(PrescriptionAgg.idSegment != None)
        .filter(PrescriptionAgg.idMeasureUnit != None)
        .filter(ConversionsAgg.factor == None)
        .group_by(PrescriptionAgg.idDrug, PrescriptionAgg.idSegment)
        .subquery()
    )

    q = (
        db.session.query(
            Drug.id,
            Drug.name,
            Segment.id,
            Segment.description,
            DrugAttributes.idMeasureUnit,
            DrugAttributes.idMeasureUnitPrice,
            DrugAttributes.price,
            Drug.sctid,
            MeasureUnitConvert.factor,
            func.count().over(),
            Substance.name,
            SegmentOutlier.description,
            Drug.ai_accuracy,
            DrugAttributes.maxDose,
            DrugAttributes.useWeight,
            MeasureUnit.description.label("measure_unit_default_name"),
        )
        .select_from(presc_query)
        .join(Drug, presc_query.c.idDrug == Drug.id)
        .outerjoin(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == Drug.id,
                DrugAttributes.idSegment == presc_query.c.idSegment,
            ),
        )
        .outerjoin(MeasureUnit, MeasureUnit.id == DrugAttributes.idMeasureUnit)
        .outerjoin(Segment, Segment.id == DrugAttributes.idSegment)
        .outerjoin(
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == Segment.id,
                MeasureUnitConvert.idDrug == Drug.id,
                MeasureUnitConvert.idMeasureUnit == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .outerjoin(SegmentOutlier, SegmentOutlier.id == presc_query.c.idSegment)
    )

    if has_missing_conversion:
        q = q.outerjoin(
            conversions_query,
            and_(
                conversions_query.c.idDrug == presc_query.c.idDrug,
                conversions_query.c.idSegment == presc_query.c.idSegment,
            ),
        ).filter(conversions_query.c.idDrug != None)

    if has_substance != None:
        if has_substance:
            q = q.filter(Substance.id != None)
        else:
            q = q.filter(Substance.id == None)

    if has_default_unit != None:
        if has_default_unit:
            q = q.filter(DrugAttributes.idMeasureUnit != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnit == None)

    if has_price_unit != None:
        if has_price_unit:
            q = q.filter(DrugAttributes.idMeasureUnitPrice != None)
        else:
            q = q.filter(DrugAttributes.idMeasureUnitPrice == None)

    if has_price_conversion != None:
        if has_price_conversion:
            q = q.filter(
                or_(
                    MeasureUnitConvert.factor != None,
                    DrugAttributes.idMeasureUnitPrice == DrugAttributes.idMeasureUnit,
                )
            )
        else:
            q = q.filter(
                and_(
                    MeasureUnitConvert.factor == None,
                    func.coalesce(DrugAttributes.idMeasureUnitPrice, "")
                    != func.coalesce(DrugAttributes.idMeasureUnit, ""),
                    DrugAttributes.idMeasureUnitPrice != None,
                )
            )

    if has_inconsistency != None:
        if has_inconsistency:
            q = q.filter(DrugAttributes.idDrug == None)
        else:
            q = q.filter(DrugAttributes.idDrug != None)

    if has_ai_substance != None:
        if has_ai_substance:
            q = q.filter(Drug.ai_accuracy != None)

            if ai_accuracy_range != None and len(ai_accuracy_range) == 2:
                q = q.filter(Drug.ai_accuracy >= ai_accuracy_range[0]).filter(
                    Drug.ai_accuracy <= ai_accuracy_range[1]
                )
        else:
            q = q.filter(Drug.ai_accuracy == None)

    if has_max_dose != None:
        if has_max_dose:
            q = q.filter(DrugAttributes.maxDose != None)
        else:
            q = q.filter(DrugAttributes.maxDose == None)

    if len(attribute_list) > 0:
        bool_attributes = [
            ["mav", DrugAttributes.mav],
            ["idoso", DrugAttributes.elderly],
            ["controlados", DrugAttributes.controlled],
            ["antimicro", DrugAttributes.antimicro],
            ["quimio", DrugAttributes.chemo],
            ["sonda", DrugAttributes.tube],
            ["naopadronizado", DrugAttributes.notdefault],
            ["linhabranca", DrugAttributes.whiteList],
            ["dialisavel", DrugAttributes.dialyzable],
            ["renal", DrugAttributes.kidney],
            ["hepatico", DrugAttributes.liver],
            ["plaquetas", DrugAttributes.platelets],
            ["dosemaxima", DrugAttributes.maxDose],
            ["risco_queda", DrugAttributes.fallRisk],
            ["lactante", DrugAttributes.lactating],
            ["gestante", DrugAttributes.pregnant],
            ["jejum", DrugAttributes.fasting],
        ]

        for a in bool_attributes:
            if a[0] in attribute_list:
                if str(a[1].type) == "BOOLEAN":
                    q = q.filter(a[1] == True)
                else:
                    q = q.filter(a[1] != None)

    if term:
        q = q.filter(Drug.name.ilike(term))

    if substance:
        q = q.filter(Substance.name.ilike(substance))

    if id_segment_list and len(id_segment_list) > 0:
        q = q.filter(DrugAttributes.idSegment.in_(id_segment_list))

    return q.order_by(Drug.name, Segment.description).limit(limit).offset(offset).all()


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
            id_drug=d[0], sctid=d[1], user=user_context, overwrite=False
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
    if (
        from_admin_schema
        and id_segment_origin != DrugAdminSegment.ADULT.value
        and id_segment_origin != DrugAdminSegment.KIDS.value
    ):
        raise ValidationError(
            "Segmento origem inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if not from_admin_schema and id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Segmento origem igual ao segmento destino",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        overwrite_all
        and Permission.ADMIN_DRUGS__OVERWRITE_ATTRIBUTES in user_permissions
    ):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    origin_schema = "hsc_test" if from_admin_schema else user_context.schema
    schema = user_context.schema

    only_support_filter = """
        and (
            ma.update_by = 0
            or ma.update_by is null
            or u.config::text like :supportRole
        )
    """

    base_attributes = [
        "renal",
        "hepatico",
        "plaquetas",
        "mav",
        "idoso",
        "controlados",
        "antimicro",
        "quimio",
        "sonda",
        "naopadronizado",
        "linhabranca",
        "dosemaxima",
        "risco_queda",
        "dialisavel",
        "lactante",
        "gestante",
        "fkunidademedidacusto",
        "custo",
        "jejum",
    ]
    set_attributes = []
    for a in attributes:
        if a in base_attributes:
            set_attributes.append(f"{a} = destino.{a},")

    query = f"""
        with modelo as (
            select
                m.sctid,
                ma.renal,
                ma.hepatico,
                ma.plaquetas,
                ma.dosemaxima,
                ma.risco_queda,
                ma.lactante,
                ma.gestante,
                coalesce(ma.mav, false) as mav,
                coalesce(ma.idoso, false) as idoso,
                coalesce(ma.controlados, false) as controlados,
                coalesce(ma.antimicro, false) as antimicro,
                coalesce(ma.quimio, false) as quimio,
                coalesce(ma.sonda, false) as sonda,
                coalesce(ma.naopadronizado, false) as naopadronizado,
                coalesce(ma.linhabranca, false) as linhabranca,
                coalesce(ma.dialisavel, false) as dialisavel,
                coalesce(ma.jejum, false) as jejum,
                ma.fkunidademedidacusto,
                ma.custo
            from
                {origin_schema}.medatributos ma
                inner join {origin_schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
                inner join public.substancia s on (m.sctid = s.sctid)
            where 
                ma.idsegmento = :idSegmentOrigin
        ),
        destino as (
            select 
                ma.fkmedicamento, ma.idsegmento, mo.*
            from
                {schema}.medatributos ma
                inner join {schema}.medicamento m on (ma.fkmedicamento = m.fkmedicamento)
                inner join public.substancia s on (m.sctid = s.sctid)
                inner join modelo mo on (s.sctid = mo.sctid)
                left join public.usuario u on (ma.update_by = u.idusuario)
            where 
                ma.idsegmento = :idSegmentDestiny
                {only_support_filter if not overwrite_all else ''}
        )
    """

    audit_stmt = text(
        f"""
        {query}
        insert into 
            {schema}.medatributos_audit 
            (tp_audit, fkmedicamento, idsegmento, extra, created_at, created_by)
        select 
            {DrugAttributesAuditTypeEnum.COPY_FROM_REFERENCE.value}, d.fkmedicamento, d.idsegmento, :extra, now(), :idUser
        from
	        destino d
    """
    )

    db.session.execute(
        audit_stmt,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "supportRole": f"%{RoleEnum.SUPPORT.value}%",
            "idUser": user_context.id,
            "extra": '{"attributes": "' + ",".join(attributes) + '"}',
        },
    )

    update_stmt = text(
        f"""
        {query}
        update 
            {schema}.medatributos origem
        set 
            {''.join(set_attributes)}
            update_at = now(),
            update_by = :idUser
        from 
            destino
        where 
            origem.fkmedicamento = destino.fkmedicamento
            and origem.idsegmento = destino.idsegmento
    """
    )

    return db.session.execute(
        update_stmt,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "supportRole": f"%{RoleEnum.SUPPORT.value}%",
            "idUser": user_context.id,
        },
    )


@has_permission(Permission.ADMIN_DRUGS)
def predict_substance(id_drugs: List[int], user_context: User):
    roles = (
        user_context.config["roles"]
        if user_context.config and "roles" in user_context.config
        else []
    )
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

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
            i["idDrug"], i["sctid"], user_context
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
