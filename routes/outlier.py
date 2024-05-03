from utils import status
from models.main import *
from models.prescription import *
from sqlalchemy import desc, asc, and_, func
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from decimal import Decimal, ROUND_HALF_UP
from .utils import freqValue, tryCommit, typeRelations, sortSubstance, strNone
from datetime import datetime
from math import ceil

from models.enums import RoleEnum
from services.drug_service import (
    getPreviouslyPrescribedUnits,
    getPreviouslyPrescribedFrequencies,
)

app_out = Blueprint("app_out", __name__)


@app_out.route("/outliers/<int:idSegment>/<int:idDrug>", methods=["GET"])
@jwt_required()
def getOutliers(idSegment=1, idDrug=1):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    outliers = (
        db.session.query(Outlier, Notes)
        .outerjoin(Notes, Notes.idOutlier == Outlier.id)
        .filter(Outlier.idSegment == idSegment, Outlier.idDrug == idDrug)
        .order_by(Outlier.countNum.desc(), Outlier.frequency.asc())
        .all()
    )
    d = (
        db.session.query(Drug, Substance.name)
        .outerjoin(Substance, Substance.id == Drug.sctid)
        .filter(Drug.id == idDrug)
        .first()
    )

    drugAttr = DrugAttributes.query.get((idDrug, idSegment))

    relations = []
    defaultNote = None
    if d and d[0].sctid:
        relations = Relation.findBySctid(d[0].sctid, user)
        defaultNote = (
            Notes.getDefaultNote(d[0].sctid) if not user.permission() else None
        )

    if drugAttr is None:
        drugAttr = DrugAttributes()

    frequency = request.args.get("f", None)
    dose = request.args.get("d", None)

    if dose:
        if drugAttr.division and dose:
            dose = round(
                ceil(((float(dose)) / drugAttr.division)) * drugAttr.division, 2
            )
        else:
            rounded = Decimal(dose).quantize(Decimal("1e-2"), rounding=ROUND_HALF_UP)
            dose = rounded

    units = getUnits(idDrug, idSegment)  # TODO: Refactor
    defaultUnit = "unlikely big name for a measure unit"
    bUnit = False
    for unit in units[0]["data"]:
        if unit["fator"] == 1 and len(unit["idMeasureUnit"]) < len(defaultUnit):
            defaultUnit = unit["idMeasureUnit"]
            bUnit = True

    if not bUnit:
        defaultUnit = ""

    newOutlier = True
    results = []
    for o in outliers:
        selected = False
        if (
            dose is not None
            and frequency is not None
            and is_float(dose)
            and is_float(frequency)
        ):
            if float(dose) == o[0].dose and float(frequency) == o[0].frequency:
                newOutlier = False
                selected = True

        results.append(
            {
                "idOutlier": o[0].id,
                "idDrug": o[0].idDrug,
                "countNum": o[0].countNum,
                "dose": o[0].dose,
                "unit": defaultUnit,
                "frequency": freqValue(o[0].frequency),
                "score": o[0].score,
                "manualScore": o[0].manualScore,
                "obs": o[1].notes if o[1] != None else "",
                "updatedAt": o[0].update.isoformat() if o[0].update else None,
                "selected": selected,
            }
        )

    if (
        dose is not None
        and frequency is not None
        and newOutlier
        and is_float(dose)
        and is_float(frequency)
    ):
        o = Outlier()
        o.idDrug = idDrug
        o.idSegment = idSegment
        o.countNum = 1
        o.dose = float(dose)
        o.frequency = float(frequency)
        o.score = 4
        o.manualScore = None
        o.update = datetime.today()
        o.user = user.id

        db.session.add(o)
        db.session.flush()

        results.append(
            {
                "idOutlier": o.id,
                "idDrug": idDrug,
                "countNum": 1,
                "dose": float(dose),
                "unit": defaultUnit,
                "frequency": freqValue(float(frequency)),
                "score": 4,
                "manualScore": None,
                "obs": "",
                "updatedAt": o.update.isoformat() if o.update else None,
                "selected": True,
            }
        )

    returnJson = {
        "status": "success",
        "data": {
            "outliers": results,
            "antimicro": drugAttr.antimicro,
            "mav": drugAttr.mav,
            "controlled": drugAttr.controlled,
            "notdefault": drugAttr.notdefault,
            "maxDose": drugAttr.maxDose,
            "kidney": drugAttr.kidney,
            "liver": drugAttr.liver,
            "platelets": drugAttr.platelets,
            "elderly": drugAttr.elderly,
            "tube": drugAttr.tube,
            "division": drugAttr.division,
            "useWeight": drugAttr.useWeight,
            "idMeasureUnit": drugAttr.idMeasureUnit or defaultUnit,
            "idMeasureUnitPrice": drugAttr.idMeasureUnitPrice,
            "amount": drugAttr.amount,
            "amountUnit": drugAttr.amountUnit,
            "price": drugAttr.price,
            "maxTime": drugAttr.maxTime,
            "whiteList": drugAttr.whiteList,
            "chemo": drugAttr.chemo,
            "sctidA": str(d[0].sctid) if d else "",
            "sctNameA": strNone(d[1]).upper() if d else "",
            "relations": relations,
            "relationTypes": [
                {"key": t, "value": typeRelations[t]} for t in typeRelations
            ],
            "defaultNote": defaultNote,
        },
    }

    tryCommit(db, idDrug)
    return returnJson, status.HTTP_200_OK


@app_out.route("/outliers/<int:idOutlier>", methods=["PUT"])
@jwt_required()
def setManualOutlier(idOutlier):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    o = Outlier.query.get(idOutlier)
    if "manualScore" in data:
        manualScore = data.get("manualScore", None)
        o.manualScore = manualScore
        o.update = datetime.today()
        o.user = user.id

    if "obs" in data:
        notes = data.get("obs", None)
        obs = Notes.query.get((idOutlier, 0))
        newObs = False

        if obs is None:
            newObs = True
            obs = Notes()
            obs.idOutlier = idOutlier
            obs.idPrescriptionDrug = 0
            obs.idSegment = o.idSegment
            obs.idDrug = o.idDrug
            obs.dose = o.dose
            obs.frequency = o.frequency

        obs.notes = notes
        obs.update = datetime.today()
        obs.user = user.id

        if newObs:
            db.session.add(obs)

    return tryCommit(db, escape_html(idOutlier))


@app_out.route("/drugs", methods=["GET"])
@app_out.route("/drugs/<int:idSegment>", methods=["GET"])
@jwt_required()
def getDrugs(idSegment=1):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    qDrug = request.args.get("q", None)
    idDrug = request.args.getlist("idDrug[]")

    drugs = Drug.getBySegment(idSegment, qDrug, idDrug)

    results = []
    for d in drugs:
        results.append(
            {
                "idDrug": str(d.id),
                "name": d.name,
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_out.route("/drugs/<int:idDrug>/units", methods=["GET"])
@jwt_required()
def getUnits(idDrug, idSegment=1):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get("idSegment", idSegment)

    u = db.aliased(MeasureUnit)
    p = db.aliased(PrescriptionAgg)
    mu = db.aliased(MeasureUnitConvert)
    d = db.aliased(Drug)

    units = (
        db.session.query(
            u.id,
            u.description,
            d.name,
            func.sum(func.coalesce(p.countNum, 0)).label("count"),
            func.max(mu.factor).label("factor"),
        )
        .select_from(u)
        .join(d, and_(d.id == idDrug))
        .outerjoin(
            p,
            and_(p.idMeasureUnit == u.id, p.idDrug == idDrug, p.idSegment == idSegment),
        )
        .outerjoin(
            mu,
            and_(
                mu.idMeasureUnit == u.id, mu.idDrug == idDrug, mu.idSegment == idSegment
            ),
        )
        .filter(or_(p.idSegment == idSegment, mu.idSegment == idSegment))
        .group_by(u.id, u.description, p.idMeasureUnit, d.name)
        .order_by(asc(u.description))
        .all()
    )

    results = []
    for u in units:
        results.append(
            {
                "idMeasureUnit": u.id,
                "description": u.description,
                "drugName": u[2],
                "fator": u[4] if u[4] != None else 1,
                "contagem": u[3],
            }
        )

    return {"status": "success", "data": results}, status.HTTP_200_OK


@app_out.route("/drugs/<int:idSegment>/<int:idDrug>/convertunit", methods=["POST"])
@jwt_required()
def setDrugUnit(idSegment, idDrug):
    data = request.get_json()
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idMeasureUnit = data.get("idMeasureUnit", 1)
    u = MeasureUnitConvert.query.get((idMeasureUnit, idDrug, idSegment))
    new = False

    if u is None:
        new = True
        u = MeasureUnitConvert()
        u.idMeasureUnit = idMeasureUnit
        u.idDrug = idDrug
        u.idSegment = idSegment

    u.factor = data.get("factor", 1)

    if new:
        db.session.add(u)

    return tryCommit(db, escape_html(idMeasureUnit))


@app_out.route("/drugs/summary/<int:idSegment>/<int:idDrug>", methods=["GET"])
@jwt_required()
def getDrugSummary(idDrug, idSegment):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    maxDays = 90

    u = db.aliased(MeasureUnit)
    p = db.aliased(Prescription)
    pd = db.aliased(PrescriptionDrug)
    f = db.aliased(Frequency)

    drug = Drug.query.get(idDrug)

    if drug is None:
        return {
            "status": "error",
            "message": "Registro inválido",
            "code": "errors.invalidRecord",
        }, status.HTTP_400_BAD_REQUEST

    units = getPreviouslyPrescribedUnits(idDrug, idSegment)

    unitResults = []
    for u in units:
        unitResults.append(
            {"id": u.id, "description": u.description, "amount": u.count}
        )

    frequencies = getPreviouslyPrescribedFrequencies(idDrug, idSegment)

    frequencyResults = []
    for f in frequencies:
        frequencyResults.append(
            {"id": f.id, "description": f.description, "amount": f.count}
        )

    routes = (
        db.session.query(pd.route)
        .select_from(pd)
        .join(p, p.id == pd.idPrescription)
        .filter(
            and_(
                pd.idDrug == idDrug,
                pd.idSegment == idSegment,
                p.date > func.current_date() - maxDays,
            )
        )
        .group_by(pd.route)
        .all()
    )

    routeResults = []
    for r in routes:
        routeResults.append({"id": r.route, "description": r.route})

    intervals = (
        db.session.query(pd.interval, pd.idFrequency)
        .select_from(pd)
        .join(p, p.id == pd.idPrescription)
        .filter(
            and_(
                pd.idDrug == idDrug,
                pd.idSegment == idSegment,
                p.date > func.current_date() - maxDays,
                pd.interval != None,
            )
        )
        .group_by(pd.interval, pd.idFrequency)
        .all()
    )

    intervalResults = []
    for i in intervals:
        intervalResults.append(
            {
                "id": i.interval,
                "idFrequency": i.idFrequency,
                "description": timeValue(i.interval),
            }
        )

    results = {
        "drug": {"id": drug.id, "name": drug.name},
        "units": unitResults,
        "frequencies": frequencyResults,
        "routes": routeResults,
        "intervals": intervalResults,
    }

    return {"status": "success", "data": results}, status.HTTP_200_OK
