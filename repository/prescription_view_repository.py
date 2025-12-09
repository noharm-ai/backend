"""Repository: prescription view related operations"""

from datetime import datetime

from sqlalchemy import and_, asc, between, case, desc, func, literal, or_
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy.sql.expression import literal_column

from models.appendix import (
    Department,
    Frequency,
    MeasureUnit,
    MeasureUnitConvert,
    Notes,
)
from models.main import Drug, DrugAttributes, Outlier, Substance, User, db
from models.prescription import Prescription, PrescriptionDrug


def _get_period_filter(query, model, agg_date, is_pmc, is_cpoe, ignore_segments=None):
    """
    adds default prescription period search
    """

    if not is_pmc:
        if is_cpoe:
            query = query.filter(
                between(
                    func.date(agg_date),
                    func.date(model.date - func.cast("2 DAY", INTERVAL)),
                    func.coalesce(func.date(model.expire), func.date(agg_date)),
                )
            )

            if ignore_segments is not None:
                query = query.filter(
                    or_(~model.idSegment.in_(ignore_segments), model.idSegment == None)
                )
        else:
            query = query.filter(
                between(
                    func.date(agg_date),
                    func.date(model.date),
                    func.coalesce(func.date(model.expire), func.date(agg_date)),
                )
            )

    return query


def find_drugs_by_prescription(
    idPrescription,
    admissionNumber,
    aggDate=None,
    idSegment=None,
    is_cpoe=False,
    is_pmc=False,
    ignore_segments=None,
):
    """
    find drugs related to the prescription
    """

    prevNotes = _get_prev_notes(admissionNumber)

    if aggDate is not None and is_cpoe:
        # Use current time if aggDate is today, last minute of day if before today, or keep original if future
        aggDate_adjusted = case(
            (
                func.date(aggDate) < datetime.now().date(),
                func.date_trunc("day", aggDate)
                + func.cast("1 day", INTERVAL)
                - func.cast("1 second", INTERVAL),
            ),
            (func.date(aggDate) == datetime.now().date(), datetime.now()),
            else_=aggDate,
        )

        # Extract epoch (seconds) and divide by seconds per day to get fractional days
        period_calc = func.floor(
            func.extract("epoch", aggDate_adjusted - Prescription.date) / 86400.0
        )
        max_period = func.floor(
            func.extract("epoch", Prescription.expire - Prescription.date) / 86400.0
        )
        max_period_suspended = func.floor(
            func.extract("epoch", PrescriptionDrug.suspendedDate - Prescription.date)
            / 86400.0
        )
        period_cpoe = case(
            (
                func.extract("epoch", aggDate_adjusted - Prescription.date) < 0,
                0,
            ),  # before starts
            (
                aggDate_adjusted > PrescriptionDrug.suspendedDate,
                max_period_suspended,
            ),  # when suspended
            (aggDate_adjusted > Prescription.expire, max_period),  # when expired
            else_=period_calc,
        )

    else:
        period_cpoe = literal_column("0")

    substance_handling = (
        db.session.query(("*"))
        .select_from(func.jsonb_object_keys(Substance.handling))
        .filter(Substance.handling != None)
        .filter(Substance.handling != "null")
        .as_scalar()
    )

    MeasureUnitSolutionConvert = db.aliased(MeasureUnitConvert)
    MeasureUnitSolution = db.aliased(MeasureUnit)
    MeasureUnitDefault = db.aliased(MeasureUnit)

    ml_conversion_factor_subquery = (
        db.session.query(MeasureUnitSolutionConvert.factor)
        .join(
            MeasureUnitSolution,
            MeasureUnitSolution.id == MeasureUnitSolutionConvert.idMeasureUnit,
        )
        .filter(MeasureUnitSolution.measureunit_nh == "ml")
        .filter(MeasureUnitSolutionConvert.idSegment == PrescriptionDrug.idSegment)
        .filter(MeasureUnitSolutionConvert.idDrug == PrescriptionDrug.idDrug)
        .limit(1)
        .as_scalar()
    )

    q = (
        db.session.query(
            PrescriptionDrug,
            Drug,
            MeasureUnit,
            Frequency,
            literal("0"),
            func.coalesce(
                PrescriptionDrug.finalscore,
                func.coalesce(func.coalesce(Outlier.manualScore, Outlier.score), 4),
            ).label("score"),
            DrugAttributes,
            Notes.notes,
            prevNotes.label("prevNotes"),
            Prescription.status,
            Prescription.expire.label("prescription_expire"),
            Substance,
            period_cpoe.label("period_cpoe"),
            Prescription.date.label("prescription_date"),
            MeasureUnitConvert.factor.label("measure_unit_convert_factor"),
            func.array(substance_handling).label("substance_handling_types"),
            Prescription.idDepartment.label("idDepartment"),
            ml_conversion_factor_subquery.label("measure_unit_solution_convert_factor"),
            MeasureUnitDefault.measureunit_nh.label("default_measure_unit_nh"),
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
            MeasureUnitConvert,
            and_(
                MeasureUnitConvert.idSegment == PrescriptionDrug.idSegment,
                MeasureUnitConvert.idDrug == PrescriptionDrug.idDrug,
                MeasureUnitConvert.idMeasureUnit == MeasureUnit.id,
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
        .outerjoin(
            MeasureUnitDefault,
            and_(
                MeasureUnitDefault.id == DrugAttributes.idMeasureUnit,
                MeasureUnitDefault.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(Substance, Drug.sctid == Substance.id)
    )

    if aggDate is None:
        q = q.filter(PrescriptionDrug.idPrescription == idPrescription)
    else:
        q = (
            q.filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.agg == None)
            .filter(Prescription.concilia == None)
        )

        q = _get_period_filter(
            query=q,
            model=Prescription,
            agg_date=aggDate,
            is_pmc=is_pmc,
            is_cpoe=is_cpoe,
            ignore_segments=ignore_segments,
        )

        if is_cpoe:
            q = q.filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate) >= func.date(aggDate),
                )
            )
        else:
            if idSegment != None:
                q = q.filter(Prescription.idSegment == idSegment)

    return q.order_by(asc(Drug.name)).all()


def _get_prev_notes(admissionNumber):
    prevNotes = db.aliased(Notes)
    prevUser = db.aliased(User)

    return (
        db.session.query(
            case(
                (
                    and_(prevNotes.notes != None, prevNotes.notes != ""),
                    func.concat(
                        prevNotes.notes,
                        " ##@",
                        prevUser.name,
                        " em ",
                        func.to_char(prevNotes.update, "DD/MM/YYYY HH24:MI"),
                        "@##",
                    ),
                ),
                else_=None,
            )
        )
        .select_from(prevNotes)
        .outerjoin(prevUser, prevNotes.user == prevUser.id)
        .filter(prevNotes.admissionNumber == admissionNumber)
        .filter(prevNotes.idDrug == PrescriptionDrug.idDrug)
        .filter(prevNotes.idPrescriptionDrug < PrescriptionDrug.id)
        .order_by(desc(prevNotes.update))
        .limit(1)
        .as_scalar()
    )


def get_headers(
    admissionNumber,
    aggDate,
    idSegment,
    is_pmc=False,
    is_cpoe=False,
    ignore_segments=None,
):
    """
    list individual prescriptions for the agg prescription
    """

    q = (
        db.session.query(Prescription, Department.name, User.name)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(User, Prescription.user == User.id)
        .filter(Prescription.admissionNumber == admissionNumber)
        .filter(Prescription.agg == None)
        .filter(Prescription.concilia == None)
    )

    q = _get_period_filter(
        query=q,
        model=Prescription,
        agg_date=aggDate,
        is_pmc=is_pmc,
        is_cpoe=is_cpoe,
        ignore_segments=ignore_segments,
    )

    if not is_cpoe:
        q = q.filter(Prescription.idSegment == idSegment)
    else:
        # discard all suspended
        active_count = (
            db.session.query(func.count().label("count"))
            .filter(PrescriptionDrug.idPrescription == Prescription.id)
            .filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate) >= aggDate,
                )
            )
            .as_scalar()
        )
        q = q.filter(active_count > 0)

    prescriptions = q.all()

    headers = {}
    for p in prescriptions:
        headers[p[0].id] = {
            "date": p[0].date.isoformat() if p[0].date else None,
            "expire": p[0].expire.isoformat() if p[0].expire else None,
            "status": p[0].status,
            "bed": p[0].bed,
            "prescriber": p[0].prescriber,
            "idSegment": p[0].idSegment,
            "idHospital": p[0].idHospital,
            "idDepartment": p[0].idDepartment,
            "department": p[1],
            "drugs": {},
            "procedures": {},
            "solutions": {},
            "user": p[2],
            "userId": p[0].user,
        }

    return headers


def get_query_prescriptions_by_agg(
    agg_prescription: Prescription,
    is_cpoe=False,
    is_pmc=False,
    only_id=False,
    ignore_segments=None,
):
    """
    Base query to find prescriptions inside agg
    """

    q = (
        db.session.query(Prescription.id if only_id else Prescription)
        .filter(Prescription.admissionNumber == agg_prescription.admissionNumber)
        .filter(Prescription.concilia == None)
        .filter(Prescription.agg == None)
    )

    q = _get_period_filter(
        query=q,
        model=Prescription,
        agg_date=agg_prescription.date,
        is_pmc=is_pmc,
        is_cpoe=is_cpoe,
        ignore_segments=ignore_segments,
    )

    if not is_cpoe:
        q = q.filter(Prescription.idSegment == agg_prescription.idSegment)
    else:
        # discard all suspended
        active_count = (
            db.session.query(func.count().label("count"))
            .filter(PrescriptionDrug.idPrescription == Prescription.id)
            .filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate) >= agg_prescription.date,
                )
            )
            .as_scalar()
        )
        q = q.filter(active_count > 0)

    return q
