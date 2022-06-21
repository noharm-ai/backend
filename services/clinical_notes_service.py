from models.main import db

from models.appendix import *
from models.notes import ClinicalNotes
from models.prescription import *
from services import memory_service, exams_service

from exception.validation_error import ValidationError

def create_clinical_notes(data, user):
    if not memory_service.has_feature('PRIMARYCARE'):
        raise ValidationError(\
            'Usuário não autorizado', 'errors.unauthorizedUser', status.HTTP_401_UNAUTHORIZED\
        )

    date = data.get('date', None)
    user_complete = db.session.query(User).get(user.id)
    cn = ClinicalNotes()
    
    cn.id = get_next_id(user.schema)
    cn.admissionNumber = data.get('admissionNumber', None)
    cn.date = datetime.today() if date == None else date
    cn.text = data.get('notes', None)
    cn.prescriber = user_complete.name
    cn.update = datetime.today()
    cn.user = user.id
    cn.position = 'Agendamento' if data.get('action', None) == 'schedule' else 'Farmacêutica'
    cn.form = data.get('formValues', None)
    cn.template = data.get('template', None)

    db.session.add(cn)
    db.session.flush()

    # route data
    if cn.template != None:
        prescription = Prescription.query.get(data.get('idPrescription'))

        for group in cn.template:
            for q in group['questions']:
                if 'integration' in q:
                    if q['integration']['to'] == 'exams' and q["id"] in cn.form and cn.form[q["id"]] != None:
                        exams_service.create_exam(\
                            admission_number = data.get('admissionNumber', None),\
                            id_prescription = prescription.id,\
                            id_patient = prescription.idPatient,\
                            type_exam = q["id"],\
                            value = cn.form[q["id"]],\
                            unit = q['integration']['unit'],\
                            user = user\
                        )

    return cn.id

def get_next_id(schema):
    result = db.session.execute("SELECT NEXTVAL('" + schema + ".evolucao_fkevolucao_seq')")

    return ([row[0] for row in result])[0]