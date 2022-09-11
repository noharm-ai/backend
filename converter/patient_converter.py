def list_to_dto(patients):
    list = []
    
    for p in patients:
        list.append({
            'idPatient': p[0].idPatient,
            'admissionNumber': p[0].admissionNumber,
            'admissionDate': p[0].admissionDate.isoformat() if p[0].admissionDate else None,
            'birthdate': p[0].birthdate.isoformat() if p[0].birthdate else None,
            'idPrescription': p[1].id,
            'observation': p[0].observation,
            'refDate': p[2].isoformat() if p[2] else None,
        })

    return list

