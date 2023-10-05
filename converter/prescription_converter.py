def search_results(prescriptions):
    list = []

    for p in prescriptions:
        list.append(
            {
                "idPrescription": p[0].id,
                "admissionNumber": p[0].admissionNumber,
                "date": p[0].date.isoformat() if p[0].date else None,
                "status": p[0].status,
                "agg": p[0].agg,
                "concilia": p[0].concilia,
                "birthdate": p[1].isoformat() if p[1] else None,
                "gender": p[2],
                "department": p[3],
                "admissionDate": p[4].isoformat() if p[4] else None,
            }
        )

    return list
