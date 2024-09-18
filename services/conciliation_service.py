from datetime import datetime
from sqlalchemy import desc

from models.main import db
from models.prescription import Prescription, User
from models.enums import FeatureEnum
from utils import status
from services import memory_service, prescription_agg_service, permission_service
from exception.validation_error import ValidationError


def create_conciliation(admission_number: int, user: User):
    if not memory_service.has_feature(
        FeatureEnum.CONCILIATION_EDIT.value
    ) or not permission_service.is_pharma(user):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    ref = prescription_agg_service.get_last_prescription(
        admission_number=admission_number
    )

    if ref == None:
        raise ValidationError(
            "Atendimento inválido", "errors.businessRules", status.HTTP_400_BAD_REQUEST
        )

    new_id = 90000000000000000 + prescription_agg_service.gen_agg_id(
        admission_number=admission_number,
        id_segment=ref.idSegment,
        pdate=datetime.today().date(),
    )

    prescription = (
        db.session.query(Prescription).filter(Prescription.id == new_id).first()
    )

    if prescription != None:
        raise ValidationError(
            "Já existe uma conciliação para este atendimento no dia atual. Somente uma conciliação por dia é permitida.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription = Prescription()

    prescription.id = new_id
    prescription.date = datetime.today().date()
    prescription.expire = datetime.today().date()
    prescription.idDepartment = ref.idDepartment
    prescription.idHospital = ref.idHospital
    prescription.admissionNumber = ref.admissionNumber
    prescription.idPatient = ref.idPatient
    prescription.prescriber = user.name
    prescription.concilia = "s"
    prescription.agg = None
    prescription.update = datetime.today()
    prescription.user = user.id

    db.session.add(prescription)
    db.session.flush()

    return prescription.id


def list_available(admission_number: int, user: User):
    if not memory_service.has_feature(FeatureEnum.CONCILIATION.value):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    results = (
        db.session.query(Prescription)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(Prescription.concilia != None)
        .order_by(desc(Prescription.date))
        .limit(5)
        .all()
    )

    c_list = []
    for p in results:
        c_list.append({"id": str(p.id), "date": p.date.isoformat(), "status": p.status})

    return c_list
