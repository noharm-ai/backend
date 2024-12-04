from decorators.has_permission_decorator import has_permission, Permission
from repository.regulation import reg_solicitation_repository
from models.regulation import RegSolicitation, RegSolicitationType
from models.prescription import Patient, Department
from models.requests.regulation_prioritization_request import (
    RegulationPrioritizationRequest,
)
from utils import dateutils


@has_permission(Permission.READ_REGULATION)
def get_prioritization(request_data: RegulationPrioritizationRequest):
    results = reg_solicitation_repository.get_prioritization(request_data=request_data)
    records = []

    for item in results:
        solicitation: RegSolicitation = item.RegSolicitation
        solicitation_type: RegSolicitationType = item.RegSolicitationType
        patient: Patient = item.Patient
        department: Department = item.Department

        records.append(
            {
                "id": str(solicitation.id),
                "date": solicitation.date.isoformat(),
                "idPatient": str(solicitation.id_patient),
                "idDepartment": str(solicitation.id_department),
                "department": department.name if department else None,
                "stage": solicitation.stage,
                "risk": solicitation.risk,
                "idRegSolicitationType": str(solicitation.id_reg_solicitation_type),
                "type": solicitation_type.name if solicitation_type else None,
                "birthdate": dateutils.to_iso(patient.birthdate) if patient else None,
                "age": (
                    dateutils.data2age(patient.birthdate.isoformat())
                    if patient
                    else None
                ),
            }
        )

    total = results[0].total if results else 0

    return {"count": total, "list": records}


@has_permission(Permission.READ_REGULATION)
def get_types():
    results = reg_solicitation_repository.get_types()
    records = []

    for i in results:
        records.append({"id": str(i.id), "name": i.name, "type": i.tp_type})

    return records
