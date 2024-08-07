from sqlalchemy import literal

from models.main import db
from models.appendix import *
from models.prescription import *
from models.enums import RoleEnum
from services import (
    prescription_service,
    permission_service,
    data_authorization_service,
)
from exception.validation_error import ValidationError


def getPrescriptionDrug(idPrescriptionDrug):
    return (
        db.session.query(
            PrescriptionDrug,
            Drug,
            MeasureUnit,
            Frequency,
            literal("0"),
            func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4).label(
                "score"
            ),
            DrugAttributes,
            Notes.notes,
            Prescription.status,
            Prescription.expire,
        )
        .outerjoin(Outlier, Outlier.id == PrescriptionDrug.idOutlier)
        .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)
        .outerjoin(Notes, Notes.idPrescriptionDrug == PrescriptionDrug.id)
        .outerjoin(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .outerjoin(
            MeasureUnit,
            and_(
                MeasureUnit.id == PrescriptionDrug.idMeasureUnit,
                MeasureUnit.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(
            Frequency,
            and_(
                Frequency.id == PrescriptionDrug.idFrequency,
                Frequency.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                DrugAttributes.idSegment == PrescriptionDrug.idSegment,
            ),
        )
        .filter(PrescriptionDrug.id == idPrescriptionDrug)
        .first()
    )


def count_drugs_by_prescription(
    prescription: Prescription, drug_types, user: User, parent_agg_date=None
):
    if prescription.agg:
        prescription_query = prescription_service.get_query_prescriptions_by_agg(
            agg_prescription=prescription, is_cpoe=user.cpoe(), only_id=True
        )

        q = (
            db.session.query(PrescriptionDrug)
            .filter(PrescriptionDrug.idPrescription.in_(prescription_query))
            .filter(PrescriptionDrug.source.in_(drug_types))
        )

        if user.cpoe():
            q = q.filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate)
                    >= func.date(prescription.date),
                )
            )

        return q.count()
    else:
        q = (
            db.session.query(PrescriptionDrug)
            .filter(PrescriptionDrug.idPrescription == prescription.id)
            .filter(PrescriptionDrug.source.in_(drug_types))
        )

        if user.cpoe():
            q = q.filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate)
                    >= func.date(parent_agg_date),
                )
            )

        return q.count()


def update_pd_form(pd_list, user):
    if not permission_service.is_pharma(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if not permission_service.has_role(user, RoleEnum.PRESMED_FORM.value):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    for pd in pd_list:
        drug = drug = (
            db.session.query(PrescriptionDrug).filter(PrescriptionDrug.id == pd).first()
        )
        if drug is None:
            raise ValidationError(
                "Prescrição inexistente",
                "errors.invalidRegister",
                status.HTTP_400_BAD_REQUEST,
            )

        if not data_authorization_service.has_segment_authorization(
            id_segment=drug.idSegment, user=user
        ):
            raise ValidationError(
                "Usuário não autorizado neste segmento",
                "errors.businessRules",
                status.HTTP_401_UNAUTHORIZED,
            )

        drug.form = pd_list[pd]
        drug.update = datetime.today()
        drug.user = user.id

        db.session.flush()


def prescriptionDrugToDTO(pd):
    pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False

    return {
        "idPrescription": str(pd[0].idPrescription),
        "idPrescriptionDrug": str(pd[0].id),
        "idDrug": pd[0].idDrug,
        "drug": pd[1].name if pd[1] is not None else "Medicamento " + str(pd[0].idDrug),
        "dose": pd[0].dose,
        "measureUnit": {"value": pd[2].id, "label": pd[2].description} if pd[2] else "",
        "frequency": {"value": pd[3].id, "label": pd[3].description} if pd[3] else "",
        "dayFrequency": pd[0].frequency,
        "doseconv": pd[0].doseconv,
        "time": timeValue(pd[0].interval),
        "interval": pd[0].interval,
        "route": pd[0].route,
        "score": str(pd[5]) if not pdWhiteList and pd[0].source != "Dietas" else "0",
        "np": pd[6].notdefault if pd[6] is not None else False,
        "am": pd[6].antimicro if pd[6] is not None else False,
        "av": pd[6].mav if pd[6] is not None else False,
        "c": pd[6].controlled if pd[6] is not None else False,
        "q": pd[6].chemo if pd[6] is not None else False,
        "alergy": bool(pd[0].allergy == "S"),
        "allergy": bool(pd[0].allergy == "S"),
        "whiteList": pdWhiteList,
        "recommendation": pd[0].notes,
    }
