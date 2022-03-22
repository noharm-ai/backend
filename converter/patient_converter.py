def list_to_dto(patients):
    list = []
    for p in patients:
        list.append(to_dto(p))

    return list


def to_dto(patient):
    return {
        'id': patient.idPatient,
        'admissionNumber': patient.admissionNumber,
        'birthdate': patient.birthdate.isoformat() if patient.birthdate else None,
    }
