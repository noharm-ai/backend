from flask_api import status
from datetime import date, datetime, timedelta
import unicodedata

def data2age(birthdate):
    if birthdate is None: return ''

    days_in_year = 365.2425
    birthdate = birthdate.split('T')[0]
    birthdate = datetime.strptime(birthdate, '%Y-%m-%d')
    age = int ((datetime.today() - birthdate).days / days_in_year)
    return age

def data2month(birthdate):
    if birthdate is None: return ''

    month_in_year = 12
    birthdate = birthdate.split('T')[0]
    birthdate = datetime.strptime(birthdate, '%Y-%m-%d')
    age = int ((datetime.today() - birthdate).months / month_in_year)
    return age

def lenghStay(admissionDate):
    if admissionDate is None: return ''

    days = int ((datetime.today() - admissionDate).days)
    return days

def is_float(s):
    try:
        float(s)
        return True
    except:
        return False

def timeValue(time):
    numeric = str(time).strip().replace(' ','')
    if not is_float(numeric): return strNone(time).strip()
    else:
      timeList = str(time).strip().split(' ')
      if len(timeList) == 1:
        return 'Às ' + str(time).strip() + ' Horas'
      elif len(timeList) < 6:
        return 'às ' + ('h, às ').join(timeList) + 'h'
      else:
        return time

def freqValue(freq):
    if freq == 33: return 'SN'
    elif freq == 44: return 'ACM'
    elif freq == 99: return 'N/D'
    else: return freq

def none2zero(s):
    return s if is_float(s) else 0

def strNone(s):
    return '' if s is None else str(s)

def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    only_ascii = nfkd_form.encode('ASCII', 'ignore')
    return only_ascii

def sortRelations(r):
  return remove_accents(r['nameB'])

def sortSubstance(s):
  return remove_accents(s['name'])

def interactionsList(drugList, splitStr):
    result = []
    for d in drugList:
        part = d.split(splitStr)
        result.append({'name': part[0], 'idDrug': part[1]})

    return result

typeRelations = {}
typeRelations['dm'] = 'Duplicidade Medicamentosa'
typeRelations['dt'] = 'Duplicidade Terapêutica'
typeRelations['it'] = 'Interação Medicamentosa'
typeRelations['iy'] = 'Incompatibilidade em Y'
typeRelations['rx'] = 'Reatividade Cruzada'

examsNameX = {
    'cr':  'Creatinina',
    'mdrd':'MDRD',
    'cg':  'CG',
    'ckd': 'CKD-EPI',
    'pcru': 'PCR',
    'pcr': 'PCR',
    'rni': 'RNI',
    'pro': 'RNI',
    'tgo': 'TGO',
    'tgp': 'TGP',
    'k':   'Potássio',
    'na':  'Sódio',
    'mg':  'Magnésio',
    'h_eritr': 'Eritócitos',
    'h_hematoc': 'Hematócrito',
    'h_hemogl': 'Hemoglobina',
    'h_plt': 'Plaquetas',
    'h_vcm': 'V.C.M.',
    'h_hcm': 'H.C.M.',
    'h_chcm': 'C.H.C.M.',
    'h_rdw': 'R.D.W.',
    'h_conleuc': 'Leucóticos',
    'h_conbaso': 'Basófilos',
    'h_coneos': 'Eosinófilos',
    'h_consegm': 'Neutrófitos',
    'h_conlinfoc': 'Linfócitos',
    'h_conmono': 'Monócitos',
}

examsRefX = {
    'tgo': { 'min': 0,   'max': 34,  'ref': 'até 34 U/L - Método: Cinético optimizado UV' },
    'tgp': { 'min': 0,   'max': 49,  'ref': '10 a 49 U/L - Método: Cinético optimizado UV' },
    'k':   { 'min': 3.5, 'max': 5.5, 'ref': '3,5 a 5,5 mEq/L - Método: Eletrodo Seletivo' },
    'na':  { 'min': 132, 'max': 146, 'ref': '132 a 146 mEq/L - Método: Eletrodo Seletivo' },
    'mg':  { 'min': 1.3, 'max': 2.7, 'ref': '1,3 a 2,7 mg/dl - Método: Clorofosfonazo III 1' },
    'rni': { 'min': 0,   'max': 1.3, 'ref': 'até 1,3 - Método: Coagulométrico automatizado ACL TOP 550' },
    'pro': { 'min': 0,   'max': 1.3, 'ref': 'até 1,3 - Método: Coagulométrico automatizado ACL TOP 550' },
    'cr':  { 'min': 0.3, 'max': 1.3, 'ref': '0,3 a 1,3 mg/dL (IFCC)' },
    'pcr': { 'min': 0,   'max': 3,   'ref': 'até 3,0 mg/L' },
    'pcru':{ 'min': 0,   'max': 3,   'ref': 'até 3,0 mg/L' },
    'h_plt':        { 'min': 150000, 'max': 440000},
    'h_vcm':        { 'min': 80,     'max': 98},
    'h_rdw':        { 'min': 0,      'max': 15},
    'h_hcm':        { 'min': 28,     'max': 32},
    'h_chcm':       { 'min': 32,     'max': 36},
    'h_hematoc':    { 'min': 39,     'max': 53},
    'h_hemogl':     { 'min': 12.8,   'max': 17.8},
    'h_eritr':      { 'min': 4.5,    'max': 6.1},
    'h_conleuc':    { 'min': 3600,   'max': 11000},
    'h_conlinfoc':  { 'min': 1000,   'max': 4500},
    'h_conmono':    { 'min': 100,    'max': 1000},
    'h_coneos':     { 'min': 0,      'max': 500},
    'h_conbaso':    { 'min': 0,      'max': 220},
    'h_consegm':    { 'min': 1500,   'max': 7000},
}

examEmpty = { 'value': None, 'alert': False, 'ref': None, 'name': None }

def examAlerts(p, patient):
    exams = {'tgo': p[7], 'tgp': p[8], 'cr': p[9], 'k': p[10], 'na': p[11], 'mg': p[12], 'rni': p[13], 'pcr': p[22]}
    exams['mdrd'] = mdrd_calc(str(p[9]), patient.birthdate, patient.gender, patient.skinColor)
    exams['cg'] = cg_calc(str(p[9]), patient.birthdate, patient.gender, patient.weight)
    exams['ckd'] = ckd_calc(str(p[9]), patient.birthdate, patient.gender, patient.skinColor)

    result = {}
    alertCount = 0
    for e in exams:
        value = exams[e]
        
        if value is None: 
            result[e] = examEmpty
        else:
            if e in ['mdrd', 'cg', 'ckd']:
                result[e] = value
                alertCount += int(value['alert'])
            else:            
                ref = examsRefX[e]
                alert = not (value >= ref['min'] and value <= ref['max'] )
                alertCount += int(alert)
                result[e] = { 'value': value, 'alert': alert }

    return result['tgo'], result['tgp'], result['cr'], result['mdrd'], result['cg'],\
            result['k'], result['na'], result['mg'], result['rni'],\
            result['pcr'], result['ckd'], alertCount

def examAlertsList(exams, patient, segExams):
    valueExams = {}
    for e in exams:
        typeExam, value = e.split('|')
        valueExams[typeExam.lower()] = value

    results = []
    alertCount = 0
    for typeExam in segExams:
        ref = segExams[typeExam]

        if typeExam.lower() in valueExams:
            value = float(valueExams[typeExam.lower()])
            alert = not (value >= ref.min and value <= ref.max)
            alertCount += int(alert)
            results.append({
                'key': typeExam.lower(),
                'value': { 'value':value, 'ref':ref.ref , 'alert':alert, 'name':ref.name }
            })

            if ref.name.lower() == 'creatinina':
                if data2age(patient.birthdate.isoformat()) > 17:
                    valueMDRD = mdrd_calc(value, patient.birthdate, patient.gender, patient.skinColor)
                    results.append({
                        'key': 'mdrd',
                        'value': valueMDRD
                    })
                    alertCount += int(valueMDRD['alert'])

                    valueCG = cg_calc(value, patient.birthdate, patient.gender, patient.weight)
                    results.append({
                        'key': 'cg',
                        'value': valueCG
                    })
                    alertCount += int(valueCG['alert'])

                    valueCKD = ckd_calc(value, patient.birthdate, patient.gender, patient.skinColor)
                    results.append({
                        'key': 'ckd',
                        'value': valueCKD
                    })
                    alertCount += int(valueCKD['alert'])
                else:
                    valueSWRTZ2 = schwartz2_calc(value, patient.height)
                    results.append({
                        'key': 'swrtz2',
                        'value': valueSWRTZ2
                    })
                    alertCount += int(valueSWRTZ2['alert'])

        else:
            examTypeEmpty = dict(examEmpty, **{'initials': ref.initials, 'name': ref.name})
            results.append({
                'key': typeExam.lower(),
                'value': examTypeEmpty
            })
            if ref.name.lower() == 'creatinina':
                if data2age(patient.birthdate.isoformat()) > 17:
                    results.append({
                        'key': 'mdrd',
                        'value': dict(examEmpty, **{'initials': 'MDRD', 'name': 'MDRD'})
                    })
                    results.append({
                        'key': 'cg',
                        'value': dict(examEmpty, **{'initials': 'CG', 'name': 'CG'})
                    })
                    results.append({
                        'key': 'ckd',
                        'value': dict(examEmpty, **{'initials': 'CKD', 'name': 'CKD'})
                    })
                else:
                    results.append({
                        'key': 'swrtz2',
                        'value': dict(examEmpty, **{'initials': 'Schwartz 2', 'name': 'Schwartz 2'})
                    })

        if len(results) == 8:
            break

    return results, alertCount

class refEmpty():
    ref = initials = min = max = name = ''

def formatExam(exam, typeExam, segExam):
    if exam is not None:
        if typeExam in segExam:
            ref = segExam[typeExam]
            alert = not (exam.value >= ref.min and exam.value <= ref.max )
        else:
            ref = refEmpty()
            ref.name = typeExam
            ref.initials = typeExam
            alert = False

        return { 'value': float(exam.value), 'unit': strNone(exam.unit), 'alert': alert,\
                 'date' : exam.date.isoformat(), 'ref': ref.ref, 'initials': ref.initials,
                 'min': ref.min, 'max': ref.max, 'name': ref.name }
    else:
        examEmpty['date'] = None
        return examEmpty

def period(tuples):
    if len(tuples) > 0:
        last30 = (datetime.today() - timedelta(days=30))
        last = datetime.strptime(tuples[0].split(' ')[0]+'/'+str(last30.year), '%d/%m/%Y')
        more = last < last30

        dates = list(set([t.split(' ')[0] for t in tuples]))

        return ('+' if more else '') + str(len(dates)) + 'D'
    else:
        return '0D'

# Modification of Diet in Renal Disease
# based on https://www.kidney.org/content/mdrd-study-equation
# eGFR = 175 x (SCr)-1.154 x (age)-0.203 x 0.742 [if female] x 1.212 [if Black]
def mdrd_calc(cr, birthdate, gender, skinColor):
    if not is_float(cr): return dict(examEmpty, **{'initials': 'MDRD', 'name': 'MDRD'})
    if birthdate is None: return dict(examEmpty, **{'initials': 'MDRD', 'name': 'MDRD'})
    
    age = data2age(birthdate.isoformat())
    if age == 0: return dict(examEmpty, **{'initials': 'MDRD', 'name': 'MDRD'})

    eGFR = 175 * (float(cr))**(-1.154) * (age)**(-0.203)

    if gender == 'F': eGFR *= 0.742
    if skinColor == 'Negra': eGFR *= 1.212


    return { 'value': round(eGFR,1), 'ref': 'maior que 50 mL/min', 'unit': 'mL/min',
             'alert': (eGFR < 50), 'name': 'Modification of Diet in Renal Disease', 'initials': 'MDRD' }

# Cockcroft-Gault
# based on https://www.kidney.org/professionals/KDOQI/gfr_calculatorCoc
# CCr = {((140–age) x weight)/(72xSCr)} x 0.85 (if female)
def cg_calc(cr, birthdate, gender, weight):
    if not is_float(cr): return dict(examEmpty, **{'initials': 'CG', 'name': 'CG'})
    if not is_float(weight): return dict(examEmpty, **{'initials': 'CG', 'name': 'CG'})
    if birthdate is None: return dict(examEmpty, **{'initials': 'CG', 'name': 'CG'})

    age = data2age(birthdate.isoformat())
    if age == 0: return dict(examEmpty, **{'initials': 'CG', 'name': 'CG'})

    ccr = ((140 - age) * float(weight)) / (72 * float(cr))
    if gender == 'F': ccr *= 0.85

    return { 'value': round(ccr,1), 'ref': 'maior que 50 mL/min', 'unit': 'mL/min',
             'alert': (ccr < 50), 'name': 'Cockcroft-Gault', 'initials': 'CG'}

# Chronic Kidney Disease Epidemiology Collaboration
# based on https://www.kidney.org/professionals/kdoqi/gfr_calculator
def ckd_calc(cr, birthdate, gender, skinColor):
    if not is_float(cr): return dict(examEmpty, **{'initials': 'CKD', 'name': 'CKD'})
    if birthdate is None: return dict(examEmpty, **{'initials': 'CKD', 'name': 'CKD'})

    age = data2age(birthdate.isoformat())
    if age == 0: return dict(examEmpty, **{'initials': 'CKD', 'name': 'CKD'})

    if gender == 'F':
        g = 0.7
        s = 166 if skinColor == 'Negra' else 144
        e = -1.209 if float(cr) > g else -0.329
    else:
        g = 0.9
        s = 163 if skinColor == 'Negra' else 141
        e = -1.209 if float(cr) > g else -0.411

    eGFR = s * (float(cr)/g)**(e) * (0.993)**(age)

    return { 'value': round(eGFR,1), 'ref': 'maior que 50 mL/min', 'unit': 'mL/min',
             'alert': (eGFR < 50), 'name': 'Chronic Kidney Disease Epidemiology' , 'initials': 'CKD'}

# Schwartz (2) Formula
# based on https://link.springer.com/article/10.1007%2Fs00467-014-3002-5
def schwartz2_calc(cr, height):
    if not is_float(cr): return dict(examEmpty, **{'initials': 'Schwartz 2', 'name': 'Schwartz 2'})
    if not is_float(height): return dict(examEmpty, **{'initials': 'Schwartz 2', 'name': 'Schwartz 2'})

    eGFR = (0.413 * height) / cr

    return { 'value': round(eGFR,1), 'ref': 'maior que 75 mL/min por 1.73 m²', 'unit': 'mL/min',
             'alert': (eGFR < 75), 'name': 'Schwartz 2' , 'initials': 'Schwartz 2'}

def tryCommit(db, recId):
    try:
        db.session.commit()

        return {
            'status': 'success',
            'data': recId
        }, status.HTTP_200_OK
    except AssertionError as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.engine.dispose()

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR