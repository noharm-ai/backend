from models.main import db

from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError


def getPrescriptionDrug(idPrescriptionDrug):
    return (
        db.session.query(
            PrescriptionDrug,
            Drug,
            MeasureUnit,
            Frequency,
            "0",
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


def has_unchecked_drugs(idPrescription):
    count = (
        db.session.query(PrescriptionDrug)
        .filter(PrescriptionDrug.idPrescription == idPrescription)
        .filter(
            or_(
                PrescriptionDrug.checked == False,
                PrescriptionDrug.checked == None,
                PrescriptionDrug.cpoe_group == None,
            )
        )
        .count()
    )

    return count > 0


def update_pd_form(pd_list, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "presmed-form" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    for pd in pd_list:
        drug = PrescriptionDrug.query.get(pd)
        if drug is None:
            raise ValidationError(
                "Prescrição inexistente",
                "errors.invalidRegister",
                status.HTTP_400_BAD_REQUEST,
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
