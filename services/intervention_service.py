from models.main import db
from sqlalchemy import case, and_

from models.appendix import *
from models.prescription import *
from routes.utils import validate
from services import memory_service

from exception.validation_error import ValidationError


def get_interventions(
    admissionNumber=None,
    startDate=None,
    endDate=None,
    idSegment=None,
    idPrescription=None,
    idPrescriptionDrug=None,
    idIntervention=None,
    idDrug=None,
):
    mReasion = db.aliased(InterventionReason)
    descript = case(
        [
            (
                mReasion.description != None,
                func.concat(
                    mReasion.description, " - ", InterventionReason.description
                ),
            ),
        ],
        else_=InterventionReason.description,
    )

    reason = (
        db.session.query(descript)
        .select_from(InterventionReason)
        .outerjoin(mReasion, mReasion.id == InterventionReason.mamy)
        .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))
        .as_scalar()
    )

    splitStr = "!?"
    dr1 = db.aliased(Drug)
    interactions = (
        db.session.query(func.concat(dr1.name, splitStr, dr1.id))
        .select_from(dr1)
        .filter(dr1.id == func.any(Intervention.interactions))
        .as_scalar()
    )

    PrescriptionB = db.aliased(Prescription)
    DepartmentB = db.aliased(Department)
    interventions = (
        db.session.query(
            Intervention,
            PrescriptionDrug,
            func.array(reason).label("reason"),
            case(
                [
                    (
                        PrescriptionB.concilia != None,
                        func.coalesce(PrescriptionDrug.interval, Drug.name),
                    )
                ],
                else_=Drug.name,
            ),
            func.array(interactions).label("interactions"),
            MeasureUnit,
            Frequency,
            Prescription,
            User.name,
            Department.name,
            PrescriptionB.prescriber,
            DepartmentB.name,
        )
        .outerjoin(PrescriptionDrug, Intervention.id == PrescriptionDrug.id)
        .outerjoin(Prescription, Intervention.idPrescription == Prescription.id)
        .outerjoin(PrescriptionB, PrescriptionDrug.idPrescription == PrescriptionB.id)
        .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)
        .outerjoin(
            MeasureUnit,
            and_(
                MeasureUnit.id == PrescriptionDrug.idMeasureUnit,
                MeasureUnit.idHospital == PrescriptionB.idHospital,
            ),
        )
        .outerjoin(
            Frequency,
            and_(
                Frequency.id == PrescriptionDrug.idFrequency,
                Frequency.idHospital == PrescriptionB.idHospital,
            ),
        )
        .outerjoin(User, User.id == Intervention.user)
        .outerjoin(
            Department,
            and_(
                Department.id == PrescriptionB.idDepartment,
                Department.idHospital == PrescriptionB.idHospital,
            ),
        )
        .outerjoin(
            DepartmentB,
            and_(
                DepartmentB.id == Prescription.idDepartment,
                DepartmentB.idHospital == Prescription.idHospital,
            ),
        )
    )

    if admissionNumber:
        interventions = interventions.filter(
            Intervention.admissionNumber == admissionNumber
        )

    if not startDate and admissionNumber == None:
        raise ValidationError(
            "Data inicial inválida",
            "errors.invalidRequest",
            status.HTTP_400_BAD_REQUEST,
        )

    if startDate is not None:
        interventions = interventions.filter(Intervention.date >= validate(startDate))

    if endDate is not None:
        interventions = interventions.filter(
            Intervention.date <= (validate(endDate) + timedelta(hours=23, minutes=59))
        )

    if idSegment is not None:
        interventions = interventions.filter(
            or_(
                PrescriptionB.idSegment == idSegment,
                Prescription.idSegment == idSegment,
            )
        )

    if idDrug is not None and len(idDrug) > 0:
        interventions = interventions.filter(PrescriptionDrug.idDrug.in_(idDrug))

    if idPrescription is not None:
        interventions = interventions.filter(
            Intervention.idPrescription == idPrescription
        )

    if idPrescriptionDrug is not None:
        interventions = interventions.filter(Intervention.id == idPrescriptionDrug)

    if idIntervention is not None:
        interventions = interventions.filter(
            Intervention.idIntervention == idIntervention
        )

    if not idIntervention:
        interventions = interventions.filter(
            Intervention.status.in_(["s", "a", "n", "x", "j"])
        )

    interventions = interventions.order_by(desc(Intervention.date)).limit(1500).all()

    intervBuffer = []
    for i in interventions:
        intervBuffer.append(
            {
                "id": str(i[0].id),
                "idIntervention": str(i[0].idIntervention),
                "idSegment": (
                    i[1].idSegment if i[1] else i[7].idSegment if i[7] else None
                ),
                "idInterventionReason": i[0].idInterventionReason,
                "reasonDescription": (", ").join(i[2]),
                "idPrescription": str(
                    i[1].idPrescription if i[1] else i[0].idPrescription
                ),
                "idDrug": i[1].idDrug if i[1] else None,
                "drugName": (
                    i[3]
                    if i[3] is not None
                    else (
                        "Medicamento " + str(i[1].idDrug)
                        if i[1]
                        else "Intervenção no Paciente"
                    )
                ),
                "dose": i[1].dose if i[1] else None,
                "measureUnit": (
                    {"value": i[5].id, "label": i[5].description} if i[5] else ""
                ),
                "frequency": (
                    {"value": i[6].id, "label": i[6].description} if i[6] else ""
                ),
                "time": timeValue(i[1].interval) if i[1] else None,
                "route": i[1].route if i[1] else "None",
                "admissionNumber": i[0].admissionNumber,
                "observation": i[0].notes,
                "error": i[0].error,
                "cost": i[0].cost,
                "interactionsDescription": (", ").join(
                    [d.split(splitStr)[0] for d in i[4]]
                ),
                "interactionsList": interactionsList(i[4], splitStr),
                "interactions": i[0].interactions,
                "date": i[0].date.isoformat(),
                "user": i[8],
                "department": i[9] if i[9] else i[11],
                "prescriber": i[10] if i[10] else i[7].prescriber if i[7] else None,
                "status": i[0].status,
                "transcription": i[0].transcription,
                "economyDays": i[0].economy_days,
                "expendedDose": i[0].expended_dose,
            }
        )

    result = [i for i in intervBuffer if i["status"] == "s"]
    result.extend([i for i in intervBuffer if i["status"] != "s"])

    return result


def save_intervention(
    id_intervention=None,
    id_prescription=0,
    id_prescription_drug=0,
    user=None,
    admission_number=None,
    id_intervention_reason=None,
    error=None,
    cost=None,
    observation=None,
    interactions=None,
    transcription=None,
    economy_days=None,
    expended_dose=None,
    new_status="s",
):
    if id_intervention == None and id_intervention_reason == None:
        # transition between versions
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParameter",
            status.HTTP_400_BAD_REQUEST,
        )

    if not user:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParameter",
            status.HTTP_400_BAD_REQUEST,
        )

    if id_prescription_drug != "0":
        id_prescription = 0

    if id_prescription == 0 and id_prescription_drug == 0:
        raise ValidationError(
            "Parâmetros inválidos",
            "errors.invalidParameter",
            status.HTTP_400_BAD_REQUEST,
        )

    new_intv = False
    i = None

    if id_intervention:
        i = Intervention.query.get(id_intervention)
        if not i:
            raise ValidationError(
                "Registro inválido",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        if i.status in ["a", "n", "x", "j"] and new_status != "s":
            raise ValidationError(
                "Intervenção com desfecho não pode ser alterada",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

    if not i:
        new_intv = True
        i = Intervention()
        i.id = id_prescription_drug
        i.idPrescription = id_prescription
        i.date = datetime.today()
        i.update = datetime.today()
        i.user = user.id

    if admission_number:
        i.admissionNumber = admission_number
    if id_intervention_reason:
        i.idInterventionReason = id_intervention_reason
    if error is not None:
        i.error = error
    if cost is not None:
        i.cost = cost
    if observation:
        i.notes = observation
    if interactions:
        i.interactions = interactions
    if transcription:
        i.transcription = transcription
    if economy_days != -1:
        i.economy_days = economy_days
    if expended_dose != -1:
        i.expended_dose = expended_dose

    if i.admissionNumber != None and i.idDepartment == None:
        currentDepartment = (
            db.session.query(Prescription.idDepartment)
            .filter(Prescription.admissionNumber == i.admissionNumber)
            .order_by(desc(Prescription.date))
            .first()
        )

        if currentDepartment != None:
            i.idDepartment = currentDepartment[0]

    if new_status != i.status:
        if i.status == "0":
            i.date = datetime.today()
            i.user = user.id

        i.status = new_status
    else:
        i.user = user.id

        if memory_service.has_feature("PRIMARYCARE"):
            i.date = datetime.today()

    i.update = datetime.today()

    if new_intv:
        db.session.add(i)
        db.session.flush()

    # TODO: is it really necessary?
    if id_prescription_drug:
        pd = PrescriptionDrug.query.get(id_prescription_drug)
        if pd is not None:
            pd.status = i.status
            pd.update = datetime.today()
            pd.user = user.id

    return get_interventions(
        admissionNumber=i.admissionNumber, idIntervention=i.idIntervention
    )


def get_outcome_data(id_intervention, user):
    intervention = (
        db.session.query(Intervention)
        .filter(Intervention.idIntervention == id_intervention)
        .first()
    )

    PrescriptionDrugConvert = db.aliased(MeasureUnitConvert)
    PrescriptionDrugPriceConvert = db.aliased(MeasureUnitConvert)

    if not intervention:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    base_query = (
        db.session.query(
            PrescriptionDrug,
            Drug,
            DrugAttributes,
            PrescriptionDrugConvert,
            PrescriptionDrugPriceConvert,
            Prescription,
        )
        .join(Drug, PrescriptionDrug.idDrug == Drug.id)
        .join(Prescription, PrescriptionDrug.idPrescription == Prescription.id)
        .outerjoin(
            DrugAttributes,
            and_(
                PrescriptionDrug.idDrug == DrugAttributes.idDrug,
                PrescriptionDrug.idSegment == DrugAttributes.idSegment,
            ),
        )
        .outerjoin(
            PrescriptionDrugConvert,
            and_(
                PrescriptionDrugConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugConvert.idSegment == PrescriptionDrug.idSegment,
                PrescriptionDrugConvert.idMeasureUnit == PrescriptionDrug.idMeasureUnit,
            ),
        )
        .outerjoin(
            PrescriptionDrugPriceConvert,
            and_(
                PrescriptionDrugPriceConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugPriceConvert.idSegment == PrescriptionDrug.idSegment,
                PrescriptionDrugPriceConvert.idMeasureUnit
                == DrugAttributes.idMeasureUnitPrice,
            ),
        )
    )

    origin_query = base_query.filter(PrescriptionDrug.id == intervention.id)
    origin = _outcome_calc(origin_query.all())

    destiny_drug = origin[0]["item"]["idDrug"]
    if intervention.interactions != None and len(intervention.interactions) > 0:
        destiny_drug = intervention.interactions[0]

    destiny_query = (
        base_query.filter(Prescription.admissionNumber == intervention.admissionNumber)
        .filter(PrescriptionDrug.idDrug == destiny_drug)
        .filter(Prescription.date > origin[0]["item"]["prescriptionDate"])
        .filter(PrescriptionDrug.suspendedDate == None)
        .order_by(Prescription.date)
        .limit(10)
    )

    destiny = _outcome_calc(destiny_query.all())

    return {
        "idIntervention": id_intervention,
        "date": intervention.date.isoformat(),
        "origin": origin[0],
        "destiny": destiny,
    }


def _outcome_calc(list):
    results = []

    for item in list:
        origin_price = None
        dose = None
        errors = {
            "origin_price_error": False,
            "origin_price_conversion_error": False,
            "origin_dose_conversion_error": False,
        }

        prescription_drug = item[0]
        drug = item[1]
        drug_attr = item[2]
        dose_convert = item[3]
        price_dose_convert = item[4]
        prescription = item[5]

        if drug_attr.price != None and drug_attr.idMeasureUnitPrice != None:
            if drug_attr.idMeasureUnitPrice == drug_attr.idMeasureUnit:
                origin_price = drug_attr.price
            elif price_dose_convert != None and price_dose_convert.factor != None:
                origin_price = drug_attr.price / price_dose_convert.factor
            else:
                errors["origin_price_conversion_error"] = True
        else:
            errors["origin_price_error"] = True

        if drug_attr.useWeight:
            if dose_convert != None and dose_convert.factor != None:
                dose = prescription_drug.dose * dose_convert.factor
            else:
                errors["origin_dose_conversion_error"] = True
        else:
            dose = prescription_drug.doseconv

        results.append(
            {
                "errors": errors,
                "item": {
                    "idPrescription": str(prescription.id),
                    "prescriptionDate": prescription.date.isoformat(),
                    "idDrug": drug.id,
                    "name": drug.name,
                    "price": origin_price,
                    "dose": dose,
                    "idMeasureUnit": drug_attr.idMeasureUnit,
                    "idFrequency": prescription_drug.idFrequency,
                    "frequencyDay": prescription_drug.frequency,
                    "pricePerDose": none2zero(origin_price) * none2zero(dose),
                    "priceKit": 0,
                    "beforeConversion": {
                        "price": drug_attr.price,
                        "idMeasureUnitPrice": drug_attr.idMeasureUnitPrice,
                        "dose": prescription_drug.dose,
                        "idMeasureUnit": prescription_drug.idMeasureUnit,
                    },
                    "conversion": {
                        "doseFactor": (
                            dose_convert.factor if dose_convert != None else None
                        ),
                        "priceFactor": (
                            price_dose_convert.factor
                            if price_dose_convert != None
                            else None
                        ),
                    },
                },
            }
        )

    return results
