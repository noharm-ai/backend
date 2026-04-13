from sqlalchemy import desc, select, text

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User, db
from models.prescription import (
    Patient,
)
from utils import dateutils, status

VALID_ATTRIBUTES = {
    "antimicro": "antimicro",
    "mav": "mav",
    "controlled": "controlados",
    "notdefault": "naopadronizado",
    "elderly": "idoso",
    "tube": "sonda",
    "whiteList": "linhabranca",
    "chemo": "quimio",
    "dialyzable": "dialisavel",
}


@has_permission(Permission.READ_REPORTS)
def get_history(
    admission_number: int, attribute: str = "antimicro", user_context: User = None
):
    if admission_number is None:
        raise ValidationError(
            "admissionNumber inválido",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if attribute not in VALID_ATTRIBUTES:
        raise ValidationError(
            f"attribute inválido. Valores aceitos: {', '.join(VALID_ATTRIBUTES.keys())}",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    column_name = VALID_ATTRIBUTES[attribute]

    admission_list = [int(admission_number)]
    admission = db.session.execute(
        select(Patient.idPatient)
        .select_from(Patient)
        .where(Patient.admissionNumber == admission_number)
    ).first()

    if admission is not None:
        admissions_query = (
            select(Patient.admissionNumber)
            .select_from(Patient)
            .where(Patient.idPatient == admission.idPatient)
            .where(Patient.admissionNumber < admission_number)
            .order_by(desc(Patient.admissionDate))
            .limit(2)
        )

        a_list = db.session.execute(admissions_query).all()
        for a in a_list:
            admission_list.append(int(a.admissionNumber))

    query = text(
        f"""
            select
                drug_attr.*,
                m.nome as name,
                s.nome as substance
            from (
                SELECT
                    p.fkprescricao as id,
                    p.dtprescricao as date,
                    p.dtvigencia as expire,
                    p.nratendimento as "admissionNumber",
                    pm.dtsuspensao as "suspendedDate",
                    pm.fkpresmed AS "idPrescriptionDrug",
                    pm.dose as dose,
                    pm.via as route,
                    pm.fkmedicamento,
                    um.nome AS "measureUnit",
                    f.nome AS frequency
                FROM
                    {user_context.schema}.prescricao p
                    JOIN {user_context.schema}.presmed pm ON pm.fkprescricao = p.fkprescricao
                    JOIN {user_context.schema}.medatributos ma ON  ma.fkmedicamento = pm.fkmedicamento AND ma.idsegmento = pm.idsegmento
                    LEFT OUTER JOIN {user_context.schema}.frequencia f ON f.fkfrequencia = pm.fkfrequencia
                    LEFT OUTER JOIN {user_context.schema}.unidademedida um ON um.fkunidademedida = pm.fkunidademedida
                WHERE
                    p.nratendimento = ANY(:admissionList)
                    AND ma.{column_name} = TRUE
                ORDER BY
                    p.dtprescricao desc
                limit 1000
            ) drug_attr
            JOIN {user_context.schema}.medicamento m ON drug_attr.fkmedicamento = m.fkmedicamento
            LEFT OUTER JOIN public.substancia s ON m.sctid = s.sctid
        """
    )

    results = db.session.execute(query, {"admissionList": admission_list}).all()
    items = []

    for row in results:
        items.append(
            {
                "idPrescription": str(row.id),
                "idPrescriptionDrug": str(row.idPrescriptionDrug),
                "admissionNumber": row.admissionNumber,
                "prescriptionDate": dateutils.to_iso(row.date),
                "prescriptionExpirationDate": dateutils.to_iso(row.expire),
                "suspensionDate": dateutils.to_iso(row.suspendedDate),
                "drug": row.name,
                "substance": row.substance,
                "dose": row.dose,
                "measureUnit": row.measureUnit,
                "frequency": row.frequency,
                "route": row.route,
            }
        )

    return items
