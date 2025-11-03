"""Service: Intervention related operations"""

from datetime import timedelta, datetime

from sqlalchemy import case, and_, func, or_, desc
from sqlalchemy.dialects import postgresql

from models.main import db, User, Drug
from models.prescription import (
    Intervention,
    InterventionAudit,
    Prescription,
    PrescriptionDrug,
)
from models.appendix import InterventionReason, MeasureUnit, Frequency, Department
from models.enums import InterventionEconomyTypeEnum, InterventionAuditEnum
from services import (
    memory_service,
    data_authorization_service,
    segment_service,
)
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status, prescriptionutils, dateutils


@has_permission(Permission.READ_PRESCRIPTION)
def get_interventions(
    admissionNumber=None,
    startDate=None,
    endDate=None,
    idSegment=None,
    idPrescription=None,
    idPrescriptionDrug=None,
    idIntervention=None,
    idInterventionList=[],
    idDrug=None,
    id_intervention_reason_list=[],
    has_economy=None,
    status_list=[],
    responsible_name=None,
    prescriber_name=None,
    admission_number_list=None,
):
    """List and filter interventions"""
    mReasion = db.aliased(InterventionReason)
    descript = case(
        (
            mReasion.description != None,
            func.concat(mReasion.description, " - ", InterventionReason.description),
        ),
        else_=InterventionReason.description,
    )

    reason = (
        db.session.query(descript)
        .select_from(InterventionReason)
        .outerjoin(mReasion, mReasion.id == InterventionReason.mamy)
        .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))
        .scalar_subquery()
    )

    splitStr = "!?"
    dr1 = db.aliased(Drug)
    interactions = (
        db.session.query(func.concat(dr1.name, splitStr, dr1.id))
        .select_from(dr1)
        .filter(dr1.id == func.any(Intervention.interactions))
        .scalar_subquery()
    )

    PrescriptionB = db.aliased(Prescription)
    DepartmentB = db.aliased(Department)
    interventions = (
        db.session.query(
            Intervention,
            PrescriptionDrug,
            func.array(reason).label("reason"),
            case(
                (
                    PrescriptionB.concilia != None,
                    func.coalesce(PrescriptionDrug.interval, Drug.name),
                ),
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

    if admission_number_list:
        interventions = interventions.filter(
            Intervention.admissionNumber.in_(admission_number_list)
        )

    if not startDate and admissionNumber is None and admission_number_list is None:
        raise ValidationError(
            "Data inicial inválida",
            "errors.invalidRequest",
            status.HTTP_400_BAD_REQUEST,
        )

    if startDate is not None:
        interventions = interventions.filter(
            Intervention.date >= dateutils.parse_date_or_today(startDate)
        )

    if endDate is not None:
        interventions = interventions.filter(
            Intervention.date
            <= (
                dateutils.parse_date_or_today(endDate) + timedelta(hours=23, minutes=59)
            )
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

    if len(idInterventionList) > 0:
        interventions = interventions.filter(
            Intervention.idIntervention.in_(idInterventionList)
        )

    if len(id_intervention_reason_list) > 0:
        interventions = interventions.filter(
            postgresql.array(id_intervention_reason_list).overlap(
                Intervention.idInterventionReason
            )
        )

    if has_economy != None and has_economy != "":
        if has_economy:
            interventions = interventions.filter(Intervention.economy_type != None)
        else:
            interventions = interventions.filter(Intervention.economy_type == None)

    if len(status_list) > 0:
        interventions = interventions.filter(Intervention.status.in_(status_list))

    if responsible_name != None:
        interventions = interventions.filter(
            User.name.ilike("%" + str(responsible_name) + "%")
        )

    if prescriber_name != None:
        interventions = interventions.filter(
            PrescriptionB.prescriber.ilike("%" + str(prescriber_name) + "%")
        )

    if not idIntervention and len(idInterventionList) == 0:
        interventions = interventions.filter(
            Intervention.status.in_(["s", "a", "n", "x", "j"])
        )

    interventions = interventions.order_by(desc(Intervention.date)).limit(1500).all()

    def get_drug_name(i: Intervention, pd: PrescriptionDrug, drug_name: str):
        if i.id == 0 or i.id == "0":
            return "Intervenção no Paciente"

        if drug_name:
            return drug_name

        if pd:
            return "Medicamento " + str(pd.idDrug)

        return "Intervenção arquivada"

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
                "drugName": get_drug_name(i=i[0], pd=i[1], drug_name=i[3]),
                "dose": i[1].dose if i[1] else None,
                "measureUnit": (
                    {"value": i[5].id, "label": i[5].description} if i[5] else ""
                ),
                "frequency": (
                    {"value": i[6].id, "label": i[6].description} if i[6] else ""
                ),
                "time": prescriptionutils.timeValue(i[1].interval) if i[1] else None,
                "route": i[1].route if i[1] else "None",
                "admissionNumber": i[0].admissionNumber,
                "observation": i[0].notes,
                "error": i[0].error,
                "cost": i[0].cost,
                "interactionsDescription": (", ").join(
                    [d.split(splitStr)[0] for d in i[4]]
                ),
                "interactionsList": prescriptionutils.interactionsList(i[4], splitStr),
                "interactions": i[0].interactions,
                "date": i[0].date.isoformat(),
                "user": i[8],
                "department": i[9] if i[9] else i[11],
                "prescriber": i[10] if i[10] else i[7].prescriber if i[7] else None,
                "status": i[0].status,
                "transcription": i[0].transcription,
                "ram": i[0].ram,
                "economyDays": i[0].economy_days,
                "expendedDose": i[0].expended_dose,
                "suspendedDate": (
                    i[1].suspendedDate.isoformat()
                    if i[1] and i[1].suspendedDate
                    else None
                ),
            }
        )

    result = [i for i in intervBuffer if i["status"] == "s"]
    result.extend([i for i in intervBuffer if i["status"] != "s"])

    return result


@has_permission(Permission.WRITE_PRESCRIPTION)
def add_multiple_interventions(
    id_prescription_drug_list,
    user_context: User = None,
    admission_number=None,
    id_intervention_reason=None,
    error=None,
    cost=None,
    observation=None,
    agg_id_prescription=None,
    ram=None,
):
    """Create multiple interventions in one request"""
    id_intervention_list = []

    # define economy
    economy_type = None
    reasons = (
        db.session.query(InterventionReason)
        .filter(InterventionReason.id.in_(id_intervention_reason))
        .all()
    )
    has_ram = False
    for r in reasons:
        if r.suspension:
            economy_type = InterventionEconomyTypeEnum.SUSPENSION.value
        elif r.substitution:
            economy_type = InterventionEconomyTypeEnum.SUBSTITUTION.value
        elif r.customEconomy:
            economy_type = InterventionEconomyTypeEnum.CUSTOM.value

        if r.ram:
            has_ram = True

    currentDepartment = (
        db.session.query(Prescription.idDepartment)
        .filter(Prescription.admissionNumber == admission_number)
        .order_by(desc(Prescription.date))
        .first()
    )

    # insert
    for id_prescription_drug in id_prescription_drug_list:
        i = Intervention()
        i.id = id_prescription_drug
        i.idPrescription = 0
        i.date = datetime.today()
        i.update = datetime.today()
        i.user = user_context.id
        i.interactions = None
        i.transcription = None
        i.economy_days = None
        i.expended_dose = None
        i.economy_type = economy_type
        i.date = datetime.today()
        i.status = "s"
        i.economy_day_value_manual = False

        _validate_authorization(
            id_prescription=i.idPrescription,
            id_prescription_drug=i.id,
            user=user_context,
        )

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
        if has_ram:
            i.ram = ram

        # date base economy
        i.date_base_economy = _get_date_base_economy(
            economy_type=economy_type,
            i=i,
            id_prescription=0,
            id_prescription_drug=id_prescription_drug,
            agg_id_prescription=agg_id_prescription,
            user=user_context,
        )

        # current department
        if currentDepartment != None:
            i.idDepartment = currentDepartment[0]

        db.session.add(i)
        db.session.flush()

        audit = InterventionAudit()
        audit.auditType = InterventionAuditEnum.CREATE.value
        audit.idIntervention = i.idIntervention
        audit.extra = {
            "status": i.status,
            "update_responsible": False,
            "economy_type": economy_type,
        }
        audit.createdBy = user_context.id
        audit.createdAt = datetime.now()
        db.session.add(audit)
        db.session.flush()

        id_intervention_list.append(i.idIntervention)

    if len(id_intervention_list) > 0:
        return get_interventions(
            admissionNumber=admission_number, idInterventionList=id_intervention_list
        )

    return []


@has_permission(Permission.WRITE_PRESCRIPTION)
def save_intervention(
    id_intervention=None,
    id_prescription=0,
    id_prescription_drug=0,
    user_context: User = None,
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
    update_responsible=False,
    ram=None,
    period=None,
):
    """Create/update intervention"""
    if id_intervention == None and id_intervention_reason == None:
        # transition between versions
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
        i = (
            db.session.query(Intervention)
            .filter(Intervention.idIntervention == id_intervention)
            .first()
        )
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

        if i.id != 0:
            pd = (
                db.session.query(PrescriptionDrug)
                .filter(PrescriptionDrug.id == i.id)
                .first()
            )

            if not pd:
                raise ValidationError(
                    "Esta intervenção não pode ser alterada, pois está arquivada",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

        # check if intervention fkprescricao is archived
        if i.idPrescription != 0:
            pd = (
                db.session.query(Prescription)
                .filter(Prescription.id == i.idPrescription)
                .first()
            )

            if not pd:
                raise ValidationError(
                    "Esta intervenção não pode ser alterada, pois está arquivada",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

    if not i:
        new_intv = True
        i = Intervention()
        i.id = id_prescription_drug
        i.idPrescription = id_prescription
        i.date = datetime.today()
        i.update = datetime.today()
        i.user = user_context.id

    _validate_authorization(
        id_prescription=i.idPrescription, id_prescription_drug=i.id, user=user_context
    )

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
    if period:
        i.period = period

    # get economy type and ram
    economy_type = None
    has_ram = False
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
        elif r.customEconomy:
            economy_type = InterventionEconomyTypeEnum.CUSTOM.value

        if r.ram:
            has_ram = True

    if (
        id_prescription != 0
        and economy_type != InterventionEconomyTypeEnum.CUSTOM.value
    ):
        # prescription intv can only have custom economy
        economy_type = None

    i.economy_type = economy_type
    i.ram = ram if ram and has_ram else None

    # date base economy
    if i.date_base_economy == None:
        i.date_base_economy = _get_date_base_economy(
            economy_type=economy_type,
            i=i,
            id_prescription=id_prescription,
            id_prescription_drug=id_prescription_drug,
            agg_id_prescription=agg_id_prescription,
            user=user_context,
        )

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
            i.user = user_context.id

        i.status = new_status

        if new_status != "0" and new_status != "s":
            raise ValidationError(
                "O desfecho não pode ser aplicado nesta interface.",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )
    else:
        if memory_service.has_feature("PRIMARYCARE"):
            i.date = datetime.today()

    i.update = datetime.today()
    i.economy_day_value_manual = False

    if update_responsible:
        i.user = user_context.id

    if new_intv:
        db.session.add(i)
        db.session.flush()

    audit = InterventionAudit()
    audit.auditType = (
        InterventionAuditEnum.CREATE.value
        if new_intv
        else InterventionAuditEnum.UPDATE.value
    )
    audit.idIntervention = i.idIntervention
    audit.extra = {
        "status": new_status,
        "update_responsible": update_responsible,
        "economy_type": economy_type,
    }
    audit.createdBy = user_context.id
    audit.createdAt = datetime.now()
    db.session.add(audit)
    db.session.flush()

    return get_interventions(
        admissionNumber=i.admissionNumber, idIntervention=i.idIntervention
    )


def _get_date_base_economy(
    economy_type,
    i: Intervention,
    id_prescription,
    id_prescription_drug,
    agg_id_prescription,
    user: User,
):
    # date base economy
    if economy_type != None and i.date_base_economy == None:
        id_segment = None
        if id_prescription != 0:
            presc = (
                db.session.query(Prescription)
                .filter(Prescription.id == agg_id_prescription)
                .first()
            )
            id_segment = presc.idSegment if presc else None
        else:
            pd = (
                db.session.query(PrescriptionDrug)
                .filter(PrescriptionDrug.id == id_prescription_drug)
                .first()
            )
            id_segment = pd.idSegment if pd else None

        if segment_service.is_cpoe(id_segment=id_segment):
            if agg_id_prescription == None:
                return i.date
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

                return presc.date.date()
        else:
            if id_prescription != 0:
                presc: Prescription = (
                    db.session.query(Prescription)
                    .filter(Prescription.id == id_prescription)
                    .first()
                )

                if presc == None:
                    raise ValidationError(
                        "Registro inválido id_prescription: data base economia",
                        "errors.invalidRecord",
                        status.HTTP_400_BAD_REQUEST,
                    )

                return presc.date.date()
            else:
                presc = (
                    db.session.query(PrescriptionDrug, Prescription)
                    .join(
                        Prescription,
                        PrescriptionDrug.idPrescription == Prescription.id,
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

                return presc[1].date.date()

    return None


def _validate_authorization(id_prescription, id_prescription_drug, user: User):
    id_segment = None
    if id_prescription != 0:
        p = (
            db.session.query(Prescription)
            .filter(Prescription.id == id_prescription)
            .first()
        )
        if p == None:
            raise ValidationError(
                "Prescrição inexistente",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        id_segment = p.idSegment
    else:
        p_drug = (
            db.session.query(PrescriptionDrug)
            .filter(PrescriptionDrug.id == id_prescription_drug)
            .first()
        )
        id_segment = p_drug.idSegment

    if not data_authorization_service.has_segment_authorization(
        id_segment=id_segment, user=user
    ):
        raise ValidationError(
            "Usuário não autorizado neste segmento",
            "errors.businessRules",
            status.HTTP_401_UNAUTHORIZED,
        )
