"""Service: admin drug related operations"""

from sqlalchemy import and_, text
from sqlalchemy.orm import undefer

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import Drug, DrugAttributes, Outlier, Substance, User, db
from services import drug_service as main_drug_service
from utils import status


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
        db.session.query(Outlier.idDrug, Drug.sctid)
        .select_from(Outlier)
        .distinct()
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
