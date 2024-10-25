from sqlalchemy import case, and_, func, or_
from datetime import timedelta, datetime

from models.main import db, User
from models.prescription import (
    Intervention,
    Prescription,
    PrescriptionDrug,
    Drug,
    MeasureUnit,
    Frequency,
    MeasureUnitConvert,
    DrugAttributes,
)
from models.appendix import InterventionReason
from models.enums import (
    InterventionEconomyTypeEnum,
    InterventionStatusEnum,
)
from services import (
    data_authorization_service,
    feature_service,
)
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status, prescriptionutils, numberutils


@has_permission(Permission.WRITE_PRESCRIPTION)
def set_intervention_outcome(
    user_context: User,
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
    intervention: Intervention = (
        db.session.query(Intervention)
        .filter(Intervention.idIntervention == id_intervention)
        .first()
    )

    if not intervention:
        raise ValidationError(
            "Registro inválido",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    _validate_authorization(
        id_prescription=intervention.idPrescription,
        id_prescription_drug=intervention.id,
        user=user_context,
    )

    if outcome not in ["a", "n", "x", "j", "s"]:
        raise ValidationError(
            "Desfecho inválido",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if intervention.economy_type == InterventionEconomyTypeEnum.CUSTOM.value and (
        not economy_day_amount_manual or not economy_day_value_manual
    ):
        raise ValidationError(
            "Para o tipo de economia customizada, é necessário especificar Economia/Dia e Qtd. de dias de economia manualmente.",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if economy_day_amount_manual and (
        economy_day_amount == None or economy_day_amount == 0
    ):
        raise ValidationError(
            "Quantidade de Dias de Economia deve ser especificado e maior que zero",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if economy_day_value_manual and (economy_day_value == None):
        raise ValidationError(
            "Economia/Dia inválido",
            "errors.businessRule",
            status.HTTP_400_BAD_REQUEST,
        )

    if (
        intervention.economy_type == InterventionEconomyTypeEnum.SUBSTITUTION.value
        and outcome != InterventionStatusEnum.PENDING.value
        and id_prescription_drug_destiny == None
    ):
        if not economy_day_value_manual:
            raise ValidationError(
                "Economia/Dia deve ser especificado manualmente quando não houver prescrição substituta selecionada",
                "errors.businessRule",
                status.HTTP_400_BAD_REQUEST,
            )

        if not economy_day_amount_manual:
            raise ValidationError(
                "Qtd. de dias de economia deve ser especificado manualmente quando não houver prescrição substituta selecionada",
                "errors.businessRule",
                status.HTTP_400_BAD_REQUEST,
            )

    intervention.outcome_at = datetime.today()
    intervention.outcome_by = user_context.id
    intervention.status = outcome

    if intervention.economy_type != None:
        # intervention v2
        if intervention.status != "s":
            if economy_day_value == None:
                raise ValidationError(
                    "Economia/Dia inválido",
                    "errors.businessRule",
                    status.HTTP_400_BAD_REQUEST,
                )

            intervention.idPrescriptionDrugDestiny = id_prescription_drug_destiny

            intervention.economy_day_value = economy_day_value
            intervention.economy_day_value_manual = economy_day_value_manual

            if (
                intervention.economy_type
                == InterventionEconomyTypeEnum.SUBSTITUTION.value
                and id_prescription_drug_destiny != None
            ):
                # update date_base_economy based on substitution date
                presc_destiny: Prescription = (
                    db.session.query(Prescription)
                    .join(
                        PrescriptionDrug,
                        PrescriptionDrug.idPrescription == Prescription.id,
                    )
                    .filter(PrescriptionDrug.id == id_prescription_drug_destiny)
                    .first()
                )

                if presc_destiny == None:
                    raise ValidationError(
                        "Prescrição destino não encontrada",
                        "errors.businessRule",
                        status.HTTP_400_BAD_REQUEST,
                    )

                intervention.date_base_economy = presc_destiny.date.date()

            if economy_day_amount_manual:
                intervention.economy_days = economy_day_amount
                intervention.date_end_economy = (
                    intervention.date_base_economy
                    + timedelta(days=economy_day_amount - 1)
                )

            intervention.origin = origin_data
            intervention.destiny = destiny_data

            if not bool(intervention.origin):
                # invalid origin
                intervention.economy_day_value = 0
                intervention.economy_day_value_manual = True
        else:
            # cleanup
            intervention.idPrescriptionDrugDestiny = None
            intervention.economy_day_value = None
            intervention.economy_day_value_manual = False
            intervention.economy_days = None
            intervention.origin = None
            intervention.destiny = None
            intervention.date_end_economy = None


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


@has_permission(Permission.READ_PRESCRIPTION)
def get_outcome_data(id_intervention, user_context: User, edit=False):
    InterventionReasonParent = db.aliased(InterventionReason)
    reason_column = case(
        (
            InterventionReasonParent.description != None,
            func.concat(
                InterventionReasonParent.description,
                " - ",
                InterventionReason.description,
            ),
        ),
        else_=InterventionReason.description,
    )

    reason = (
        db.session.query(reason_column)
        .select_from(InterventionReason)
        .outerjoin(
            InterventionReasonParent,
            InterventionReasonParent.id == InterventionReason.mamy,
        )
        .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))
        .scalar_subquery()
    )

    record = (
        db.session.query(
            Intervention,
            PrescriptionDrug,
            Drug,
            User,
            func.array(reason).label("reason"),
        )
        .outerjoin(PrescriptionDrug, PrescriptionDrug.id == Intervention.id)
        .outerjoin(Drug, PrescriptionDrug.idDrug == Drug.id)
        .outerjoin(User, Intervention.outcome_by == User.id)
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
    outcome_user: User = record[3]

    # custom economy gets a simpler response
    if economy_type == InterventionEconomyTypeEnum.CUSTOM.value:
        return _get_outcome_dict(
            outcome_data=record,
            readonly=readonly,
            destiny_drug=None,
            original=None,
            origin=None,
            destiny=None,
        )

    # origin
    origin_query = _get_outcome_data_query().filter(
        PrescriptionDrug.id == intervention.id
    )
    origin_list = origin_query.all()

    if economy_type == None or len(origin_list) == 0:
        return {
            "idIntervention": intervention.idIntervention,
            "header": {
                "patient": prescription_drug == None,
                "status": intervention.status,
                "readonly": readonly,
                "date": intervention.date.isoformat(),
                "interventionReason": record.reason,
                "outcomeAt": (
                    intervention.outcome_at.isoformat()
                    if intervention.outcome_at != None
                    else None
                ),
                "outcomeUser": (outcome_user.name if outcome_user != None else None),
            },
        }

    base_origin = _outcome_calc(
        list=origin_query.all(),
        user=user_context,
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
            .filter(Prescription.date >= origin[0]["item"]["prescriptionDate"])
            .filter(Prescription.id != origin[0]["item"]["idPrescription"])
        )

        if destiny_drug != None and destiny_drug.sctid != None:
            destiny_query = destiny_query.filter(
                or_(
                    PrescriptionDrug.idDrug == destiny_id_drug,
                    Drug.sctid == destiny_drug.sctid,
                )
            )
        else:
            destiny_query = destiny_query.filter(
                PrescriptionDrug.idDrug == destiny_id_drug
            )

        destiny_query = destiny_query.order_by(Prescription.date).limit(10)

        base_destiny = _outcome_calc(
            list=destiny_query.all(),
            user=user_context,
            date_base_economy=None,
        )

        if not readonly:
            destiny = base_destiny
        else:
            destiny = [{"item": intervention.destiny}]
    else:
        base_destiny = None
        destiny = None
        destiny_drug = None

    return _get_outcome_dict(
        outcome_data=record,
        readonly=readonly,
        destiny_drug=destiny_drug,
        original={"origin": base_origin[0], "destiny": base_destiny},
        origin=origin,
        destiny=destiny,
    )


def _get_outcome_dict(
    outcome_data,
    readonly: bool,
    destiny_drug: Drug,
    original: dict,
    origin: dict,
    destiny: dict,
):
    intervention: Intervention = outcome_data[0]
    prescription_drug: PrescriptionDrug = outcome_data[1]
    origin_drug: Drug = outcome_data[2]
    outcome_user: User = outcome_data[3]

    data = {
        "idIntervention": intervention.idIntervention,
        "header": {
            "patient": intervention.idPrescription != 0,
            "status": intervention.status,
            "readonly": readonly,
            "date": intervention.date.isoformat(),
            "originDrug": origin_drug.name if origin_drug != None else None,
            "destinyDrug": destiny_drug.name if destiny_drug != None else None,
            "economyDayValueManual": intervention.economy_day_value_manual,
            "economyDayAmount": intervention.economy_days,
            "economyDayAmountManual": intervention.economy_days != None,
            "economyType": intervention.economy_type,
            "updatedAt": (
                intervention.update.isoformat() if intervention.update != None else None
            ),
            "outcomeAt": (
                intervention.outcome_at.isoformat()
                if intervention.outcome_at != None
                else None
            ),
            "outcomeUser": (outcome_user.name if outcome_user != None else None),
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
            "interventionReason": outcome_data.reason,
        },
    }

    if (
        intervention.economy_type == InterventionEconomyTypeEnum.SUBSTITUTION.value
        or intervention.economy_type == InterventionEconomyTypeEnum.SUSPENSION.value
    ):
        # calc
        economy_day_value = (
            intervention.economy_day_value
            if readonly
            else _calc_economy(
                origin=origin[0],
                destiny=destiny[0] if destiny != None and len(destiny) > 0 else None,
            )
        )

        data["header"]["economyDayValue"] = economy_day_value
        data["header"]["idSegment"] = prescription_drug.idSegment
        data["original"] = original
        data["origin"] = origin[0]
        data["destiny"] = destiny

    if intervention.economy_type == InterventionEconomyTypeEnum.CUSTOM.value:
        id_prescription = (
            intervention.idPrescription
            if intervention.idPrescription != 0
            else prescription_drug.idPrescription
        )
        prescription = (
            db.session.query(Prescription)
            .filter(Prescription.id == id_prescription)
            .first()
        )

        data["header"]["economyDayValue"] = intervention.economy_day_value
        data["header"]["economyDayValueManual"] = True
        data["header"]["economyDayAmountManual"] = True
        data["header"]["idSegment"] = prescription.idSegment
        data["origin"] = {
            "item": {
                "idPrescription": str(prescription.id),
                "idPrescriptionAgg": prescriptionutils.gen_agg_id(
                    admission_number=prescription.admissionNumber,
                    id_segment=prescription.idSegment,
                    pdate=intervention.date_base_economy,
                ),
                "prescriptionDate": prescription.date.isoformat(),
            }
        }

    return data


def _calc_economy(origin, destiny):
    if origin == None:
        return 0

    if destiny != None:
        economy = numberutils.none2zero(
            origin["item"]["pricePerDose"]
        ) * numberutils.none2zero(
            origin["item"]["frequencyDay"]
        ) - numberutils.none2zero(
            destiny["item"]["pricePerDose"]
        ) * numberutils.none2zero(
            destiny["item"]["frequencyDay"]
        )
    else:
        economy = numberutils.none2zero(
            origin["item"]["pricePerDose"]
        ) * numberutils.none2zero(origin["item"]["frequencyDay"])

    return economy


def _get_price_kit(id_prescription, prescription_drug: PrescriptionDrug, user: User):
    group = None
    if feature_service.is_cpoe():
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
            elif (
                price_dose_convert != None
                and price_dose_convert.factor != None
                and price_dose_convert.factor != 0
            ):
                origin_price = drug_attr.price / price_dose_convert.factor
            else:
                origin_price = drug_attr.price

        if (
            dose_convert != None
            and dose_convert.factor != None
            and prescription_drug.dose != None
        ):
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
                price_dose_convert.factor
                if price_dose_convert != None and price_dose_convert.factor != 0
                else None
            )

        base_date = (
            date_base_economy if date_base_economy != None else prescription.date
        )
        if prescription.idSegment:
            id_prescription_aggregate = prescriptionutils.gen_agg_id(
                admission_number=prescription.admissionNumber,
                id_segment=prescription.idSegment,
                pdate=base_date,
            )
        else:
            agg_presc = (
                db.session.query(Prescription)
                .filter(Prescription.admissionNumber == prescription.admissionNumber)
                .filter(Prescription.agg != None)
                .filter(func.date(Prescription.date) == func.date(base_date))
                .first()
            )

            if agg_presc != None:
                id_prescription_aggregate = agg_presc.id
            else:
                raise ValidationError(
                    "Não foi possível determinar o segmento desta intervenção. Tente recalcular a prescrição. Se não surtir efeito, contate o suporte.",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
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
                    "dose": str(dose) if dose != None else None,
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
                    "pricePerDose": str(
                        numberutils.none2zero(origin_price)
                        * numberutils.none2zero(dose)
                        + numberutils.none2zero(kit["price"])
                    ),
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
