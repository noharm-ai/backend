from routes.utils import *

def to_dto(pd):
    pdWhiteList = bool(pd[6].whiteList) if pd[6] is not None else False

    return {
        'idPrescription': str(pd[0].idPrescription),
        'idPrescriptionDrug': str(pd[0].id),
        'idDrug': pd[0].idDrug,
        'drug': pd[1].name if pd[1] is not None else 'Medicamento ' + str(pd[0].idDrug),
        'dose': pd[0].dose,
        'measureUnit': { 'value': pd[2].id, 'label': pd[2].description } if pd[2] else '',
        'frequency': { 'value': pd[3].id, 'label': pd[3].description } if pd[3] else '',
        'dayFrequency': pd[0].frequency,
        'doseconv': pd[0].doseconv,
        'time': timeValue(pd[0].interval),
        'interval': pd[0].interval,
        'route': pd[0].route,
        'score': str(pd[5]) if not pdWhiteList and pd[0].source != 'Dietas' else '0',
        'np': pd[6].notdefault if pd[6] is not None else False,
        'am': pd[6].antimicro if pd[6] is not None else False,
        'av': pd[6].mav if pd[6] is not None else False,
        'c': pd[6].controlled if pd[6] is not None else False,
        'q': pd[6].chemo if pd[6] is not None else False,
        'alergy': bool(pd[0].allergy == 'S'),
        'allergy': bool(pd[0].allergy == 'S'),
        'whiteList': pdWhiteList,
    }