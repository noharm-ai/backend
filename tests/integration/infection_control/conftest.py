"""Tests: infection control follow-up (ci_* tables)

An admission with a running antimicrobial is followed: prescalc creates its
record as pending and never reviewed (or reopens a closed one); the rule
(applied by the scheduled job in backend-private, the review save and the
backfill) opens one reason per drug without an evaluation and follows stops,
new drugs and discharge, expired evaluations, posology changes (when the
evaluation watches for them) and scheduled review dates; the infectologist's
review evaluates drugs, settles reasons and sets the status (pending while a
reason is open, revised when none is left, closed when no antimicrobial is
running anymore).

Seed data used (demo schema): drug 1 (AMPICILINA + SULBACTAM) is antimicrobial
on segment 1, drug 4 (BISACODIL) is not; the ``second_antimicrobial`` fixture
flags drug 4 as antimicrobial to have two drugs. Segment 2 is the CPOE segment;
the ``cpoe_antimicrobial`` fixture flags drug 1 as antimicrobial there too.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.enums import FeatureEnum
from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit
from tests.integration.infection_control.helpers import (
    ADULT_SEGMENT,
    ANTIMICROBIAL_DRUG,
    CPOE_SEGMENT,
    OTHER_DRUG,
    PATIENT_ID,
)
from tests.utils.utils_test_prescription import test_counters


def _read_features():
    row = session.execute(
        text("SELECT valor FROM demo.memoria WHERE tipo = 'features'")
    ).first()
    return list(row[0]) if row else []


def _write_features(features):
    session.execute(
        text(
            "UPDATE demo.memoria SET valor = CAST(:value AS json) WHERE tipo = 'features'"
        ),
        {"value": json.dumps(features)},
    )
    session_commit()


@pytest.fixture
def infection_control():
    """Enable INFECTION_CONTROL for the demo schema"""
    original = _read_features()
    _write_features(original + [FeatureEnum.INFECTION_CONTROL.value])
    yield
    _write_features(original)


@pytest.fixture
def admission():
    """A synthetic patient admitted ten days ago"""
    admission_number = test_counters["admission_number"]
    test_counters["admission_number"] += 1

    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkpessoa, nratendimento, dtinternacao, dtnascimento, sexo, peso) "
            "VALUES (:id_patient, :admission, :admission_date, '1970-05-04', 'F', 70)"
        ),
        {
            "id_patient": PATIENT_ID,
            "admission": admission_number,
            "admission_date": datetime.now() - timedelta(days=10),
        },
    )
    session_commit()

    yield admission_number

    for table in (
        "ci_pendencia",
        "ci_avaliacao_atm",
        "ci_revisao",
        "ci_atendimento",
        "pessoa",
        "pessoa_audit",
    ):
        session.execute(
            text(f"DELETE FROM demo.{table} WHERE nratendimento = :admission"),
            {"admission": admission_number},
        )
    session_commit()


def _flag_antimicrobial(id_drug, id_segment, value):
    session.execute(
        text(
            "UPDATE demo.medatributos SET antimicro = :value "
            "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
        ),
        {"value": value, "id_drug": id_drug, "id_segment": id_segment},
    )
    session_commit()


@pytest.fixture
def second_antimicrobial():
    """Flag drug 4 as antimicrobial on the adult segment"""
    _flag_antimicrobial(OTHER_DRUG, ADULT_SEGMENT, True)
    yield OTHER_DRUG
    _flag_antimicrobial(OTHER_DRUG, ADULT_SEGMENT, False)


@pytest.fixture
def cpoe_antimicrobial():
    """Flag the antimicrobial drug on the CPOE segment as well"""
    session.execute(
        text(
            "INSERT INTO demo.medatributos (fkmedicamento, idsegmento, antimicro) "
            "VALUES (:id_drug, :id_segment, true)"
        ),
        {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
    )
    session_commit()

    yield

    for table in ("medatributos_audit", "medatributos"):
        session.execute(
            text(
                f"DELETE FROM demo.{table} "
                "WHERE fkmedicamento = :id_drug AND idsegmento = :id_segment"
            ),
            {"id_drug": ANTIMICROBIAL_DRUG, "id_segment": CPOE_SEGMENT},
        )
    session_commit()


@pytest.fixture
def admin_utils_headers(client):
    """Headers with the ADMIN role (INTEGRATION_UTILS)"""
    return make_headers(get_access(client, roles=[Role.ADMIN.value]))
