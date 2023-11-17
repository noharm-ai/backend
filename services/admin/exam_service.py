from flask_api import status
from sqlalchemy import desc

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum
from services.admin import integration_service

from exception.validation_error import ValidationError


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

    if integration_service.get_table_count(user.schema, "exame") > 500000:
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

            db.session.add(se)
