"""Unit tests for alert_protocol_service — protocol alert orchestration.

``utils/alert_protocol.py`` (the rule engine that evaluates a single protocol
config) is already covered by ``test_alerts_protocol.py``. The orchestration
layer around it had no coverage at all, and it owns three decisions that change
what a pharmacist sees on screen:

* **which protocols are fetched** — an aggregated prescription must be tested
  against ``PRESCRIPTION_AGG`` protocols, an individual one against
  ``PRESCRIPTION_INDIVIDUAL``; ``PRESCRIPTION_ALL`` and ``PRESCRIPTION_ITEM``
  always apply;
* **how drugs are grouped** — on an aggregated, non-CPOE prescription the
  protocols must run once per expire-date group, so a rule that needs two
  drugs together does not fire across days that never overlap;
* **where each alert lands** — item protocols go to the flat ``items`` list,
  every other protocol to its date bucket, and ``summary`` holds the set of
  protocol ids that fired anywhere.

The rule engine and the repository are replaced by stubs so these tests drive
the orchestration only — no database or request context is needed. The
``@has_permission`` gate is bypassed via ``__wrapped__``.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models.enums import ProtocolTypeEnum
from models.prescription import Patient, Prescription
from services import alert_protocol_service
from tests.utils import utils_test_prescription

# The undecorated business logic (skips the permission gate).
_find_protocols = alert_protocol_service.find_protocols.__wrapped__

_PRESCRIPTION_DATE = datetime(2024, 3, 10, 8, 0)


def _prescription(agg: bool, date: datetime = _PRESCRIPTION_DATE, id_segment: int = 1):
    """Build the minimal Prescription the service reads from."""
    prescription = Prescription()
    prescription.id = 1
    prescription.agg = agg
    prescription.idSegment = id_segment
    prescription.date = date

    return prescription


def _drug(id: int, expire_date=None, prescription_date=_PRESCRIPTION_DATE):
    """Build a prescription-drug row with the two date fields the grouping reads."""
    row = utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=id,
        dose=10,
        frequency=1,
    )

    # the mock row defaults both dates to "now"; set them explicitly, including
    # a null expire date, which the grouping treats as "use the drug's own date"
    return row._replace(expire=expire_date, prescription_date=prescription_date)


def _protocol(
    id: int, protocol_type: ProtocolTypeEnum, only_latest_expire_date: bool = None
):
    """Build an active-protocol row as returned by protocol_repository.

    ``only_latest_expire_date`` left as None reproduces a config stored before
    the field existed: the key is simply absent."""
    config = {"id": id}
    if only_latest_expire_date is not None:
        config["onlyLatestExpireDate"] = only_latest_expire_date

    return SimpleNamespace(
        id=id,
        protocol_type=protocol_type.value,
        config=config,
    )


def _fires_on_items(*drug_ids: int):
    """Alert callback of an item protocol: fires on the date groups holding one
    of the given prescription drug ids and reports them back in
    ``related_items``, the way the engine reports a combination match."""

    def fire(drugs):
        ids = [d[0].id for d in drugs if d[0].id in drug_ids]
        return {"message": "fired", "related_items": ids} if ids else None

    return fire


def _fires_on(*drug_ids: int):
    """Alert callback that fires only on the date groups holding one of the
    given prescription drug ids, so a test can activate a protocol in one
    expire date group and not in another."""

    def fire(drugs):
        ids = {d[0].id for d in drugs}
        return {"message": "fired"} if ids & set(drug_ids) else None

    return fire


class _FakeAlertProtocol:
    """Stand-in for the rule engine: replays a canned answer per protocol config.

    ``alerts_by_protocol`` maps a protocol config id to the alert dict the
    engine should return (``None`` for "protocol did not fire"), or to a
    callable receiving the drug group, for protocols that must fire in some
    date groups only. Every instance records the drug group it was built with,
    so tests can assert the grouping.
    """

    instances = []
    alerts_by_protocol = {}

    def __init__(self, drugs, exams, prescription, patient, cn_stats, **kwargs):
        self.drugs = drugs
        self.exams = exams
        self.prescription = prescription
        self.patient = patient
        self.cn_stats = cn_stats
        self.kwargs = kwargs
        _FakeAlertProtocol.instances.append(self)

    def get_protocol_alerts(self, protocol: dict):
        alert = _FakeAlertProtocol.alerts_by_protocol.get(protocol.get("id"))

        if callable(alert):
            alert = alert(self.drugs)

        # the real engine returns a fresh dict per call; copy so the service
        # writing "id" into it cannot leak between date groups
        return dict(alert) if alert else alert


@pytest.fixture
def fake_engine():
    """Patch the rule engine and reset its recordings between tests."""
    _FakeAlertProtocol.instances = []
    _FakeAlertProtocol.alerts_by_protocol = {}

    with patch.object(alert_protocol_service, "AlertProtocol", _FakeAlertProtocol):
        yield _FakeAlertProtocol


def _run(
    protocols,
    drug_list,
    prescription,
    is_cpoe=False,
    exams=None,
    cn_stats=None,
):
    """Invoke find_protocols with the repository and segment lookup patched."""
    user = SimpleNamespace(id=1, schema="demo")

    with patch.object(
        alert_protocol_service.protocol_repository,
        "get_active_protocols",
        return_value=protocols,
    ) as get_active_protocols, patch.object(
        alert_protocol_service.segment_service, "is_cpoe", return_value=is_cpoe
    ):
        result = _find_protocols(
            drug_list=drug_list,
            exams=exams if exams is not None else {},
            prescription=prescription,
            patient=Patient(),
            cn_stats=cn_stats if cn_stats is not None else {},
            protocol_extra_info=None,
            user_context=user,
        )

    return result, get_active_protocols


class TestSplitDrugsByDate:
    """alert_protocol_service.split_drugs_by_date

    Protocols must be evaluated inside a single expire-date group: two drugs
    that never overlap in time should not satisfy the same rule. Only an
    aggregated, non-CPOE prescription is split — everything else keeps one
    group keyed by the prescription date.
    """

    def test_non_agg_prescription_keeps_a_single_group(self):
        """An individual prescription is one group keyed by its own date"""
        prescription = _prescription(agg=False)
        drug_list = [_drug(1), _drug(2)]

        with patch.object(
            alert_protocol_service.segment_service, "is_cpoe", return_value=False
        ):
            groups = alert_protocol_service.split_drugs_by_date(
                drug_list=drug_list, prescription=prescription
            )

        assert groups == {"2024-03-10": drug_list}

    def test_cpoe_segment_keeps_a_single_group(self):
        """CPOE segments are never split, even when aggregated"""
        prescription = _prescription(agg=True)
        drug_list = [
            _drug(1, expire_date=datetime(2024, 3, 11, 12, 0)),
            _drug(2, expire_date=datetime(2024, 3, 12, 12, 0)),
        ]

        with patch.object(
            alert_protocol_service.segment_service, "is_cpoe", return_value=True
        ):
            groups = alert_protocol_service.split_drugs_by_date(
                drug_list=drug_list, prescription=prescription
            )

        assert groups == {"2024-03-10": drug_list}

    def test_agg_prescription_groups_by_expire_date(self):
        """Aggregated, non-CPOE: one bucket per expire date, in insertion order"""
        prescription = _prescription(agg=True)
        first = _drug(1, expire_date=datetime(2024, 3, 11, 23, 59))
        second = _drug(2, expire_date=datetime(2024, 3, 12, 23, 59))
        third = _drug(3, expire_date=datetime(2024, 3, 11, 6, 0))

        with patch.object(
            alert_protocol_service.segment_service, "is_cpoe", return_value=False
        ):
            groups = alert_protocol_service.split_drugs_by_date(
                drug_list=[first, second, third], prescription=prescription
            )

        assert groups == {
            "2024-03-11": [first, third],
            "2024-03-12": [second],
        }

    def test_drug_without_expire_date_falls_back_to_its_prescription_date(self):
        """A null expire date groups the drug under its own prescription date"""
        prescription = _prescription(agg=True)
        no_expire = _drug(
            1, expire_date=None, prescription_date=datetime(2024, 3, 15, 7, 0)
        )
        with_expire = _drug(2, expire_date=datetime(2024, 3, 16, 7, 0))

        with patch.object(
            alert_protocol_service.segment_service, "is_cpoe", return_value=False
        ):
            groups = alert_protocol_service.split_drugs_by_date(
                drug_list=[no_expire, with_expire], prescription=prescription
            )

        assert groups == {
            "2024-03-15": [no_expire],
            "2024-03-16": [with_expire],
        }

    def test_empty_drug_list_on_agg_prescription_yields_no_group(self):
        """No drugs means no date buckets at all"""
        prescription = _prescription(agg=True)

        with patch.object(
            alert_protocol_service.segment_service, "is_cpoe", return_value=False
        ):
            groups = alert_protocol_service.split_drugs_by_date(
                drug_list=[], prescription=prescription
            )

        assert groups == {}


@pytest.mark.usefixtures("fake_engine")
class TestFindProtocolsTypeSelection:
    """alert_protocol_service.find_protocols — which protocols are fetched

    An aggregated prescription and an individual one must not be tested against
    each other's protocol type, or a rule written for a daily aggregation would
    fire on a single prescription item (and vice-versa).
    """

    def test_agg_prescription_requests_agg_protocols(self):
        """agg=True asks for ALL + ITEM + AGG, never INDIVIDUAL"""
        _, get_active_protocols = _run(
            protocols=[], drug_list=[_drug(1)], prescription=_prescription(agg=True)
        )

        requested = get_active_protocols.call_args.kwargs["protocol_type_list"]
        assert requested == [
            ProtocolTypeEnum.PRESCRIPTION_ALL,
            ProtocolTypeEnum.PRESCRIPTION_ITEM,
            ProtocolTypeEnum.PRESCRIPTION_AGG,
        ]

    def test_individual_prescription_requests_individual_protocols(self):
        """agg=False asks for ALL + ITEM + INDIVIDUAL, never AGG"""
        _, get_active_protocols = _run(
            protocols=[], drug_list=[_drug(1)], prescription=_prescription(agg=False)
        )

        requested = get_active_protocols.call_args.kwargs["protocol_type_list"]
        assert requested == [
            ProtocolTypeEnum.PRESCRIPTION_ALL,
            ProtocolTypeEnum.PRESCRIPTION_ITEM,
            ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL,
        ]

    def test_protocols_are_fetched_for_the_user_schema(self):
        """The lookup is scoped to the requesting user's schema"""
        _, get_active_protocols = _run(
            protocols=[], drug_list=[_drug(1)], prescription=_prescription(agg=False)
        )

        assert get_active_protocols.call_args.kwargs["schema"] == "demo"

    def test_no_active_protocols_short_circuits(self, fake_engine):
        """With no protocols configured the engine is never built"""
        result, _ = _run(
            protocols=[], drug_list=[_drug(1)], prescription=_prescription(agg=False)
        )

        assert result == {}
        assert fake_engine.instances == []


class TestFindProtocolsResults:
    """alert_protocol_service.find_protocols — where each alert lands

    Item protocols feed the per-item list in the UI; every other protocol feeds
    the date bucket it fired in. ``summary`` is the de-duplicated set of
    protocol ids that fired anywhere, and is what drives the alert badge count.
    """

    def test_alert_is_placed_in_its_date_bucket_with_the_protocol_id(
        self, fake_engine
    ):
        """A non-item protocol alert lands under the group date, tagged with its id"""
        fake_engine.alerts_by_protocol = {7: {"message": "fired"}}

        result, _ = _run(
            protocols=[_protocol(7, ProtocolTypeEnum.PRESCRIPTION_ALL)],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=False),
        )

        assert result["2024-03-10"] == [{"message": "fired", "id": 7}]
        assert result["items"] == []
        assert result["summary"] == [7]

    def test_item_protocol_alert_goes_to_the_items_list(self, fake_engine):
        """An item protocol alert bypasses the date bucket"""
        fake_engine.alerts_by_protocol = {9: {"message": "item alert"}}

        result, _ = _run(
            protocols=[_protocol(9, ProtocolTypeEnum.PRESCRIPTION_ITEM)],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=False),
        )

        assert result["items"] == [{"message": "item alert", "id": 9}]
        assert result["2024-03-10"] == []
        assert result["summary"] == [9]

    def test_protocol_that_does_not_fire_is_skipped(self, fake_engine):
        """A protocol returning no alert leaves an empty bucket and no summary entry"""
        fake_engine.alerts_by_protocol = {11: None}

        result, _ = _run(
            protocols=[_protocol(11, ProtocolTypeEnum.PRESCRIPTION_ALL)],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=False),
        )

        assert result["2024-03-10"] == []
        assert result["items"] == []
        assert result["summary"] == []

    def test_each_date_group_is_evaluated_separately(self, fake_engine):
        """Every expire-date group gets its own engine instance and its own drugs"""
        fake_engine.alerts_by_protocol = {5: {"message": "fired"}}

        first = _drug(1, expire_date=datetime(2024, 3, 11, 10, 0))
        second = _drug(2, expire_date=datetime(2024, 3, 12, 10, 0))

        result, _ = _run(
            protocols=[_protocol(5, ProtocolTypeEnum.PRESCRIPTION_AGG)],
            drug_list=[first, second],
            prescription=_prescription(agg=True),
        )

        assert [instance.drugs for instance in fake_engine.instances] == [
            [first],
            [second],
        ]
        assert result["2024-03-11"] == [{"message": "fired", "id": 5}]
        assert result["2024-03-12"] == [{"message": "fired", "id": 5}]

    def test_protocol_firing_in_two_groups_is_summarised_once(self, fake_engine):
        """summary is a set of ids, so a repeat across date groups counts once"""
        fake_engine.alerts_by_protocol = {5: {"message": "fired"}}

        result, _ = _run(
            protocols=[_protocol(5, ProtocolTypeEnum.PRESCRIPTION_AGG)],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(2, expire_date=datetime(2024, 3, 12, 10, 0)),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == [5]

    def test_mixed_protocol_types_are_routed_independently(self, fake_engine):
        """Item and non-item protocols fired by the same group keep their targets"""
        fake_engine.alerts_by_protocol = {
            1: {"message": "all"},
            2: {"message": "item"},
            3: None,
        }

        result, _ = _run(
            protocols=[
                _protocol(1, ProtocolTypeEnum.PRESCRIPTION_ALL),
                _protocol(2, ProtocolTypeEnum.PRESCRIPTION_ITEM),
                _protocol(3, ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL),
            ],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=False),
        )

        assert result["2024-03-10"] == [{"message": "all", "id": 1}]
        assert result["items"] == [{"message": "item", "id": 2}]
        assert sorted(result["summary"]) == [1, 2]

    def test_engine_receives_the_prescription_context(self, fake_engine):
        """exams, cn_stats, prescription and patient are forwarded to the engine"""
        fake_engine.alerts_by_protocol = {1: None}
        exams = {"cr": {"value": 1.2}}
        cn_stats = {"dialysis": 1}
        prescription = _prescription(agg=False)

        _run(
            protocols=[_protocol(1, ProtocolTypeEnum.PRESCRIPTION_ALL)],
            drug_list=[_drug(1)],
            prescription=prescription,
            exams=exams,
            cn_stats=cn_stats,
        )

        instance = fake_engine.instances[0]
        assert instance.exams == exams
        assert instance.cn_stats == cn_stats
        assert instance.prescription is prescription

    def test_no_drugs_still_returns_the_base_structure(self, fake_engine):
        """An aggregated prescription with no drugs yields only items + summary"""
        fake_engine.alerts_by_protocol = {1: {"message": "fired"}}

        result, _ = _run(
            protocols=[_protocol(1, ProtocolTypeEnum.PRESCRIPTION_AGG)],
            drug_list=[],
            prescription=_prescription(agg=True),
        )

        assert result == {"items": [], "summary": []}
        assert fake_engine.instances == []


class TestOnlyLatestExpireDate:
    """config.onlyLatestExpireDate — reach the summary from current groups only

    An aggregated prescription is evaluated once per expire-date group and also
    carries drugs prescribed on previous days; ``summary`` feeds the
    prescription alert count. Some protocols only make sense against what is
    prescribed today, so the config can ask to be counted only when it fires on
    a group holding drugs whose prescription date is the aggregated prescription
    date. The protocol is still tested against every group and its alert still
    shows inside the group where it fired: the flag changes the summary alone.
    It is read per protocol, and a config without the key always reaches the
    summary.
    """

    @pytest.mark.parametrize(
        "config, expected",
        [
            (None, False),
            ({}, False),
            ({"id": 1}, False),
            ({"onlyLatestExpireDate": False}, False),
            ({"onlyLatestExpireDate": True}, True),
        ],
    )
    def test_flag_reading_defaults_to_false(self, config, expected):
        """A config without the key behaves as it did before the field existed"""
        assert alert_protocol_service.is_summary_restricted(config=config) is expected

    def test_flagged_protocol_firing_on_a_current_group_is_summarized(
        self, fake_engine
    ):
        """The newest expire date does not decide it: what counts is that the
        group holds drugs prescribed on the aggregated prescription date"""
        fake_engine.alerts_by_protocol = {5: _fires_on(1)}

        result, _ = _run(
            protocols=[
                _protocol(
                    5, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=True
                )
            ],
            drug_list=[
                # prescribed today, expires first
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                # left over from a previous day, expires later
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 12, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["2024-03-11"] == [{"message": "fired", "id": 5}]
        assert result["2024-03-12"] == []
        assert result["summary"] == [5]

    def test_flagged_protocol_firing_on_an_older_group_is_not_summarized(
        self, fake_engine
    ):
        """The alert is still reported inside the group of the previous day, but
        it does not count in the summary (which feeds the alert count)"""
        fake_engine.alerts_by_protocol = {5: _fires_on(2)}

        result, _ = _run(
            protocols=[
                _protocol(
                    5, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=True
                )
            ],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 12, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["2024-03-12"] == [{"message": "fired", "id": 5}]
        assert result["2024-03-11"] == []
        assert result["summary"] == []

    def test_a_group_mixing_dates_counts_as_current(self, fake_engine):
        """One drug of the prescription date is enough: the group is part of
        what is prescribed today"""
        fake_engine.alerts_by_protocol = {5: {"message": "fired"}}

        result, _ = _run(
            protocols=[
                _protocol(
                    5, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=True
                )
            ],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 11, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == [5]

    def test_unflagged_protocol_firing_on_an_older_group_is_summarized(
        self, fake_engine
    ):
        """Back compatibility: without the flag, firing anywhere counts"""
        fake_engine.alerts_by_protocol = {5: _fires_on(2)}

        result, _ = _run(
            protocols=[_protocol(5, ProtocolTypeEnum.PRESCRIPTION_AGG)],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 12, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["2024-03-12"] == [{"message": "fired", "id": 5}]
        assert result["summary"] == [5]

    def test_flag_is_read_per_protocol(self, fake_engine):
        """A flagged and an unflagged protocol coexist in the same prescription:
        both alert on the previous day group, only the unflagged one is counted"""
        fake_engine.alerts_by_protocol = {5: _fires_on(2), 6: _fires_on(2)}

        result, _ = _run(
            protocols=[
                _protocol(
                    5, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=True
                ),
                _protocol(
                    6, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=False
                ),
            ],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 12, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["2024-03-12"] == [
            {"message": "fired", "id": 5},
            {"message": "fired", "id": 6},
        ]
        assert result["summary"] == [6]

    def test_flagged_item_protocol_is_judged_by_its_own_item(self, fake_engine):
        """An item alert belongs to the items that matched it: the date of those
        items decides the summary, not the dates of the whole group"""
        fake_engine.alerts_by_protocol = {7: _fires_on_items(2)}

        result, _ = _run(
            protocols=[
                _protocol(
                    7, ProtocolTypeEnum.PRESCRIPTION_ITEM, only_latest_expire_date=True
                )
            ],
            drug_list=[
                # same expire date group, prescribed on different days
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 11, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        # the alert is reported, but the item it points at is not of today
        assert result["items"] == [
            {"message": "fired", "related_items": [2], "id": 7}
        ]
        assert result["summary"] == []

    def test_flagged_item_protocol_of_a_current_item_is_summarized(self, fake_engine):
        """The same group counts when the matched item is of the current date"""
        fake_engine.alerts_by_protocol = {7: _fires_on_items(1)}

        result, _ = _run(
            protocols=[
                _protocol(
                    7, ProtocolTypeEnum.PRESCRIPTION_ITEM, only_latest_expire_date=True
                )
            ],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 11, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == [7]

    def test_flagged_item_alert_without_related_items_falls_back_to_the_group(
        self, fake_engine
    ):
        """An item alert that reports no item cannot be attributed to one, so
        the group answers for it"""
        fake_engine.alerts_by_protocol = {7: {"message": "fired"}}

        result, _ = _run(
            protocols=[
                _protocol(
                    7, ProtocolTypeEnum.PRESCRIPTION_ITEM, only_latest_expire_date=True
                )
            ],
            drug_list=[_drug(1, prescription_date=datetime(2024, 3, 9, 8, 0))],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == []

    def test_flagged_item_alert_without_related_items_counts_on_a_current_group(
        self, fake_engine
    ):
        """The fallback is the group rule, not a refusal: an unattributable item
        alert still counts when the group is of the current date"""
        fake_engine.alerts_by_protocol = {7: {"message": "fired"}}

        result, _ = _run(
            protocols=[
                _protocol(
                    7, ProtocolTypeEnum.PRESCRIPTION_ITEM, only_latest_expire_date=True
                )
            ],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == [7]

    def test_unflagged_item_protocol_ignores_the_item_date(self, fake_engine):
        """Back compatibility: without the flag, an item alert always counts"""
        fake_engine.alerts_by_protocol = {7: _fires_on_items(2)}

        result, _ = _run(
            protocols=[_protocol(7, ProtocolTypeEnum.PRESCRIPTION_ITEM)],
            drug_list=[
                _drug(1, expire_date=datetime(2024, 3, 11, 10, 0)),
                _drug(
                    2,
                    expire_date=datetime(2024, 3, 11, 10, 0),
                    prescription_date=datetime(2024, 3, 9, 8, 0),
                ),
            ],
            prescription=_prescription(agg=True),
        )

        assert result["summary"] == [7]

    def test_single_group_prescription_is_unaffected(self, fake_engine):
        """An individual prescription has one group, holding its own drugs"""
        fake_engine.alerts_by_protocol = {5: {"message": "fired"}}

        result, _ = _run(
            protocols=[
                _protocol(
                    5,
                    ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL,
                    only_latest_expire_date=True,
                )
            ],
            drug_list=[_drug(1)],
            prescription=_prescription(agg=False),
        )

        assert result["2024-03-10"] == [{"message": "fired", "id": 5}]
        assert result["summary"] == [5]

    def test_cpoe_group_of_previous_days_only_is_not_summarized(self, fake_engine):
        """A cpoe prescription is a single group keyed by its own date, but its
        drugs may all come from previous days: the flag still applies"""
        fake_engine.alerts_by_protocol = {5: {"message": "fired"}}

        result, _ = _run(
            protocols=[
                _protocol(
                    5, ProtocolTypeEnum.PRESCRIPTION_AGG, only_latest_expire_date=True
                )
            ],
            drug_list=[_drug(1, prescription_date=datetime(2024, 3, 9, 8, 0))],
            prescription=_prescription(agg=True),
            is_cpoe=True,
        )

        assert result["2024-03-10"] == [{"message": "fired", "id": 5}]
        assert result["summary"] == []
