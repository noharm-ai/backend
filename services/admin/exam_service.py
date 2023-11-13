from flask_api import status

from models.main import *
from models.appendix import *
from models.segment import *
from models.enums import RoleEnum

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
