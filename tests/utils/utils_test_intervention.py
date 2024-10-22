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

# used in route /intervention/outcome-data test
fields_to_compare_outcome = [
    "data.destiny.0.item.beforeConversion",
    "data.destiny.0.item.beforeConversion.dose",
    "data.destiny.0.item.beforeConversion.idMeasureUnit",
    "data.destiny.0.item.beforeConversion.idMeasureUnitPrice",
    "data.destiny.0.item.beforeConversion.price",
    "data.destiny.0.item.conversion",
    "data.destiny.0.item.conversion.doseFactor",
    "data.destiny.0.item.conversion.priceFactor",
    "data.destiny.0.item.dose",
    "data.destiny.0.item.frequencyDay",
    "data.destiny.0.item.frequencyDescription",
    "data.destiny.0.item.idDrug",
    "data.destiny.0.item.idFrequency",
    "data.destiny.0.item.idMeasureUnit",
    "data.destiny.0.item.idPrescription",
    "data.destiny.0.item.idPrescriptionAggregate",
    "data.destiny.0.item.idPrescriptionDrug",
    "data.destiny.0.item.kit",
    "data.destiny.0.item.kit.list",
    "data.destiny.0.item.kit.price",
    "data.destiny.0.item.measureUnitDescription",
    "data.destiny.0.item.name",
    "data.destiny.0.item.price",
    "data.destiny.0.item.priceKit",
    "data.destiny.0.item.pricePerDose",
    "data.destiny.0.item.route",
    "data.header.destinyDrug",
    "data.header.economyDayAmount",
    "data.header.economyDayAmountManual",
    "data.header.economyDayValue",
    "data.header.economyDayValueManual",
    "data.header.economyEndDate",
    "data.header.economyIniDate",
    "data.header.economyType",
    "data.header.idSegment",
    "data.header.interventionReason",
    "data.header.interventionReason.0",
    "data.header.originDrug",
    "data.header.outcomeAt",
    "data.header.outcomeUser",
    "data.header.patient",
    "data.header.readonly",
    "data.header.status",
    "data.origin.item.beforeConversion",
    "data.origin.item.beforeConversion.dose",
    "data.origin.item.beforeConversion.idMeasureUnit",
    "data.origin.item.beforeConversion.idMeasureUnitPrice",
    "data.origin.item.beforeConversion.price",
    "data.origin.item.conversion",
    "data.origin.item.conversion.doseFactor",
    "data.origin.item.conversion.priceFactor",
    "data.origin.item.dose",
    "data.origin.item.frequencyDay",
    "data.origin.item.frequencyDescription",
    "data.origin.item.idDrug",
    "data.origin.item.idFrequency",
    "data.origin.item.idMeasureUnit",
    "data.origin.item.idPrescription",
    "data.origin.item.idPrescriptionAggregate",
    "data.origin.item.idPrescriptionDrug",
    "data.origin.item.kit",
    "data.origin.item.kit.list",
    "data.origin.item.kit.price",
    "data.origin.item.measureUnitDescription",
    "data.origin.item.name",
    "data.origin.item.price",
    "data.origin.item.priceKit",
    "data.origin.item.pricePerDose",
    "data.origin.item.route",
    "data.original.destiny.0.item.beforeConversion",
    "data.original.destiny.0.item.beforeConversion.dose",
    "data.original.destiny.0.item.beforeConversion.idMeasureUnit",
    "data.original.destiny.0.item.beforeConversion.idMeasureUnitPrice",
    "data.original.destiny.0.item.beforeConversion.price",
    "data.original.destiny.0.item.conversion",
    "data.original.destiny.0.item.conversion.doseFactor",
    "data.original.destiny.0.item.conversion.priceFactor",
    "data.original.destiny.0.item.dose",
    "data.original.destiny.0.item.frequencyDay",
    "data.original.destiny.0.item.frequencyDescription",
    "data.original.destiny.0.item.idDrug",
    "data.original.destiny.0.item.idFrequency",
    "data.original.destiny.0.item.idMeasureUnit",
    "data.original.destiny.0.item.idPrescription",
    "data.original.destiny.0.item.idPrescriptionAggregate",
    "data.original.destiny.0.item.idPrescriptionDrug",
    "data.original.destiny.0.item.kit",
    "data.original.destiny.0.item.kit.list",
    "data.original.destiny.0.item.kit.price",
    "data.original.destiny.0.item.measureUnitDescription",
    "data.original.destiny.0.item.name",
    "data.original.destiny.0.item.price",
    "data.original.destiny.0.item.priceKit",
    "data.original.destiny.0.item.pricePerDose",
    "data.original.destiny.0.item.route",
    "data.original.origin.item.beforeConversion",
    "data.original.origin.item.beforeConversion.dose",
    "data.original.origin.item.beforeConversion.idMeasureUnit",
    "data.original.origin.item.beforeConversion.idMeasureUnitPrice",
    "data.original.origin.item.beforeConversion.price",
    "data.original.origin.item.conversion",
    "data.original.origin.item.conversion.doseFactor",
    "data.original.origin.item.conversion.priceFactor",
    "data.original.origin.item.dose",
    "data.original.origin.item.frequencyDay",
    "data.original.origin.item.frequencyDescription",
    "data.original.origin.item.idDrug",
    "data.original.origin.item.idFrequency",
    "data.original.origin.item.idMeasureUnit",
    "data.original.origin.item.idPrescription",
    "data.original.origin.item.idPrescriptionAggregate",
    "data.original.origin.item.idPrescriptionDrug",
    "data.original.origin.item.kit",
    "data.original.origin.item.kit.list",
    "data.original.origin.item.kit.price",
    "data.original.origin.item.measureUnitDescription",
    "data.original.origin.item.name",
    "data.original.origin.item.price",
    "data.original.origin.item.priceKit",
    "data.original.origin.item.pricePerDose",
    "data.original.origin.item.route",
    "status",
]

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

from collections.abc import Mapping


def _get_nested_value(data, path):
    keys = path.split(".")
    for key in keys:
        if isinstance(data, Mapping) and key in data:
            data = data[key]
        elif isinstance(data, list) and key.isdigit():
            data = data[int(key)]
        else:
            return None
    return data


def _compare_specific_fields(data1, data2, fields_to_compare):
    differences = {}

    for field in fields_to_compare:
        value1 = _get_nested_value(data1, field)
        value2 = _get_nested_value(data2, field)

        if value1 is None and value2 is None:
            continue
        elif value1 is None:
            differences[field] = ("Field not present in first JSON", value2)
        elif value2 is None:
            differences[field] = (value1, "Field not present in second JSON")
        elif value1 != value2:
            differences[field] = (value1, value2)

    return differences


def _compare_json_fields(json_str1, json_str2, fields_to_compare):

    return _compare_specific_fields(json_str1, json_str2, fields_to_compare)
