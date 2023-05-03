from models.main import db

from models.appendix import *
from models.prescription import *
from routes.utils import validate

from exception.validation_error import ValidationError

def get_interventions(admissionNumber=None, startDate=None, endDate=None):
    mReasion = db.aliased(InterventionReason)
    descript = case([(
                        mReasion.description != None,
                        func.concat(mReasion.description, ' - ',InterventionReason.description)
                    ),],
                    else_=InterventionReason.description)

    reason = db.session.query(descript)\
            .select_from(InterventionReason)\
            .outerjoin(mReasion, mReasion.id == InterventionReason.mamy)\
            .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))\
            .as_scalar()

    splitStr = '!?'
    dr1 = db.aliased(Drug)
    interactions = db.session.query(func.concat(dr1.name, splitStr, dr1.id))\
            .select_from(dr1)\
            .filter(dr1.id == func.any(Intervention.interactions))\
            .as_scalar()

    PrescriptionB = db.aliased(Prescription)
    DepartmentB = db.aliased(Department)
    interventions = db.session\
        .query(Intervention, PrescriptionDrug, 
                func.array(reason).label('reason'), Drug.name, 
                func.array(interactions).label('interactions'),
                MeasureUnit, Frequency, Prescription, User.name, 
                Department.name, PrescriptionB.prescriber, DepartmentB.name)\
        .outerjoin(PrescriptionDrug, Intervention.id == PrescriptionDrug.id)\
        .outerjoin(Prescription, Intervention.idPrescription == Prescription.id)\
        .outerjoin(PrescriptionB, PrescriptionDrug.idPrescription == PrescriptionB.id)\
        .outerjoin(Drug, Drug.id == PrescriptionDrug.idDrug)\
        .outerjoin(MeasureUnit, and_(MeasureUnit.id == PrescriptionDrug.idMeasureUnit, MeasureUnit.idHospital == PrescriptionB.idHospital))\
        .outerjoin(Frequency, and_(Frequency.id == PrescriptionDrug.idFrequency, Frequency.idHospital == PrescriptionB.idHospital))\
        .outerjoin(User, User.id == Intervention.user)\
        .outerjoin(Department, and_(Department.id == PrescriptionB.idDepartment, Department.idHospital == PrescriptionB.idHospital))\
        .outerjoin(DepartmentB, and_(DepartmentB.id == Prescription.idDepartment, DepartmentB.idHospital == Prescription.idHospital))

    if admissionNumber:
        interventions = interventions.filter(Intervention.admissionNumber == admissionNumber)
    else:
        #interventions = interventions.filter(Intervention.date > (date.today() - timedelta(days=60)))
        if not startDate:
            raise ValidationError('Data inicial inválida', 'errors.invalidRequest', status.HTTP_400_BAD_REQUEST)

    if startDate is not None:
        interventions = interventions.filter(Intervention.date > validate(startDate))

    interventions = interventions.filter(Intervention.status.in_(['s','a','n','x','j']))\
                                    .order_by(desc(Intervention.date))
    
    print("||||||", interventions)
    print("|||||||")

    interventions = interventions.limit(1500).all()
    
    intervBuffer = []
    for i in interventions:
        intervBuffer.append({
            'id': str(i[0].id),
            'idSegment': i[1].idSegment if i[1] else i[7].idSegment if i[7] else None,
            'idInterventionReason': i[0].idInterventionReason,
            'reasonDescription': (', ').join(i[2]),
            'idPrescription': str(i[1].idPrescription if i[1] else i[0].idPrescription),
            'idDrug': i[1].idDrug if i[1] else None,
            'drugName': i[3] if i[3] is not None else 'Medicamento ' + str(i[1].idDrug) if i[1] else 'Intervenção no Paciente',
            'dose': i[1].dose if i[1] else None,
            'measureUnit': { 'value': i[5].id, 'label': i[5].description } if i[5] else '',
            'frequency': { 'value': i[6].id, 'label': i[6].description } if i[6] else '',
            'time': timeValue(i[1].interval) if i[1] else None,
            'route': i[1].route if i[1] else 'None',
            'admissionNumber': i[0].admissionNumber,
            'observation': i[0].notes,
            'error': i[0].error,
            'cost': i[0].cost,
            'interactionsDescription': (', ').join([ d.split(splitStr)[0] for d in i[4] ] ),
            'interactionsList': interactionsList(i[4], splitStr),
            'interactions': i[0].interactions,
            'date': i[0].date.isoformat(),
            'user': i[8],
            'department': i[9] if i[9] else i[11],
            'prescriber': i[10] if i[10] else i[7].prescriber if i[7] else None,
            'status': i[0].status,
            'transcription':i[0].transcription,
            'economyDays': i[0].economy_days,
            'expendedDose': i[0].expended_dose
        })

    result = [i for i in intervBuffer if i['status'] == 's']
    result.extend([i for i in intervBuffer if i['status'] != 's'])

    return result