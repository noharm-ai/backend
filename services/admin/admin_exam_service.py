from utils import status
from sqlalchemy import desc
from datetime import datetime
from markupsafe import escape as escape_html

from models.main import *
from models.appendix import *
from models.segment import *
from services.admin import admin_integration_service
from services import data_authorization_service
from decorators.has_permission_decorator import has_permission, Permission

from exception.validation_error import ValidationError


@has_permission(Permission.ADMIN_EXAMS)
def get_segment_exams(id_segment: int):
    segExams = (
        db.session.query(SegmentExam, Segment)
        .filter(SegmentExam.idSegment == id_segment)
        .join(Segment, Segment.id == SegmentExam.idSegment)
        .order_by(asc(SegmentExam.name))
        .all()
    )

    exams = []
    for e in segExams:
        se: SegmentExam = e[0]
        s: Segment = e[1]

        exams.append(
            {
                "idSegment": s.id,
                "segment": s.description,
                "type": se.typeExam.lower(),
                "initials": se.initials,
                "name": se.name,
                "min": se.min,
                "max": se.max,
                "ref": se.ref,
                "order": se.order,
                "active": se.active,
            }
        )

    return exams


@has_permission(Permission.ADMIN_EXAMS__COPY)
def copy_exams(id_segment_origin, id_segment_destiny, user_context: User):
    if id_segment_origin == None:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    if id_segment_origin == id_segment_destiny:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.unauthorizedUser",
            status.HTTP_400_BAD_REQUEST,
        )

    query = text(
        f"""
            insert into {user_context.schema}.segmentoexame 
            (idsegmento, tpexame, abrev, nome, min, max, referencia, posicao, ativo, update_at, update_by)
            select
                :idSegmentDestiny,
                tpexame, 
                abrev, 
                nome, 
                min, 
                max, 
                referencia, 
                posicao, 
                ativo, 
                now(), 
                :idUser
            from
                {user_context.schema}.segmentoexame 
            where
                idsegmento = :idSegmentOrigin
            on conflict (idsegmento, tpexame)
            do nothing
        """
    )

    return db.session.execute(
        query,
        {
            "idSegmentOrigin": id_segment_origin,
            "idSegmentDestiny": id_segment_destiny,
            "idUser": user_context.id,
        },
    )


@has_permission(Permission.ADMIN_EXAMS__MOST_FREQUENT)
def get_most_frequent(user_context: User):
    if (
        admin_integration_service.get_table_count(user_context.schema, "exame")
        > 1000000
    ):
        raise ValidationError(
            "A tabela é grande demais para ser consultada",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    q = (
        db.session.query(
            Exams.typeExam,
            func.count().label("total"),
            func.min(Exams.value),
            func.max(Exams.value),
        )
        .group_by(Exams.typeExam)
        .order_by(desc("total"))
    )

    result = q.all()

    exams = []

    for e in result:
        exams.append({"type": e[0], "count": e[1], "min": e[2], "max": e[3]})

    return exams


@has_permission(Permission.ADMIN_EXAMS__MOST_FREQUENT)
def add_most_frequent(exam_types, id_segment, user_context: User):

    exams_result = (
        db.session.query(SegmentExam)
        .filter(SegmentExam.idSegment == id_segment)
        .filter(SegmentExam.typeExam.in_([e.lower() for e in exam_types]))
        .all()
    )
    registered_exams = []
    for e in exams_result:
        registered_exams.append(e.typeExam)

    for e in exam_types:
        if e.lower() not in registered_exams:
            se = SegmentExam()
            se.typeExam = e.lower()
            se.idSegment = id_segment
            se.name = e
            se.user = user_context.id
            se.active = False
            se.update = datetime.today()
            se.order = 99

            db.session.add(se)


@has_permission(Permission.ADMIN_EXAMS)
def get_exam_types():
    typesExam = (
        db.session.query(Exams.typeExam)
        .filter(Exams.date > (date.today() - timedelta(days=30)))
        .group_by(Exams.typeExam)
        .order_by(asc(Exams.typeExam))
        .all()
    )

    results = ["mdrd", "ckd", "ckd21", "cg", "swrtz2", "swrtz1"]
    for t in typesExam:
        results.append(t[0].lower())

    return results


@has_permission(Permission.ADMIN_EXAMS)
def upsert_seg_exam(data: dict, user_context: User):
    id_segment = data.get("idSegment", None)
    typeExam = data.get("type", None)

    if id_segment == None or typeExam == None:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    typeExam = escape_html(typeExam)

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    segExam = (
        db.session.query(SegmentExam)
        .filter(SegmentExam.idSegment == id_segment)
        .filter(SegmentExam.typeExam == typeExam)
        .first()
    )

    if data.get("new", False) == True and segExam != None:
        raise ValidationError(
            "Este exame já foi cadastrado",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    newSegExam = False
    if segExam is None:
        newSegExam = True
        segExam = SegmentExam()
        segExam.idSegment = id_segment
        segExam.typeExam = typeExam

    if data.get("initials", None) != None:
        segExam.initials = escape_html(data.get("initials", None))
    if data.get("name", None) != None:
        segExam.name = escape_html(data.get("name", None))
    if data.get("min", None) != None:
        segExam.min = escape_html(data.get("min", None))
    if data.get("max", None) != None:
        segExam.max = escape_html(data.get("max", None))
    if data.get("ref", None) != None:
        segExam.ref = escape_html(data.get("ref", None))
    if "active" in data.keys():
        segExam.active = bool(data.get("active", False))

    segExam.update = datetime.today()
    segExam.user = user_context.id

    if newSegExam:
        db.session.add(segExam)

    segment = db.session.query(Segment).filter(Segment.id == id_segment).first()

    return {
        "idSegment": segment.id,
        "segment": segment.description,
        "type": segExam.typeExam.lower(),
        "initials": segExam.initials,
        "name": segExam.name,
        "min": segExam.min,
        "max": segExam.max,
        "ref": segExam.ref,
        "order": segExam.order,
        "active": segExam.active,
    }


@has_permission(Permission.ADMIN_EXAMS)
def set_exams_order(exams, id_segment, user_context: User):
    if not exams or not id_segment:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user_context
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )

    db.session.query(SegmentExam).filter(SegmentExam.idSegment == id_segment).update(
        {"order": 99}, synchronize_session="fetch"
    )

    for idx, type in enumerate(exams):
        exam = (
            db.session.query(SegmentExam)
            .filter(SegmentExam.idSegment == id_segment)
            .filter(SegmentExam.typeExam == type)
            .first()
        )

        if exam:
            exam.order = idx
            db.session.flush()
