from models.main import db
from sqlalchemy import case, and_

from models.appendix import *
from models.prescription import *
from models.enums import (
    InterventionEconomyTypeEnum,
    InterventionStatusEnum,
    FeatureEnum,
)
from routes.utils import validate, gen_agg_id
from services import memory_service, permission_service

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


def set_intervention_outcome(
    user,
    id_intervention,
    outcome,
    economy_day_value,
    economy_day_value_manual,
    economy_day_amount,
    economy_day_amount_manual,
    origin_data,
    destiny_data,
    id_prescription_drug_destiny,
):
    if not permission_service.is_pharma(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    intervention = Intervention.query.get(id_intervention)
    if not intervention:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    if outcome not in ["a", "n", "x", "j", "s"]:
        raise ValidationError(
            "Desfecho inválido",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if economy_day_amount_manual and (
        economy_day_amount == None or economy_day_amount == 0
    ):
        raise ValidationError(
            "Quantidade de Dias de Economia deve ser especificado",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    intervention.update = datetime.today()
    intervention.user = user.id
    intervention.status = outcome

    if intervention.economy_type != None:
        # intervention v2
        if intervention.status != "s":
            intervention.idPrescriptionDrugDestiny = id_prescription_drug_destiny

            intervention.economy_day_value = economy_day_value
            intervention.economy_day_value_manual = economy_day_value_manual

            if economy_day_amount_manual:
                intervention.economy_days = economy_day_amount
                intervention.date_end_economy = (
                    intervention.date_base_economy
                    + timedelta(days=economy_day_amount - 1)
                )

            intervention.origin = origin_data
            intervention.destiny = destiny_data
        else:
            # cleanup
            intervention.idPrescriptionDrugDestiny = None
            intervention.economy_day_value = None
            intervention.economy_day_value_manual = False
            intervention.economy_days = None
            intervention.origin = None
            intervention.destiny = None
            intervention.date_end_economy = None


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
    agg_id_prescription=None,
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

    if not permission_service.is_pharma(user):
        raise ValidationError(
            "Permissão inválida",
            "errors.invalidPermission",
            status.HTTP_401_UNAUTHORIZED,
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

    if memory_service.has_feature(FeatureEnum.INTERVENTION_V2.value):
        economy_type = None
        reasons = (
            db.session.query(InterventionReason)
            .filter(InterventionReason.id.in_(i.idInterventionReason))
            .all()
        )
        for r in reasons:
            if r.suspension:
                economy_type = InterventionEconomyTypeEnum.SUSPENSION.value
            elif r.substitution:
                economy_type = InterventionEconomyTypeEnum.SUBSTITUTION.value

        i.economy_type = economy_type

        # date base economy
        if economy_type != None and i.date_base_economy == None:
            if permission_service.is_cpoe(user):
                if agg_id_prescription == None:
                    i.date_base_economy = i.date
                else:
                    presc = (
                        db.session.query(Prescription)
                        .filter(Prescription.id == agg_id_prescription)
                        .first()
                    )

                    if presc == None:
                        raise ValidationError(
                            "Registro inválido: data base economia",
                            "errors.businessRule",
                            status.HTTP_400_BAD_REQUEST,
                        )

                    i.date_base_economy = presc.date
            else:
                presc = (
                    db.session.query(PrescriptionDrug, Prescription)
                    .join(
                        Prescription, PrescriptionDrug.idPrescription == Prescription.id
                    )
                    .filter(PrescriptionDrug.id == id_prescription_drug)
                    .first()
                )

                if presc == None:
                    raise ValidationError(
                        "Registro inválido: data base economia",
                        "errors.invalidRecord",
                        status.HTTP_400_BAD_REQUEST,
                    )

                i.date_base_economy = presc[1].date

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
    i.economy_day_value_manual = False

    if new_intv:
        db.session.add(i)
        db.session.flush()

    return get_interventions(
        admissionNumber=i.admissionNumber, idIntervention=i.idIntervention
    )


def _get_outcome_data_query():
    PrescriptionDrugConvert = db.aliased(MeasureUnitConvert)
    PrescriptionDrugPriceConvert = db.aliased(MeasureUnitConvert)
    PrescriptionDrugFrequency = db.aliased(Frequency)
    DefaultMeasureUnit = db.aliased(MeasureUnit)

    return (
        db.session.query(
            PrescriptionDrug,
            Drug,
            DrugAttributes,
            PrescriptionDrugConvert,
            PrescriptionDrugPriceConvert,
            Prescription,
            DefaultMeasureUnit,
            PrescriptionDrugFrequency,
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
        .outerjoin(
            DefaultMeasureUnit,
            DrugAttributes.idMeasureUnit == DefaultMeasureUnit.id,
        )
        .outerjoin(
            PrescriptionDrugFrequency,
            PrescriptionDrug.idFrequency == PrescriptionDrugFrequency.id,
        )
    )


def get_outcome_data(id_intervention, user: User, edit=False):
    record = (
        db.session.query(Intervention, PrescriptionDrug)
        .outerjoin(PrescriptionDrug, PrescriptionDrug.id == Intervention.id)
        .filter(Intervention.idIntervention == id_intervention)
        .first()
    )

    if not record:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    intervention: Intervention = record[0]
    prescription_drug: PrescriptionDrug = record[1]
    readonly = intervention.status != InterventionStatusEnum.PENDING.value and not edit
    economy_type = intervention.economy_type

    if prescription_drug == None or economy_type == None:
        return {
            "idIntervention": id_intervention,
            "header": {
                "patient": prescription_drug == None,
                "status": intervention.status,
                "readonly": readonly,
                "date": intervention.date.isoformat(),
            },
        }

    # origin
    origin_query = _get_outcome_data_query().filter(
        PrescriptionDrug.id == intervention.id
    )
    base_origin = _outcome_calc(
        list=origin_query.all(),
        user=user,
        date_base_economy=(
            intervention.date_base_economy
            if intervention.date_base_economy != None
            else intervention.date
        ),
    )

    if not readonly or intervention.origin == None:
        origin = base_origin
    else:
        origin = [{"item": intervention.origin}]

    # destiny
    if economy_type == InterventionEconomyTypeEnum.SUBSTITUTION.value:
        destiny_id_drug = origin[0]["item"]["idDrug"]
        if intervention.interactions != None and len(intervention.interactions) > 0:
            destiny_id_drug = intervention.interactions[0]

        destiny_drug = db.session.query(Drug).filter(Drug.id == destiny_id_drug).first()

        destiny_query = (
            _get_outcome_data_query()
            .filter(Prescription.admissionNumber == intervention.admissionNumber)
            .filter(
                or_(
                    PrescriptionDrug.idDrug == destiny_id_drug,
                    Drug.sctid == destiny_drug.sctid,
                )
            )
            .filter(Prescription.date > origin[0]["item"]["prescriptionDate"])
            .filter(PrescriptionDrug.suspendedDate == None)
            .order_by(Prescription.date)
            .limit(10)
        )

        base_destiny = _outcome_calc(
            list=destiny_query.all(),
            user=user,
            date_base_economy=(
                intervention.date_base_economy
                if intervention.date_base_economy != None
                else intervention.date
            ),
        )

        if not readonly:
            destiny = base_destiny
        else:
            destiny = [{"item": intervention.destiny}]
    else:
        base_destiny = None
        destiny = None
        destiny_drug = None

    # calc
    economy_day_value = (
        intervention.economy_day_value
        if readonly
        else _calc_economy(
            origin=origin[0],
            destiny=destiny[0] if destiny != None and len(destiny) > 0 else None,
        )
    )

    return {
        "idIntervention": id_intervention,
        "header": {
            "patient": False,
            "idSegment": prescription_drug.idSegment,
            "status": intervention.status,
            "readonly": readonly,
            "date": intervention.date.isoformat(),
            "originDrug": origin[0]["item"]["name"],
            "destinyDrug": destiny_drug.name if destiny_drug != None else None,
            "economyDayValueManual": intervention.economy_day_value_manual,
            "economyDayValue": economy_day_value,
            "economyDayAmount": intervention.economy_days,
            "economyDayAmountManual": intervention.economy_days != None,
            "economyType": economy_type,
            "updatedAt": (
                intervention.update.isoformat() if intervention.update != None else None
            ),
            "economyIniDate": (
                intervention.date_base_economy.isoformat()
                if intervention.date_base_economy != None
                else intervention.date.isoformat()
            ),
            "economyEndDate": (
                intervention.date_end_economy.isoformat()
                if intervention.date_end_economy != None
                else None
            ),
        },
        "original": {"origin": base_origin[0], "destiny": base_destiny},
        "origin": origin[0],
        "destiny": destiny,
    }


def _calc_economy(origin, destiny):
    if origin == None:
        return 0

    if destiny != None:
        economy = none2zero(origin["item"]["pricePerDose"]) * none2zero(
            origin["item"]["frequencyDay"]
        ) - none2zero(destiny["item"]["pricePerDose"]) * none2zero(
            destiny["item"]["frequencyDay"]
        )
    else:
        economy = none2zero(origin["item"]["pricePerDose"]) * none2zero(
            origin["item"]["frequencyDay"]
        )

    return economy if economy > 0 else 0


def _get_price_kit(id_prescription, prescription_drug: PrescriptionDrug, user: User):
    group = None
    if permission_service.is_cpoe(user):
        group = prescription_drug.cpoe_group
    else:
        group = prescription_drug.solutionGroup

    if group == None:
        return {"price": 0, "list": []}

    components = (
        db.session.query(PrescriptionDrug, Drug, DrugAttributes)
        .join(Drug, PrescriptionDrug.idDrug == Drug.id)
        .outerjoin(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == Drug.id,
                DrugAttributes.idSegment == PrescriptionDrug.idSegment,
            ),
        )
        .filter(PrescriptionDrug.idPrescription == id_prescription)
        .filter(PrescriptionDrug.id != prescription_drug.id)
        .filter(
            or_(
                PrescriptionDrug.solutionGroup == group,
                PrescriptionDrug.cpoe_group == group,
            )
        )
        .filter(PrescriptionDrug.suspendedDate == None)
        .all()
    )

    drugs = []
    kit_price = 0

    for c in components:
        drug_price = c[2].price if c[2] != None and c[2].price != None else 0

        drugs.append(
            {
                "name": c[1].name,
                "price": str(drug_price),
                "idMeasureUnit": c[2].idMeasureUnitPrice if c[2] != None else None,
            }
        )
        kit_price += c[2].price if c[2] != None and c[2].price != None else 0

    return {"price": str(kit_price), "list": drugs}


def _outcome_calc(list, user: User, date_base_economy):
    results = []

    for item in list:
        origin_price = None
        dose = None

        prescription_drug: PrescriptionDrug = item[0]
        drug: Drug = item[1]
        drug_attr: DrugAttributes = item[2]
        dose_convert: MeasureUnitConvert = item[3]
        price_dose_convert: MeasureUnitConvert = item[4]
        prescription: Prescription = item[5]
        default_measure_unit: MeasureUnit = item[6]
        frequency: Frequency = item[7]

        if (
            drug_attr != None
            and drug_attr.price != None
            and drug_attr.idMeasureUnitPrice != None
        ):
            if drug_attr.idMeasureUnitPrice == drug_attr.idMeasureUnit:
                origin_price = drug_attr.price
            elif price_dose_convert != None and price_dose_convert.factor != None:
                origin_price = drug_attr.price / price_dose_convert.factor
            else:
                origin_price = drug_attr.price

        if dose_convert != None and dose_convert.factor != None:
            dose = prescription_drug.dose * dose_convert.factor
        else:
            dose = prescription_drug.dose

        frequency_day = prescription_drug.frequency
        if frequency_day in [33, 44, 55, 66, 99]:
            frequency_day = 1

        kit = _get_price_kit(
            id_prescription=prescription.id,
            prescription_drug=prescription_drug,
            user=user,
        )

        dose_factor = None
        if (
            drug_attr != None
            and prescription_drug.idMeasureUnit == drug_attr.idMeasureUnit
        ):
            dose_factor = 1
        else:
            dose_factor = dose_convert.factor if dose_convert != None else None

        price_factor = None
        if (
            drug_attr != None
            and drug_attr.idMeasureUnitPrice == drug_attr.idMeasureUnit
        ):
            price_factor = 1
        else:
            price_factor = (
                price_dose_convert.factor if price_dose_convert != None else None
            )

        id_prescription_aggregate = gen_agg_id(
            admission_number=prescription.admissionNumber,
            id_segment=prescription.idSegment,
            pdate=date_base_economy,
        )

        results.append(
            {
                "item": {
                    "idPrescription": str(prescription.id),
                    "idPrescriptionAggregate": str(id_prescription_aggregate),
                    "idPrescriptionDrug": str(prescription_drug.id),
                    "prescriptionDate": prescription.date.isoformat(),
                    "idDrug": drug.id,
                    "name": drug.name,
                    "price": str(origin_price) if origin_price != None else None,
                    "dose": str(dose),
                    "idMeasureUnit": (
                        drug_attr.idMeasureUnit if drug_attr != None else None
                    ),
                    "measureUnitDescription": (
                        default_measure_unit.description
                        if default_measure_unit != None
                        else None
                    ),
                    "idFrequency": prescription_drug.idFrequency,
                    "frequencyDay": frequency_day,
                    "frequencyDescription": (
                        frequency.description if frequency != None else None
                    ),
                    "route": prescription_drug.route,
                    "pricePerDose": str(none2zero(origin_price) * none2zero(dose)),
                    "priceKit": kit["price"],
                    "beforeConversion": {
                        "price": (
                            str(drug_attr.price)
                            if drug_attr != None and drug_attr.price != None
                            else None
                        ),
                        "idMeasureUnitPrice": (
                            drug_attr.idMeasureUnitPrice if drug_attr != None else None
                        ),
                        "dose": (
                            str(prescription_drug.dose)
                            if prescription_drug.dose != None
                            else 0
                        ),
                        "idMeasureUnit": prescription_drug.idMeasureUnit,
                    },
                    "conversion": {
                        "doseFactor": (
                            str(dose_factor) if dose_factor != None else None
                        ),
                        "priceFactor": (
                            str(price_factor) if price_factor != None else None
                        ),
                    },
                    "kit": kit,
                },
            }
        )

    return results
