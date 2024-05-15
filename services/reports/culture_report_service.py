from sqlalchemy import select

from models.main import db, desc, User
from models.appendix import CultureHeader, Culture
from exception.validation_error import ValidationError
from utils import dateutils, status


def get_cultures(idPatient: int, user: User):
    if idPatient == None:
        raise ValidationError(
            "idPatient inválido",
            "errors.invalidParams",
            status.HTTP_401_UNAUTHORIZED,
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
            Culture.microorganism,
            Culture.drug,
            Culture.result,
            Culture.microorganismAmount,
        )
        .outerjoin(Culture, CultureHeader.idExamItem == Culture.idExamItem)
        .where(CultureHeader.idPatient == idPatient)
        .order_by(desc(CultureHeader.collectionDate), CultureHeader.idExamItem)
        .limit(2000)
    )

    results = db.session.execute(query).all()

    return _group_culture_results(results=results)


def _group_culture_results(results):
    headers = {}

    def culture(row):
        if row.result != None:
            return {
                "microorganism": row.microorganism,
                "drug": row.drug,
                "result": row.result,
                "microorganismAmount": row.microorganismAmount,
            }

        return None

    for row in results:
        culture_data = culture(row)

        if row.id in headers:
            if culture_data != None:
                headers[row.id]["cultures"].append(culture_data)
        else:
            headers[row.id] = {
                "id": row.id,
                "idExamItem": row.idExamItem,
                "collectionDate": dateutils.toIso(row.collectionDate),
                "releaseDate": dateutils.toIso(row.releaseDate),
                "examName": row.examName,
                "examMaterialName": row.examMaterialName,
                "previousResult": row.previousResult,
                "gram": row.gram,
                "extraInfo": row.extraInfo,
                "colony": row.colony,
                "microorganism": None,
                "cultures": [culture_data] if culture_data != None else [],
            }

    grouped_data = []
    for id in headers:
        headers[id]["cultures"] = sorted(
            headers[id]["cultures"], key=lambda d: d["drug"]
        )
        if len(headers[id]["cultures"]) > 0:
            headers[id]["microorganism"] = headers[id]["cultures"][0]["microorganism"]
        grouped_data.append(headers[id])

    return sorted(grouped_data, key=lambda d: d["collectionDate"], reverse=True)
