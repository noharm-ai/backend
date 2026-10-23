"""Unit tests for the direct allergy alert (alert_service.is_allergic).

The allergy flag of a prescribed item (presmed.alergia) is set by the
integration when the item arrives. The patient's allergy records (alergia)
confirm it: an active record of the item raises the alert even without the
flag, a record of the item that was inactivated drops it, and with no record of
the item the flag stands (some clients have no allergy records at all).

A record is of the item by its fkmedicamento when it is the same drug, or by
its substance: its sctid when it has one, otherwise the substance of its
fkmedicamento.
"""

from collections import namedtuple
from datetime import datetime

import pytest

from models.enums import AllergyRecordStatusEnum, DrugAlertTypeEnum
from services import alert_service, prescription_view_service
from tests.utils import utils_test_prescription

AllergyRecord = namedtuple("AllergyRecord", "idDrug sctid drugSctid active")

_ID_DRUG = 1  # get_prescription_drug_mock_row prescribes drug 1
_SCTID = 90201
_OTHER_SCTID = 90202


def _row(allergy: str | None, id_prescription_drug: int = 71):
    """A prescribed item of drug 1, substance _SCTID"""
    return utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=id_prescription_drug,
        dose=10,
        allergy=allergy,
        sctid=_SCTID,
    )


def _is_allergic(allergy: str | None, allergies: list | None) -> bool:
    row = _row(allergy=allergy)
    return alert_service.is_allergic(
        prescription_drug=row[0], drug=row[1], allergies=allergies
    )


def _allergy_alerts(rows: list, allergies: list | None) -> dict:
    alerts = alert_service.find_alerts(
        drug_list=rows,
        exams={"age": 50, "weight": 80},
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=None,
        is_cpoe=False,
        allergies=allergies,
    )

    return {
        key: [a for a in items if a["type"] == DrugAlertTypeEnum.ALLERGY.value]
        for key, items in alerts["alerts"].items()
    }


@pytest.mark.parametrize("allergies", [None, []])
@pytest.mark.parametrize("flag, expected", [("S", True), ("N", False), (None, False)])
def test_without_records_the_flag_stands(flag, expected, allergies):
    """No record (or records not fetched): the integration flag decides"""
    assert _is_allergic(flag, allergies) is expected


@pytest.mark.parametrize("flag", ["S", "N", None])
@pytest.mark.parametrize(
    "record",
    [
        AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=True),
        AllergyRecord(idDrug=99001, sctid=None, drugSctid=_SCTID, active=True),
        AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=True),
    ],
    ids=["same_drug", "drug_of_same_substance", "sctid"],
)
def test_an_active_record_of_the_item_confirms_the_allergy(flag, record):
    """Recorded after the item arrived: allergic whatever the flag says"""
    assert _is_allergic(flag, [record]) is True


@pytest.mark.parametrize(
    "record",
    [
        AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=False),
        AllergyRecord(idDrug=99001, sctid=None, drugSctid=_SCTID, active=False),
        AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=False),
    ],
    ids=["same_drug", "drug_of_same_substance", "sctid"],
)
def test_an_inactivated_record_of_the_item_drops_the_flag(record):
    """The allergy was inactivated after the item arrived"""
    assert _is_allergic("S", [record]) is False


def test_an_active_record_wins_over_an_inactive_one():
    """The same substance recorded twice: one active record is enough"""
    allergies = [
        AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=False),
        AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=True),
    ]

    assert _is_allergic(None, allergies) is True


def test_records_of_other_items_keep_the_flag():
    """Allergies to other substances neither confirm nor drop the flag"""
    allergies = [
        AllergyRecord(idDrug=99001, sctid=_OTHER_SCTID, drugSctid=None, active=True),
        AllergyRecord(idDrug=99002, sctid=None, drugSctid=_OTHER_SCTID, active=False),
        AllergyRecord(idDrug=99003, sctid=None, drugSctid=None, active=False),
    ]

    assert _is_allergic("S", allergies) is True
    assert _is_allergic(None, allergies) is False


def test_the_record_sctid_is_trusted_over_the_substance_of_its_fkmedicamento():
    """When the record has a sctid, the substance of another drug in its
    fkmedicamento does not make it the item's"""
    inactive = AllergyRecord(
        idDrug=99001, sctid=_OTHER_SCTID, drugSctid=_SCTID, active=False
    )
    active = AllergyRecord(
        idDrug=99001, sctid=_OTHER_SCTID, drugSctid=_SCTID, active=True
    )

    assert _is_allergic("S", [inactive]) is True
    assert _is_allergic(None, [active]) is False


def test_the_same_drug_matches_even_with_a_stale_sctid():
    """The job copies the drug's sctid only into recent records: a record of
    the same drug whose substance changed afterwards is still the item's"""
    inactive = AllergyRecord(
        idDrug=_ID_DRUG, sctid=_OTHER_SCTID, drugSctid=_SCTID, active=False
    )
    active = AllergyRecord(
        idDrug=_ID_DRUG, sctid=_OTHER_SCTID, drugSctid=_SCTID, active=True
    )

    assert _is_allergic("S", [inactive]) is False
    assert _is_allergic(None, [active]) is True


def test_a_record_without_status_neither_confirms_nor_drops():
    """ativo is nullable: a record without a status is ignored"""
    record = AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=None)

    assert _is_allergic("S", [record]) is True
    assert _is_allergic(None, [record]) is False


def test_an_item_without_drug_only_matches_by_fkmedicamento():
    """An item whose drug is not registered has no substance to compare"""
    row = _row(allergy=None)
    by_sctid = AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=True)
    by_drug = AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=True)

    assert (
        alert_service.is_allergic(
            prescription_drug=row[0], drug=None, allergies=[by_sctid]
        )
        is False
    )
    assert (
        alert_service.is_allergic(
            prescription_drug=row[0], drug=None, allergies=[by_drug]
        )
        is True
    )


def _record_status(allergy: str | None, allergies: list | None):
    row = _row(allergy=allergy)
    return alert_service.get_allergy_record_status(
        prescription_drug=row[0], drug=row[1], allergies=allergies
    )


@pytest.mark.parametrize("flag", ["S", "N", None])
def test_the_record_status_says_why_the_flag_was_kept_or_overridden(flag):
    """The maintainers read it next to the flag: the records decide only when
    there is a record of the item, whatever the flag says"""
    active = AllergyRecord(idDrug=_ID_DRUG, sctid=None, drugSctid=None, active=True)
    inactive = AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=False)
    other = AllergyRecord(idDrug=99002, sctid=_OTHER_SCTID, drugSctid=None, active=True)

    assert _record_status(flag, [active]) is AllergyRecordStatusEnum.ACTIVE
    assert _record_status(flag, [inactive, active]) is AllergyRecordStatusEnum.ACTIVE
    assert _record_status(flag, [inactive]) is AllergyRecordStatusEnum.INACTIVE
    assert _record_status(flag, [other]) is None
    assert _record_status(flag, []) is None
    assert _record_status(flag, None) is None


def test_find_alerts_raises_the_allergy_alert_from_the_records():
    """The alert follows the records: raised without the flag, dropped with it"""
    rows = [
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=81, dose=10, allergy=None, sctid=_SCTID
        ),
        utils_test_prescription.get_prescription_drug_mock_row(
            id_prescription_drug=82, dose=10, allergy="S", sctid=_OTHER_SCTID
        ),
    ]
    allergies = [
        AllergyRecord(idDrug=99001, sctid=_SCTID, drugSctid=None, active=True),
        AllergyRecord(idDrug=99002, sctid=_OTHER_SCTID, drugSctid=None, active=False),
    ]

    alerts = _allergy_alerts(rows, allergies)

    assert len(alerts.get("81", [])) == 1
    assert alerts["81"][0]["level"] == "high"
    assert alerts["81"][0]["text"] == "Paciente alérgico a este medicamento."
    assert alerts.get("82", []) == []


def test_find_alerts_without_records_keeps_the_flag():
    """Callers that do not fetch the records keep the flag behaviour"""
    rows = [_row(allergy="S", id_prescription_drug=83)]

    assert len(_allergy_alerts(rows, None).get("83", [])) == 1


ListedRecord = namedtuple("ListedRecord", "name active createdAt")


def test_the_listed_records_are_one_per_name_dated_by_the_latest():
    """Only information on the screen: active, named, alphabetical, the latest
    date of each name"""
    listed = prescription_view_service._list_allergy_records(
        allergies=[
            ListedRecord("Sulfa", True, datetime(2026, 1, 1)),
            ListedRecord("Dipirona", True, datetime(2026, 2, 1)),
            ListedRecord("Sulfa", True, datetime(2026, 3, 1)),
            ListedRecord("Sulfa", True, None),
            ListedRecord("Penicilina", False, datetime(2026, 3, 1)),
            ListedRecord("Ativo nulo", None, datetime(2026, 3, 1)),
            ListedRecord("  ", True, datetime(2026, 3, 1)),
            ListedRecord(None, True, datetime(2026, 3, 1)),
        ]
    )

    assert listed == [
        {"date": "2026-02-01T00:00:00", "text": "Dipirona", "source": "pep"},
        {"date": "2026-03-01T00:00:00", "text": "Sulfa", "source": "pep"},
    ]


def test_the_listed_records_are_cut_at_the_limit():
    """The alert reads every record; the list on the screen is truncated"""
    allergies = [
        ListedRecord(f"Alergia {i:03d}", True, datetime(2026, 1, 1)) for i in range(150)
    ]

    listed = prescription_view_service._list_allergy_records(allergies=allergies)

    assert len(listed) == prescription_view_service._ALLERGY_RECORDS_LIMIT
    assert listed[0]["text"] == "Alergia 000"
