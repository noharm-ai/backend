from sqlalchemy import select

from models.main import db, desc, User
from models.appendix import CultureHeader, Culture
from exception.validation_error import ValidationError
from utils import dateutils, status
from routes.utils import none2zero


def get_cultures(idPatient: int, user: User):
    if idPatient == None:
        raise ValidationError(
            "idPatient inválido", "errors.invalidParams", status.HTTP_400_BAD_REQUEST
        )

    query = (
        select(
            CultureHeader.id,
            CultureHeader.idExamItem,
            CultureHeader.collectionDate,
            CultureHeader.releaseDate,
            CultureHeader.examName,
            CultureHeader.examMaterialName,
            CultureHeader.previousResult,
            CultureHeader.gram,
            CultureHeader.extraInfo,
            CultureHeader.colony,
            Culture.idMicroorganism,
            Culture.microorganism,
            Culture.drug,
            Culture.result,
            Culture.microorganismAmount,
            Culture.drug_proba,
            Culture.predict_proba,
            Culture.prediction,
        )
        .outerjoin(Culture, CultureHeader.idExamItem == Culture.idExamItem)
        .where(CultureHeader.idPatient == idPatient)
        .order_by(
            desc(CultureHeader.collectionDate),
            CultureHeader.idExamItem,
            Culture.idMicroorganism,
        )
        .limit(2000)
    )

    results = db.session.execute(query).all()

    return _group_culture_results(results=results)


def _group_culture_results(results):
    headers = {}

    def culture(row):
        if row.microorganism != None:
            return {
                "microorganism": row.microorganism,
                "drug": row.drug,
                "result": row.result,
                "microorganismAmount": row.microorganismAmount,
            }

        return None

    def prediction(row):
        if (
            row.prediction != None
            and none2zero(row.predict_proba) > 0.7
            and none2zero(row.drug_proba) > 0.025
        ):
            return {
                "drug": row.drug,
                "prediction": row.prediction,
                "probability": row.predict_proba,
            }

        return None

    for row in results:
        culture_data = culture(row)
        prediction_data = prediction(row)

        key = (
            f"{row.id}-{row.idMicroorganism if row.idMicroorganism != None else 'None'}"
        )

        if key in headers:
            if culture_data != None:
                headers[key]["cultures"].append(culture_data)

            if prediction_data != None:
                headers[key]["predictions"].append(prediction_data)
        else:
            headers[key] = {
                "key": key,
                "id": row.id,
                "idExamItem": row.idExamItem,
                "collectionDate": dateutils.to_iso(row.collectionDate),
                "releaseDate": dateutils.to_iso(row.releaseDate),
                "examName": row.examName,
                "examMaterialName": row.examMaterialName,
                "previousResult": row.previousResult,
                "gram": row.gram,
                "extraInfo": row.extraInfo,
                "colony": row.colony,
                "microorganism": None,
                "cultures": [culture_data] if culture_data != None else [],
                "predictions": [prediction_data] if prediction_data != None else [],
            }

    grouped_data = []
    for id in headers:
        headers[id]["cultures"] = sorted(
            headers[id]["cultures"],
            key=lambda d: d["drug"] if d["drug"] != None else "",
        )
        if len(headers[id]["cultures"]) > 0:
            headers[id]["microorganism"] = headers[id]["cultures"][0]["microorganism"]

        if len(headers[id]["predictions"]) > 0:
            headers[id]["predictions"] = sorted(
                headers[id]["predictions"],
                key=lambda d: d["drug"] if d["drug"] != None else "",
            )

        grouped_data.append(headers[id])

    return sorted(
        grouped_data,
        key=lambda d: d["collectionDate"] if d["collectionDate"] != None else "",
        reverse=True,
    )
