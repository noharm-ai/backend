# used in route "intervention/outcome-data" test
dict_expected_before_outcome = {
    "data": {
        "destiny": [
            {
                "item": {
                    "beforeConversion": {
                        "dose": "5.0",
                        "idMeasureUnit": "1",
                        "idMeasureUnitPrice": "1",
                        "price": "4.52",
                    },
                    "conversion": {"doseFactor": "1", "priceFactor": "1"},
                    "dose": "5.0",
                    "frequencyDay": 2.0,
                    "frequencyDescription": "12h/12h",
                    "idDrug": 4,
                    "idFrequency": "2",
                    "idMeasureUnit": "1",
                    "idPrescription": "199",
                    "idPrescriptionAggregate": "2410201000009999",
                    "idPrescriptionDrug": "48",
                    "kit": {"list": [], "price": 0},
                    "measureUnitDescription": "mg",
                    "name": "BISACODIL 5 mg CP",
                    "prescriptionDate": "2024-10-20T10:15:46.390844",
                    "price": "4.52",
                    "priceKit": 0,
                    "pricePerDose": "22.599999999999998",
                    "route": "VO",
                }
            }
        ],
        "header": {
            "date": "2024-10-20T10:18:12.911249",
            "destinyDrug": "BISACODIL 5 mg CP",
            "economyDayAmount": None,
            "economyDayAmountManual": False,
            "economyDayValue": 0.0,
            "economyDayValueManual": False,
            "economyEndDate": None,
            "economyIniDate": "2024-10-20T00:00:00",
            "economyType": 2,
            "idSegment": 1,
            "interventionReason": ["Substitui\u00e7\u00e3o"],
            "originDrug": "BISACODIL 5 mg CP",
            "outcomeAt": None,
            "outcomeUser": None,
            "patient": False,
            "readonly": False,
            "status": "s",
            "updatedAt": "2024-10-20T10:18:12.925873",
            "notes": "teste",
        },
        "idIntervention": 15,
        "origin": {
            "item": {
                "beforeConversion": {
                    "dose": "5.0",
                    "idMeasureUnit": "1",
                    "idMeasureUnitPrice": "1",
                    "price": "4.52",
                },
                "conversion": {"doseFactor": "1", "priceFactor": "1"},
                "dose": "5.0",
                "frequencyDay": 2.0,
                "frequencyDescription": "12h/12h",
                "idDrug": 4,
                "idFrequency": "2",
                "idMeasureUnit": "1",
                "idPrescription": "198",
                "idPrescriptionAggregate": "2410201000009999",
                "idPrescriptionDrug": "54",
                "kit": {"list": [], "price": 0},
                "measureUnitDescription": "mg",
                "name": "BISACODIL 5 mg CP",
                "prescriptionDate": "2024-10-20T10:15:46.390844",
                "price": "4.52",
                "priceKit": 0,
                "pricePerDose": "22.599999999999998",
                "route": "VO",
            }
        },
        "original": {
            "destiny": [
                {
                    "item": {
                        "beforeConversion": {
                            "dose": "5.0",
                            "idMeasureUnit": "1",
                            "idMeasureUnitPrice": "1",
                            "price": "4.52",
                        },
                        "conversion": {"doseFactor": "1", "priceFactor": "1"},
                        "dose": "5.0",
                        "frequencyDay": 2.0,
                        "frequencyDescription": "12h/12h",
                        "idDrug": 4,
                        "idFrequency": "2",
                        "idMeasureUnit": "1",
                        "idPrescription": "199",
                        "idPrescriptionAggregate": "2410201000009999",
                        "idPrescriptionDrug": "48",
                        "kit": {"list": [], "price": 0},
                        "measureUnitDescription": "mg",
                        "name": "BISACODIL 5 mg CP",
                        "prescriptionDate": "2024-10-20T10:15:46.390844",
                        "price": "4.52",
                        "priceKit": 0,
                        "pricePerDose": "22.599999999999998",
                        "route": "VO",
                    }
                }
            ],
            "origin": {
                "item": {
                    "beforeConversion": {
                        "dose": "5.0",
                        "idMeasureUnit": "1",
                        "idMeasureUnitPrice": "1",
                        "price": "4.52",
                    },
                    "conversion": {"doseFactor": "1", "priceFactor": "1"},
                    "dose": "5.0",
                    "frequencyDay": 2.0,
                    "frequencyDescription": "12h/12h",
                    "idDrug": 4,
                    "idFrequency": "2",
                    "idMeasureUnit": "1",
                    "idPrescription": "198",
                    "idPrescriptionAggregate": "2410201000009999",
                    "idPrescriptionDrug": "54",
                    "kit": {"list": [], "price": 0},
                    "measureUnitDescription": "mg",
                    "name": "BISACODIL 5 mg CP",
                    "prescriptionDate": "2024-10-20T10:15:46.390844",
                    "price": "4.52",
                    "priceKit": 0,
                    "pricePerDose": "22.599999999999998",
                    "route": "VO",
                }
            },
        },
    },
    "status": "success",
}


# used in route  /intervention/set-outcome test
payload_api_set_outcome = {
    "idIntervention": [0],  # idIntervention to be filled by program
    "outcome": "a",
    "origin": {
        "beforeConversion": {
            "dose": "5.0",
            "idMeasureUnit": "1",
            "idMeasureUnitPrice": "1",
            "price": "4.52",
        },
        "conversion": {"doseFactor": "1", "priceFactor": "1"},
        "dose": "5.0",
        "frequencyDay": 2,
        "frequencyDescription": "12h/12h",
        "idDrug": 4,
        "idFrequency": "2",
        "idMeasureUnit": "1",
        "idPrescription": "198",
        "idPrescriptionDrug": "54",
        "kit": {"list": [], "price": 0},
        "measureUnitDescription": "mg",
        "name": "BISACODIL 5 mg CP",
        "prescriptionDate": "2024-10-20T10:15:46.390844",
        "price": "4.52",
        "priceKit": 0,
        "pricePerDose": "22.599999999999998",
        "route": "VO",
    },
    "idPrescriptionDrugDestiny": "48",
    "destiny": {
        "beforeConversion": {
            "dose": "5.0",
            "idMeasureUnit": "1",
            "idMeasureUnitPrice": "1",
            "price": "4.52",
        },
        "conversion": {"doseFactor": "1", "priceFactor": "1"},
        "dose": "5.0",
        "frequencyDay": "1",
        "frequencyDescription": "12h/12h",
        "idDrug": 4,
        "idFrequency": "2",
        "idMeasureUnit": "1",
        "idPrescription": "199",
        "idPrescriptionDrug": "48",
        "kit": {"list": [], "price": 0},
        "measureUnitDescription": "mg",
        "name": "BISACODIL 5 mg CP",
        "prescriptionDate": "2024-10-20T10:15:46.390844",
        "price": "4.52",
        "priceKit": 0,
        "pricePerDose": "22.599999999999998",
        "route": "VO",
    },
    "economyDayValueManual": False,
    "economyDayValue": "22.599999999999998",
    "economyDayAmountManual": False,
    "economyDayAmount": None,
}

# used in route /intervention/outcome-data final test
dict_expected_after_outcome = {
    "data": {
        "destiny": [
            {
                "item": {
                    "beforeConversion": {
                        "dose": "5.0",
                        "idMeasureUnit": "1",
                        "idMeasureUnitPrice": "1",
                        "price": "4.52",
                    },
                    "conversion": {"doseFactor": "1", "priceFactor": "1"},
                    "dose": "5.0",
                    "frequencyDay": 2.0,
                    "frequencyDescription": "12h/12h",
                    "idDrug": 4,
                    "idFrequency": "2",
                    "idMeasureUnit": "1",
                    "idPrescription": "199",
                    "idPrescriptionAggregate": "2410201000009999",
                    "idPrescriptionDrug": "48",
                    "kit": {"list": [], "price": 0},
                    "measureUnitDescription": "mg",
                    "name": "BISACODIL 5 mg CP",
                    "prescriptionDate": "2024-10-20T18:41:04.275245",
                    "price": "4.52",
                    "priceKit": 0,
                    "pricePerDose": "22.599999999999998",
                    "route": "VO",
                }
            }
        ],
        "header": {
            "date": "2024-10-21T09:14:02.640918",
            "destinyDrug": "BISACODIL 5 mg CP",
            "economyDayAmount": None,
            "economyDayAmountManual": False,
            "economyDayValue": 0.0,
            "economyDayValueManual": False,
            "economyEndDate": None,
            "economyIniDate": "2024-10-20T00:00:00",
            "economyType": 2,
            "idSegment": 1,
            "interventionReason": ["Substituição"],
            "originDrug": "BISACODIL 5 mg CP",
            "outcomeAt": None,
            "outcomeUser": None,
            "patient": False,
            "readonly": False,
            "status": "s",
            "updatedAt": "2024-10-21T09:14:02.677830",
            "notes": "teste",
        },
        "idIntervention": 21,
        "origin": {
            "item": {
                "beforeConversion": {
                    "dose": "5.0",
                    "idMeasureUnit": "1",
                    "idMeasureUnitPrice": "1",
                    "price": "4.52",
                },
                "conversion": {"doseFactor": "1", "priceFactor": "1"},
                "dose": "5.0",
                "frequencyDay": 2.0,
                "frequencyDescription": "12h/12h",
                "idDrug": 4,
                "idFrequency": "2",
                "idMeasureUnit": "1",
                "idPrescription": "198",
                "idPrescriptionAggregate": "2410201000009999",
                "idPrescriptionDrug": "54",
                "kit": {"list": [], "price": 0},
                "measureUnitDescription": "mg",
                "name": "BISACODIL 5 mg CP",
                "prescriptionDate": "2024-10-20T18:41:04.275245",
                "price": "4.52",
                "priceKit": 0,
                "pricePerDose": "22.599999999999998",
                "route": "VO",
            }
        },
        "original": {
            "destiny": [
                {
                    "item": {
                        "beforeConversion": {
                            "dose": "5.0",
                            "idMeasureUnit": "1",
                            "idMeasureUnitPrice": "1",
                            "price": "4.52",
                        },
                        "conversion": {"doseFactor": "1", "priceFactor": "1"},
                        "dose": "5.0",
                        "frequencyDay": 2.0,
                        "frequencyDescription": "12h/12h",
                        "idDrug": 4,
                        "idFrequency": "2",
                        "idMeasureUnit": "1",
                        "idPrescription": "199",
                        "idPrescriptionAggregate": "2410201000009999",
                        "idPrescriptionDrug": "48",
                        "kit": {"list": [], "price": 0},
                        "measureUnitDescription": "mg",
                        "name": "BISACODIL 5 mg CP",
                        "prescriptionDate": "2024-10-20T18:41:04.275245",
                        "price": "4.52",
                        "priceKit": 0,
                        "pricePerDose": "22.599999999999998",
                        "route": "VO",
                    }
                }
            ],
            "origin": {
                "item": {
                    "beforeConversion": {
                        "dose": "5.0",
                        "idMeasureUnit": "1",
                        "idMeasureUnitPrice": "1",
                        "price": "4.52",
                    },
                    "conversion": {"doseFactor": "1", "priceFactor": "1"},
                    "dose": "5.0",
                    "frequencyDay": 2.0,
                    "frequencyDescription": "12h/12h",
                    "idDrug": 4,
                    "idFrequency": "2",
                    "idMeasureUnit": "1",
                    "idPrescription": "198",
                    "idPrescriptionAggregate": "2410201000009999",
                    "idPrescriptionDrug": "54",
                    "kit": {"list": [], "price": 0},
                    "measureUnitDescription": "mg",
                    "name": "BISACODIL 5 mg CP",
                    "prescriptionDate": "2024-10-20T18:41:04.275245",
                    "price": "4.52",
                    "priceKit": 0,
                    "pricePerDose": "22.599999999999998",
                    "route": "VO",
                }
            },
        },
    },
    "status": "success",
}


def remove_not_comparable_attributes(data: dict):
    data["data"].pop("idIntervention", None)

    data["data"]["header"].pop("date", None)
    data["data"]["header"].pop("economyIniDate", None)
    data["data"]["header"].pop("updatedAt", None)

    data["data"]["destiny"][0]["item"].pop("idPrescriptionAggregate", None)
    data["data"]["destiny"][0]["item"].pop("prescriptionDate", None)

    data["data"]["origin"]["item"].pop("idPrescriptionAggregate", None)
    data["data"]["origin"]["item"].pop("prescriptionDate", None)

    data["data"]["original"]["destiny"][0]["item"].pop("idPrescriptionAggregate", None)
    data["data"]["original"]["destiny"][0]["item"].pop("prescriptionDate", None)
    data["data"]["original"]["origin"]["item"].pop("idPrescriptionAggregate", None)
    data["data"]["original"]["origin"]["item"].pop("prescriptionDate", None)
