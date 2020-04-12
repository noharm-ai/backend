from datetime import date, datetime

def data2age(birthdate):
    days_in_year = 365.2425
    birthdate = datetime.strptime(birthdate, '%Y-%m-%d')
    age = int ((datetime.today() - birthdate).days / days_in_year)
    return age

def is_float(s):
    try:
        float(s)
        return True
    except:
        return False

def none2zero(s):
    return s if is_float(s) else ''

def formatExam(exam):
    if exam is not None:
        examDate = exam.date.strftime('%d/%m/%Y %H:%M')
        return str(exam.value) + ' ' + exam.unit + ' (' +  examDate + ')'
    else:
        return ''

# Modification of Diet in Renal Disease
# based on https://www.kidney.org/content/mdrd-study-equation
# eGFR = 175 x (SCr)-1.154 x (age)-0.203 x 0.742 [if female] x 1.212 [if Black]
def mdrd_calc(cr, birthdate, gender, skinColor):
    if not is_float(cr): return ''
    
    age = data2age(birthdate)
    if age == 0: return ''

    eGFR = 175 * (float(cr))**(-1.154) * (age)**(-0.203)

    if gender == 'F': eGFR *= 0.742
    if skinColor == 'Negra': eGFR *= 1.212

    return round(eGFR,1)

# Cockcroft-Gault
# based on https://www.kidney.org/professionals/KDOQI/gfr_calculatorCoc
# CCr = {((140–age) x weight)/(72xSCr)} x 0.85 (if female)
def cg_calc(cr, birthdate, gender, weight):
    if not is_float(cr): return ''
    if not is_float(weight): return ''

    age = data2age(birthdate)
    if age == 0: return ''

    ccr = ((140 - age) * float(weight)) / (72 * float(cr))
    if gender == 'F': ccr *= 0.85

    return round(ccr,1)