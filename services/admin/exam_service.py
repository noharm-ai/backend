from utils import status
from sqlalchemy import desc
from datetime import datetime

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum
from services.admin import integration_service
from services import data_authorization_service

from exception.validation_error import ValidationError


def get_segment_exams(id_segment: int, user: User):
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


def copy_exams(id_segment_origin, id_segment_destiny, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

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
            insert into {user.schema}.segmentoexame 
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
                {user.schema}.segmentoexame 
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
            "idUser": user.id,
        },
    )


def get_most_frequent(user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if integration_service.get_table_count(user.schema, "exame") > 1000000:
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


def add_most_frequent(user, exam_types, id_segment):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if RoleEnum.ADMIN.value not in roles and RoleEnum.TRAINING.value not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

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
            se.user = user.id
            se.active = False
            se.update = datetime.today()
            se.order = 99

            db.session.add(se)


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


def upsert_seg_exam(data: dict, user: User):
    id_segment = data.get("idSegment", None)
    typeExam = data.get("type", None)

    if id_segment == None or typeExam == None:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
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

    if "initials" in data.keys():
        segExam.initials = data.get("initials", None)
    if "name" in data.keys():
        segExam.name = data.get("name", None)
    if "min" in data.keys():
        segExam.min = data.get("min", None)
    if "max" in data.keys():
        segExam.max = data.get("max", None)
    if "ref" in data.keys():
        segExam.ref = data.get("ref", None)
    if "order" in data.keys():
        segExam.order = data.get("order", None)
    if "active" in data.keys():
        segExam.active = bool(data.get("active", False))

    segExam.update = datetime.today()
    segExam.user = user.id

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


def set_exams_order(exams, id_segment, user: User):
    if not exams or not id_segment:
        raise ValidationError(
            "Parametros inválidos",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
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
