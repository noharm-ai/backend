import pytest, json
from mobile import app
from models.main import User
from unittest.mock import patch
from flask_jwt_extended import create_access_token

from models.prescription import (
    Prescription,
    PrescriptionDrug,
    DrugAttributes,
    Drug,
    Frequency,
    PrescriptionAudit,
)

from collections import namedtuple
from datetime import datetime, timedelta

from config import Config
import sqlalchemy
from sqlalchemy.orm import sessionmaker

engine = sqlalchemy.create_engine(Config.POTGRESQL_CONNECTION_STRING)
DBSession = sessionmaker(bind=engine)
session = DBSession()
session.connection(execution_options={"schema_translate_map": {None: "demo"}})

with app.test_request_context():
    access_token = create_access_token("1")


def make_headers(jwt):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer {}".format(jwt),
    }


def user_find(id):
    user = User()
    user.schema = "demo"
    return user


def setSchema(schema):
    return schema


def session_commit():
    session.commit()
    session.connection(execution_options={"schema_translate_map": {None: "demo"}})


@pytest.fixture
def client():
    client = app.test_client()
    yield client


def get_access(client, email="demo", password="demo", roles=["suporte"]):
    mimetype = "application/json"
    headers = {"Content-Type": mimetype, "Accept": mimetype}
    data = {"email": email, "password": password}
    url = "/authenticate"

    update_roles(email, roles)

    response = client.post(url, data=json.dumps(data), headers=headers)
    my_json = response.data.decode("utf8").replace("'", '"')
    data_response = json.loads(my_json)
    access_token = data_response["access_token"]
    return access_token


def update_roles(email, roles):
    user = session.query(User).filter_by(email=email).first()
    if user != None:
        user.config = {"roles": roles}
        session_commit()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    test_fn = item.obj
    docstring = getattr(test_fn, "__doc__")
    if docstring:
        report.nodeid = docstring


def prepareTestAggregate(id, admissionNumber, prescriptionid1, prescriptionid2):
    """Deleção da prescrição agregada já existente."""

    session.query(Prescription).filter(Prescription.id == id).delete()
    session_commit()

    """Deleção dos registros das prescrições."""

    session.query(PrescriptionAudit).filter(
        PrescriptionAudit.admissionNumber == admissionNumber
    ).delete()
    session_commit()

    """Mudança para status 0 nas prescrições id=4 e id=7."""

    session.query(Prescription).filter(
        Prescription.id.in_([prescriptionid1, prescriptionid2])
    ).update({"status": "0"}, synchronize_session="fetch")
    session_commit()


MockRow = namedtuple(
    "Mockrow",
    "prescription_drug drug measure_unit frequency not_used score drug_attributes notes prevnotes status expire substance period_cpoe prescription_date measure_unit_convert_factor substance_handling_types",
)


def get_mock_row(
    id_prescription_drug: int,
    dose: float,
    frequency: float = None,
    max_dose: float = None,
    kidney: float = None,
    liver: float = None,
    platelets: float = None,
    elderly: bool = None,
    tube: bool = None,
    allergy: str = None,
    drug_name: str = "Test2",
    pregnant: str = None,
    lactating: str = None,
    interval: str = None,
    freq_obj: Frequency = None,
    use_weight: bool = False,
    expire_date: datetime = None,
):
    d = Drug()
    d.id = id_prescription_drug
    d.name = drug_name
    d.sctid = f"{id_prescription_drug}11111"  # Generate a unique sctid

    pd = PrescriptionDrug()
    pd.id = id_prescription_drug
    pd.source = "Medicamentos"
    pd.idDrug = 1
    pd.frequency = frequency
    pd.doseconv = dose
    pd.tube = tube
    pd.allergy = allergy
    pd.interval = interval
    pd.intravenous = False

    da = DrugAttributes()
    da.idDrug = id_prescription_drug
    da.idSegment = 1
    da.maxDose = max_dose
    da.kidney = kidney
    da.liver = liver
    da.platelets = platelets
    da.elderly = elderly
    da.tube = tube
    da.pregnant = pregnant
    da.lactating = lactating
    da.fasting = True
    da.useWeight = use_weight

    return MockRow(
        pd,
        d,
        None,
        freq_obj,
        None,
        None,
        da,
        None,
        None,
        None,
        expire_date or datetime.now() + timedelta(days=1),
        None,
        0,
        datetime.now(),
        1,
        [],
    )
