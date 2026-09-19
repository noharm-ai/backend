"""Integration tests for the prioritization filters of ``GET /prescriptions``.

The pharmacist work queue is a single query built by
``prioritization_repository._build_base_query``: every panel filter of the
prioritization screen adds one more ``WHERE`` clause to it. The suite reached
only a handful of them (segment, pending, agg and concilia), so most clauses
— the ones reading the ``indicadores`` JSON, the patient columns and the
aggregated department/drug arrays — were never executed against PostgreSQL.
That matters more than a coverage number here: these clauses build raw JSON
paths, array overlaps, regex matches and casts that only fail when the
database actually runs them.

The fixture creates one prescription that every filter should select
(``_MATCH``) and one that every filter should reject (``_OTHER``), plus the
three shapes that live behind a flag — two aggregated prescriptions, one
pending and one reviewed, and a conciliation. All of them are dated on
``_DATE``, a day no seed row and no other test module uses, so a request for
that single day returns this module's rows and nothing else and each
assertion can compare the whole result set.

Prescriptions are inserted through the ORM so ``trg_complete_prescricao``
runs as it would in production (it resolves the segment from the department
and ignores the columns it does not carry), then the columns the trigger
drops — ``status``, the features JSON, the aggregated arrays, the specialty
and the clinical note — are written with a follow-up ``UPDATE``.
"""

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from models.prescription import Patient
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import create_prescription
from utils import status

# A day of its own: seed prescriptions are dated 2020-12-30/31, 2021-01-01 or
# "now", and every other module creates its rows around the current date.
_DATE = datetime(2021, 3, 10, 10, 0)
_DATE_PARAM = "2021-03-10"

_SEGMENT = 1
_DEPARTMENT_MATCH = 1
_DEPARTMENT_OTHER = 2
# in aggDeps but not the prescription's own department: tells the two
# department filters apart
_DEPARTMENT_AGGREGATED_ONLY = 9

# ids reserved for this module (>= 100000, cleaned by clean_test_artifacts)
_MATCH = 991000
_OTHER = 991001
_AGG_PENDING = 991002
_AGG_REVIEWED = 991003
_CONCILIA = 991004

_ADMISSION_MATCH = 991000
_ADMISSION_OTHER = 991001
_PATIENT_MATCH = 991000
_PATIENT_OTHER = 991001

_ALL_PRESCRIPTIONS = [_MATCH, _OTHER, _AGG_PENDING, _AGG_REVIEWED, _CONCILIA]
_ALL_ADMISSIONS = [_ADMISSION_MATCH, _ADMISSION_OTHER]

_SUBSTANCE_MATCH = 991001
_SUBSTANCE_OTHER = 991002
_PROTOCOL_MATCH = 991077

_AGE_MATCH = 40
_AGE_OTHER = 5

_FEATURES_MATCH = {
    "globalScore": 80,
    "alertStats": {
        "interactions": {"it": 2, "dt": 0, "dm": 0, "iy": 0, "sl": 0, "rx": 0},
        "am": 1,
        "av": 0,
    },
    "drugAttributes": {"am": 1, "av": 0},
    "frequencies": ["ZZTFREQMATCH"],
    "substanceIDs": [_SUBSTANCE_MATCH],
    "substanceClassIDs": ["ZZTCLASSMATCH"],
    "intervals": ["08", "20"],
    "diff": 1,
    "alertLevel": "high",
    "interventions": 2,
    "protocolAlerts": [_PROTOCOL_MATCH],
}

_FEATURES_OTHER = {
    "globalScore": 10,
    "alertStats": {
        "interactions": {"it": 0, "dt": 0, "dm": 0, "iy": 0, "sl": 0, "rx": 0},
        "am": 0,
        "av": 0,
    },
    "drugAttributes": {"am": 0, "av": 0},
    "frequencies": ["ZZTFREQOUTRA"],
    "substanceIDs": [_SUBSTANCE_OTHER],
    "substanceClassIDs": ["ZZTCLASSOUTRA"],
    "intervals": ["14"],
    "diff": 0,
    "alertLevel": "low",
    "interventions": 0,
    "protocolAlerts": [],
}


def _years_ago(years: int) -> datetime:
    """Birthdate of someone that age today, on the 365-day year the filter uses."""
    return datetime.combine(
        date.today() - timedelta(days=365 * years + 30), datetime.min.time()
    )


def _create_patient(
    admission_number: int,
    id_patient: int,
    birthdate: datetime,
    tags: list,
    id_icd: str,
    city: str,
    responsible_physician: str,
    st_conciliation: int,
    discharge_date: datetime = None,
):
    """Insert the patient row the prioritization query outer-joins on."""
    patient = Patient()
    patient.admissionNumber = admission_number
    patient.idPatient = id_patient
    patient.idHospital = 1
    patient.admissionDate = _DATE - timedelta(days=5)
    patient.birthdate = birthdate
    patient.gender = "F"
    patient.tags = tags
    patient.id_icd = id_icd
    patient.city = city
    patient.responsiblePhysician = responsible_physician
    patient.st_conciliation = st_conciliation
    patient.dischargeDate = discharge_date

    session.add(patient)
    session_commit()

    return patient


def _complete_prescription(
    id_prescription: int,
    features: dict = None,
    agg_deps: list = None,
    agg_drugs: list = None,
    prescription_status: str = "0",
    specialty: str = None,
    notes: str = None,
    review_type: int = None,
):
    """Write the columns ``trg_complete_prescricao`` does not carry on insert."""
    session.execute(
        text(
            """
            UPDATE demo.prescricao
            SET
                status = :status,
                indicadores = CAST(:features AS json),
                aggsetor = CAST(:agg_deps AS bigint[]),
                aggmedicamento = CAST(:agg_drugs AS bigint[]),
                especialidade = :specialty,
                evolucao = :notes,
                tp_revisao = :review_type
            WHERE fkprescricao = :id
            """
        ),
        {
            "id": id_prescription,
            "status": prescription_status,
            "features": json.dumps(features) if features is not None else None,
            "agg_deps": agg_deps,
            "agg_drugs": agg_drugs,
            "specialty": specialty,
            "notes": notes,
            "review_type": review_type,
        },
    )
    session_commit()


def _cleanup():
    session.execute(
        text("DELETE FROM demo.prescricao WHERE fkprescricao = ANY(:ids)"),
        {"ids": _ALL_PRESCRIPTIONS},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = ANY(:ids)"),
        {"ids": _ALL_ADMISSIONS},
    )
    session_commit()


@pytest.fixture(scope="module", autouse=True)
def seed_prioritization_filters():
    """One prescription every filter selects, one every filter rejects."""
    _cleanup()

    _create_patient(
        admission_number=_ADMISSION_MATCH,
        id_patient=_PATIENT_MATCH,
        birthdate=_years_ago(_AGE_MATCH),
        tags=["ZZT-TAG-MATCH"],
        id_icd="C50",  # inside the ONCO group
        city="ZZT Cidade Match",
        responsible_physician="Ciclano de Tal",
        st_conciliation=1,  # PatientConciliationStatusEnum.CREATED
        discharge_date=None,
    )
    _create_patient(
        admission_number=_ADMISSION_OTHER,
        id_patient=_PATIENT_OTHER,
        birthdate=_years_ago(_AGE_OTHER),
        tags=["ZZT-TAG-OUTRA"],
        id_icd="Z000",  # outside every ICD group
        city="Outra Cidade",
        responsible_physician="Beltrano Medico",
        st_conciliation=0,  # PatientConciliationStatusEnum.PENDING
        discharge_date=_DATE + timedelta(days=1),
    )

    create_prescription(
        id=_MATCH,
        admissionNumber=_ADMISSION_MATCH,
        idPatient=_PATIENT_MATCH,
        idDepartment=_DEPARTMENT_MATCH,
        idSegment=_SEGMENT,
        date=_DATE,
        bed="ZZT-101",
        record=987654,
        prescriber="Fulano Prescritor",
        insurance="ZZT Convenio Match",
    )
    _complete_prescription(
        _MATCH,
        features=_FEATURES_MATCH,
        agg_deps=[_DEPARTMENT_MATCH, _DEPARTMENT_AGGREGATED_ONLY],
        agg_drugs=[3, 4],
        prescription_status="0",
        specialty="ZZT Cardiologia",
        notes="anotacao de evolucao",
    )

    create_prescription(
        id=_OTHER,
        admissionNumber=_ADMISSION_OTHER,
        idPatient=_PATIENT_OTHER,
        idDepartment=_DEPARTMENT_OTHER,
        idSegment=_SEGMENT,
        date=_DATE,
        bed="ZZT-202",
        record=123456,
        prescriber="Beltrano Prescritor",
        insurance="Outro Convenio",
    )
    _complete_prescription(
        _OTHER,
        features=_FEATURES_OTHER,
        agg_deps=[_DEPARTMENT_OTHER],
        agg_drugs=[5],
        prescription_status="s",
        specialty="ZZT Ortopedia",
        notes=None,
    )

    for id_prescription, review_type in (
        (_AGG_PENDING, 0),
        (_AGG_REVIEWED, 1),
    ):
        create_prescription(
            id=id_prescription,
            admissionNumber=_ADMISSION_MATCH,
            idPatient=_PATIENT_MATCH,
            idDepartment=_DEPARTMENT_MATCH,
            idSegment=_SEGMENT,
            date=_DATE,
            agg=True,
        )
        _complete_prescription(
            id_prescription, features=_FEATURES_MATCH, review_type=review_type
        )

    create_prescription(
        id=_CONCILIA,
        admissionNumber=_ADMISSION_MATCH,
        idPatient=_PATIENT_MATCH,
        idDepartment=_DEPARTMENT_MATCH,
        idSegment=_SEGMENT,
        date=_DATE,
        concilia="s",
    )
    _complete_prescription(_CONCILIA, features=_FEATURES_MATCH)

    yield

    _cleanup()


def _ids(client, headers, query: str = "", day: str = _DATE_PARAM):
    """Prescription ids returned by the prioritization list for a single day."""
    response = client.get(
        f"/prescriptions?startDate={day}{query}",
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK

    return {int(item["idPrescription"]) for item in response.get_json()["data"]}


def test_the_day_returns_only_this_module_rows(client, analyst_headers):
    """Without filters the day holds the two plain prescriptions [200]"""
    assert _ids(client, analyst_headers) == {_MATCH, _OTHER}


class TestSegmentAndDepartment:
    """Where the prescription is: segment, department and aggregated departments"""

    def test_id_segment(self, client, analyst_headers):
        """idSegment keeps the segment, and an unknown one empties the list"""
        assert _ids(client, analyst_headers, "&idSegment=1") == {_MATCH, _OTHER}
        assert _ids(client, analyst_headers, "&idSegment=2") == set()

    def test_id_segment_list(self, client, analyst_headers):
        """idSegment[] accepts more than one segment"""
        assert _ids(client, analyst_headers, "&idSegment[]=1&idSegment[]=2") == {
            _MATCH,
            _OTHER,
        }

    def test_department_matches_the_aggregated_departments(
        self, client, analyst_headers
    ):
        """idDept[] reads aggsetor, so a department only visited earlier counts"""
        assert _ids(
            client, analyst_headers, f"&idDept[]={_DEPARTMENT_AGGREGATED_ONLY}"
        ) == {_MATCH}

    def test_current_department_matches_the_prescription_department(
        self, client, analyst_headers
    ):
        """currentDepartment switches the same filter to the fksetor column"""
        assert (
            _ids(
                client,
                analyst_headers,
                f"&idDept[]={_DEPARTMENT_AGGREGATED_ONLY}&currentDepartment=true",
            )
            == set()
        )
        assert _ids(
            client,
            analyst_headers,
            f"&idDept[]={_DEPARTMENT_MATCH}&currentDepartment=true",
        ) == {_MATCH}


class TestDrugs:
    """Which drugs the prescription aggregates"""

    def test_id_drug_overlaps_by_default(self, client, analyst_headers):
        """idDrug[] keeps a prescription carrying any of the drugs"""
        assert _ids(client, analyst_headers, "&idDrug[]=3&idDrug[]=5") == {
            _MATCH,
            _OTHER,
        }

    def test_all_drugs_requires_every_drug(self, client, analyst_headers):
        """allDrugs turns the overlap into containment"""
        assert _ids(
            client, analyst_headers, "&idDrug[]=3&idDrug[]=4&allDrugs=true"
        ) == {_MATCH}
        assert (
            _ids(client, analyst_headers, "&idDrug[]=3&idDrug[]=5&allDrugs=true")
            == set()
        )


class TestPrescriptionShape:
    """Columns of the prescription itself"""

    def test_pending(self, client, analyst_headers):
        """pending keeps the prescriptions still to be evaluated"""
        assert _ids(client, analyst_headers, "&pending=true") == {_MATCH}

    def test_agg(self, client, analyst_headers):
        """agg swaps the plain prescriptions for the aggregated ones"""
        assert _ids(client, analyst_headers, "&agg=true") == {
            _AGG_PENDING,
            _AGG_REVIEWED,
        }

    def test_patient_review_type_only_applies_to_aggregated(
        self, client, analyst_headers
    ):
        """patientReviewType splits the aggregated list in two"""
        assert _ids(client, analyst_headers, "&agg=true&patientReviewType=0") == {
            _AGG_PENDING
        }
        assert _ids(client, analyst_headers, "&agg=true&patientReviewType=1") == {
            _AGG_REVIEWED
        }

    def test_concilia(self, client, analyst_headers):
        """concilia reaches the conciliation, which no other request returns"""
        assert _ids(client, analyst_headers, "&concilia=true") == {_CONCILIA}

    def test_insurance(self, client, analyst_headers):
        """insurance matches part of the plan name"""
        assert _ids(client, analyst_headers, "&insurance=Convenio Match") == {_MATCH}

    def test_prescriber(self, client, analyst_headers):
        """prescriber matches part of the prescriber name"""
        assert _ids(client, analyst_headers, "&prescriber=Fulano") == {_MATCH}

    def test_bed_list(self, client, analyst_headers):
        """bedList[] matches any of the beds, blanks aside"""
        assert _ids(client, analyst_headers, "&bedList[]=ZZT-101&bedList[]= ") == {
            _MATCH
        }

    def test_specialty_list(self, client, analyst_headers):
        """specialtyList[] matches part of the specialty"""
        assert _ids(client, analyst_headers, "&specialtyList[]=Cardio") == {_MATCH}

    def test_medical_record(self, client, analyst_headers):
        """medical_record is an exact match on the record number"""
        assert _ids(client, analyst_headers, "&medical_record=987654") == {_MATCH}

    def test_medical_record_list(self, client, analyst_headers):
        """medicalRecordList[] takes several record numbers at once"""
        assert _ids(
            client, analyst_headers, "&medicalRecordList[]=987654&medicalRecordList[]=1"
        ) == {_MATCH}

    def test_has_clinical_notes(self, client, analyst_headers):
        """hasClinicalNotes tells the prescriptions with an evolution apart"""
        assert _ids(client, analyst_headers, "&hasClinicalNotes=true") == {_MATCH}
        assert _ids(client, analyst_headers, "&hasClinicalNotes=false") == {_OTHER}


class TestFeaturesJson:
    """Counters and lists the prescalc leaves in the ``indicadores`` JSON"""

    def test_indicators_on_an_interaction(self, client, analyst_headers):
        """indicators[] reads the interaction counters one level deeper"""
        assert _ids(client, analyst_headers, "&indicators[]=it") == {_MATCH}
        assert _ids(client, analyst_headers, "&indicators[]=dt") == set()

    def test_indicators_outside_the_interactions(self, client, analyst_headers):
        """a non-interaction indicator is read straight off alertStats"""
        assert _ids(client, analyst_headers, "&indicators[]=am") == {_MATCH}

    def test_drug_attributes(self, client, analyst_headers):
        """drugAttributes[] reads its own counter block"""
        assert _ids(client, analyst_headers, "&drugAttributes[]=am") == {_MATCH}
        assert _ids(client, analyst_headers, "&drugAttributes[]=av") == set()

    def test_frequencies(self, client, analyst_headers):
        """frequencies[] matches the serialized frequency list"""
        assert _ids(client, analyst_headers, "&frequencies[]=ZZTFREQMATCH") == {_MATCH}

    def test_substances(self, client, analyst_headers):
        """substances[] asks the substance id list to contain the id"""
        assert _ids(client, analyst_headers, f"&substances[]={_SUBSTANCE_MATCH}") == {
            _MATCH
        }

    def test_substance_classes(self, client, analyst_headers):
        """substanceClasses[] does the same with the class list"""
        assert _ids(client, analyst_headers, "&substanceClasses[]=ZZTCLASSMATCH") == {
            _MATCH
        }

    def test_intervals(self, client, analyst_headers):
        """intervals[] matches any administration hour"""
        assert _ids(client, analyst_headers, "&intervals[]=20") == {_MATCH}

    def test_first_administration_hour(self, client, analyst_headers):
        """first_administration_hour[] only looks at the first one"""
        assert _ids(client, analyst_headers, "&first_administration_hour[]=08") == {
            _MATCH
        }
        assert (
            _ids(client, analyst_headers, "&first_administration_hour[]=20") == set()
        )

    def test_diff(self, client, analyst_headers):
        """diff splits the prescriptions that changed from the ones that did not"""
        assert _ids(client, analyst_headers, "&diff=true") == {_MATCH}
        assert _ids(client, analyst_headers, "&diff=false") == {_OTHER}

    def test_alert_level(self, client, analyst_headers):
        """alertLevel is an exact match on the worst alert of the prescription"""
        assert _ids(client, analyst_headers, "&alertLevel=high") == {_MATCH}
        assert _ids(client, analyst_headers, "&alertLevel=low") == {_OTHER}

    def test_pending_interventions(self, client, analyst_headers):
        """pendingInterventions splits by the intervention counter"""
        assert _ids(client, analyst_headers, "&pendingInterventions=true") == {_MATCH}
        assert _ids(client, analyst_headers, "&pendingInterventions=false") == {_OTHER}

    def test_global_score_range(self, client, analyst_headers):
        """globalScoreMin/Max bound the score the list is ordered by"""
        assert _ids(client, analyst_headers, "&globalScoreMin=50") == {_MATCH}
        assert _ids(client, analyst_headers, "&globalScoreMax=50") == {_OTHER}
        assert _ids(
            client, analyst_headers, "&globalScoreMin=0&globalScoreMax=100"
        ) == {_MATCH, _OTHER}

    def test_protocols(self, client, analyst_headers):
        """protocols[] asks the protocol alert list to contain the protocol"""
        assert _ids(client, analyst_headers, f"&protocols[]={_PROTOCOL_MATCH}") == {
            _MATCH
        }


class TestPatientColumns:
    """Columns of the patient the prescription is outer-joined to"""

    def test_id_patient(self, client, analyst_headers):
        """idPatient[] filters by the patient behind the prescription"""
        assert _ids(client, analyst_headers, f"&idPatient[]={_PATIENT_MATCH}") == {
            _MATCH
        }

    def test_id_patient_by_name_list(self, client, analyst_headers):
        """idPatientByNameList[] is the same filter fed by the name search"""
        assert _ids(
            client, analyst_headers, f"&idPatientByNameList[]={_PATIENT_MATCH}"
        ) == {_MATCH}

    def test_patient_status(self, client, analyst_headers):
        """patientStatus reads the discharge date"""
        assert _ids(client, analyst_headers, "&patientStatus=ACTIVE") == {_MATCH}
        assert _ids(client, analyst_headers, "&patientStatus=DISCHARGED") == {_OTHER}

    def test_has_conciliation(self, client, analyst_headers):
        """hasConciliation reads the patient conciliation status"""
        assert _ids(client, analyst_headers, "&hasConciliation=true") == {_MATCH}
        assert _ids(client, analyst_headers, "&hasConciliation=false") == {_OTHER}

    def test_tags(self, client, analyst_headers):
        """tags[] overlaps the patient tag array"""
        assert _ids(client, analyst_headers, "&tags[]=ZZT-TAG-MATCH") == {_MATCH}

    def test_city(self, client, analyst_headers):
        """city matches part of the patient city"""
        assert _ids(client, analyst_headers, "&city=Cidade Match") == {_MATCH}

    def test_responsible_physician_list(self, client, analyst_headers):
        """responsiblePhysicianList[] matches part of the physician name"""
        assert _ids(client, analyst_headers, "&responsiblePhysicianList[]=Ciclano") == {
            _MATCH
        }

    def test_age_range(self, client, analyst_headers):
        """ageMin/ageMax bound the patient age, counted in 365-day years"""
        assert _ids(client, analyst_headers, "&ageMin=30") == {_MATCH}
        assert _ids(client, analyst_headers, "&ageMax=10") == {_OTHER}
        assert _ids(client, analyst_headers, "&ageMin=1&ageMax=100") == {
            _MATCH,
            _OTHER,
        }

    def test_id_icd_list(self, client, analyst_headers):
        """idIcdList[] matches the diagnosis exactly"""
        assert _ids(client, analyst_headers, "&idIcdList[]=C50") == {_MATCH}
        assert _ids(client, analyst_headers, "&idIcdList[]=Z000") == {_OTHER}

    def test_id_icd_group_list(self, client, analyst_headers):
        """idIcdGroupList[] expands a group into all of its codes"""
        assert _ids(client, analyst_headers, "&idIcdGroupList[]=ONCO") == {_MATCH}
        assert _ids(client, analyst_headers, "&idIcdGroupList[]=DIABETES") == set()

    def test_unknown_icd_group_is_ignored(self, client, analyst_headers):
        """an unknown group name adds no code, so it filters nothing out"""
        assert _ids(client, analyst_headers, "&idIcdGroupList[]=ZZTGROUP") == {
            _MATCH,
            _OTHER,
        }


class TestDateWindow:
    """The date range every request is bounded by"""

    def test_end_date_widens_the_window(self, client, analyst_headers):
        """endDate extends the day into a range"""
        assert _ids(
            client, analyst_headers, "&endDate=2021-03-20", day="2021-03-01"
        ) == {_MATCH, _OTHER}

    def test_a_day_before_returns_nothing(self, client, analyst_headers):
        """the window is closed on both ends"""
        assert _ids(client, analyst_headers, day="2021-03-09") == set()

    def test_a_window_over_120_days_is_rejected(self, client, analyst_headers):
        """more than 120 days would hold the database for too long [400]"""
        response = client.get(
            "/prescriptions?startDate=2021-01-01&endDate=2021-12-31",
            headers=analyst_headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_prioritization_requires_read_prescription(client, user_manager_headers):
    """the work queue is closed to a role without READ_PRESCRIPTION [401]"""
    response = client.get(
        f"/prescriptions?startDate={_DATE_PARAM}", headers=user_manager_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
