from datetime import date, datetime, timedelta

def data2age(birthdate):
    if birthdate is None: return ''

    days_in_year = 365.2425
    birthdate = datetime.strptime(birthdate, '%Y-%m-%d')
    age = int ((datetime.today() - birthdate).days / days_in_year)
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

def none2zero(s):
    return s if is_float(s) else ''

def strNone(s):
    return '' if s is None else str(s)

examsRef = {
    'tgo': { 'min': 0,   'max': 37,  'ref': 'até 37 U/L - Método: Cinético optimizado UV' },
    'tgp': { 'min': 0,   'max': 41,  'ref': 'até 41 U/L - Método: Cinético optimizado UV' },
    'k':   { 'min': 3.5, 'max': 5,   'ref': '3,5 a 5,O mEq/L - Método: Eletrodo Seletivo' },
    'na':  { 'min': 135, 'max': 145, 'ref': '135 a 145 mEq/L - Método: Eletrodo Seletivo' },
    'mg':  { 'min': 1.7, 'max': 2.5, 'ref': '1,7 a 2,5 mg/dl - Método: Clorofosfonazo III 1' },
    'rni': { 'min': 0,   'max': 999, 'ref': 'até 1,3 - Método: Coagulométrico automatizado ACL TOP 550' },
    'cr':  { 'min': 0.5, 'max': 1.2, 'ref': 'Nas mulheres, entre 0,5 a 1,1 mg/dL.\nNos homens, entre 0,6 a 1,2 mg/dL' },
}

examEmpty = { 'value': None, 'alert': False, 'ref': None }

def examAlerts(p, patient):
    exams = {'tgo': p[7], 'tgp': p[8], 'k': p[10], 'na': p[11], 'mg': p[12], 'rni': p[13]}
    exams['mdrd'] = mdrd_calc(str(p[9]), patient.birthdate, patient.gender, patient.skinColor)
    exams['cg'] = cg_calc(str(p[9]), patient.birthdate, patient.gender, patient.weight)

    result = {}
    alertCount = 0
    for e in exams:
        value = exams[e]
        
        if value is None: 
            result[e] = examEmpty
        else:
            if e in ['mdrd', 'cg']:
                result[e] = value
                alertCount += int(value['alert'])
            else:            
                ref = examsRef[e]
                alert = not (value >= ref['min'] and value <= ref['max'] )
                alertCount += int(alert)
                result[e] = { 'value': value, 'alert': alert }

    return result['tgo'], result['tgp'], result['mdrd'], result['cg'],\
            result['k'], result['na'], result['mg'], result['rni'], alertCount

def formatExam(exam, type):
    if exam is not None:
        examDate = exam.date.strftime('%d/%m/%Y %H:%M')
        ref = examsRef[type]
        alert = not (exam.value >= ref['min'] and exam.value <= ref['max'] )
        return { 'value': str(exam.value) + ' ' + exam.unit, 'alert': alert,\
                      'date' :  examDate, 'ref': ref['ref']}
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
    if not is_float(cr): return examEmpty
    if birthdate is None: return examEmpty 
    
    age = data2age(birthdate.isoformat())
    if age == 0: return examEmpty

    eGFR = 175 * (float(cr))**(-1.154) * (age)**(-0.203)

    if gender == 'F': eGFR *= 0.742
    if skinColor == 'Negra': eGFR *= 1.212


    return { 'value': round(eGFR,1), 'ref': 'maior que 50 mL/min', 'alert': (eGFR < 50) }

# Cockcroft-Gault
# based on https://www.kidney.org/professionals/KDOQI/gfr_calculatorCoc
# CCr = {((140–age) x weight)/(72xSCr)} x 0.85 (if female)
def cg_calc(cr, birthdate, gender, weight):
    if not is_float(cr): return examEmpty
    if not is_float(weight): return examEmpty
    if birthdate is None: return examEmpty

    age = data2age(birthdate.isoformat())
    if age == 0: return examEmpty

    ccr = ((140 - age) * float(weight)) / (72 * float(cr))
    if gender == 'F': ccr *= 0.85

    return { 'value': round(ccr,1), 'ref': 'maior que 50 mL/min', 'alert': (ccr < 50) }