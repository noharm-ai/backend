"""Tests: protocol alert of a prescription item (alert_service._alert_protocol).

A protocol of the prescription item type answers, when it fires, with the ids of the
items that matched it (``related_items``). ``alert_service.find_alerts`` turns it into
a ``protocol`` alert on each of those items, carrying the protocol message (as escaped
HTML) and level. An item gets at most one protocol alert: the first protocol that
names it wins.
"""

from datetime import datetime

from services import alert_service
from tests.utils import utils_test_prescription


def _find_alerts(drugs: list, protocols):
    """Run find_alerts with neutral patient data and the given protocols."""
    return alert_service.find_alerts(
        drug_list=drugs,
        exams={"age": 50, "weight": 80},
        dialisys=None,
        pregnant=None,
        lactating=None,
        schedules_fasting=None,
        cn_data=None,
        protocols=protocols,
        is_cpoe=False,
    )


def _drug(id_prescription_drug: int):
    """A plain prescription item that raises no other alert."""
    return utils_test_prescription.get_prescription_drug_mock_row(
        id_prescription_drug=id_prescription_drug, dose=10, frequency=1
    )


def _protocol_alerts(result: dict, id_prescription_drug: int) -> list:
    """Protocol alerts of one item."""
    return [
        a
        for a in result["alerts"].get(str(id_prescription_drug), [])
        if a["type"] == "protocol"
    ]


def test_related_item_gets_the_protocol_alert():
    """The item named by the protocol gets an alert with its message and level"""
    protocols = [
        {"related_items": [71], "message": "Ajustar dose", "level": "high", "id": 1}
    ]

    result = _find_alerts([_drug(71)], protocols)

    alerts = _protocol_alerts(result, 71)
    assert len(alerts) == 1
    assert alerts[0]["idPrescriptionDrug"] == "71"
    assert alerts[0]["key"] == ""
    assert alerts[0]["text"] == "Ajustar dose"
    assert alerts[0]["level"] == "high"
    assert alerts[0]["handling"] is False
    assert result["stats"]["protocol"] == 1


def test_unrelated_items_get_no_protocol_alert():
    """Only the items in related_items are alerted"""
    protocols = [{"related_items": [72], "message": "Mensagem", "level": "medium"}]

    result = _find_alerts([_drug(72), _drug(73)], protocols)

    assert len(_protocol_alerts(result, 72)) == 1
    assert _protocol_alerts(result, 73) == []
    assert result["stats"]["protocol"] == 1


def test_one_protocol_can_alert_several_items():
    """Every related item gets its own alert"""
    protocols = [{"related_items": [74, 75], "message": "Duplicidade", "level": "low"}]

    result = _find_alerts([_drug(74), _drug(75)], protocols)

    assert len(_protocol_alerts(result, 74)) == 1
    assert len(_protocol_alerts(result, 75)) == 1
    assert result["stats"]["protocol"] == 2


def test_the_first_protocol_naming_the_item_wins():
    """An item named by two protocols gets one alert, from the first of them"""
    protocols = [
        {"related_items": [76], "message": "Primeiro", "level": "low"},
        {"related_items": [76], "message": "Segundo", "level": "high"},
    ]

    result = _find_alerts([_drug(76)], protocols)

    alerts = _protocol_alerts(result, 76)
    assert len(alerts) == 1
    assert alerts[0]["text"] == "Primeiro"
    assert alerts[0]["level"] == "low"


def test_a_protocol_without_related_items_alerts_no_item():
    """A protocol with no related_items (e.g. a prescription level one) alerts no item"""
    protocols = [{"message": "Sem itens", "level": "high"}]

    result = _find_alerts([_drug(77)], protocols)

    assert _protocol_alerts(result, 77) == []
    assert result["stats"]["protocol"] == 0


def test_level_defaults_to_low_and_message_to_empty():
    """Missing level and message fall back to "low" and an empty text"""
    protocols = [{"related_items": [78]}]

    result = _find_alerts([_drug(78)], protocols)

    alerts = _protocol_alerts(result, 78)
    assert len(alerts) == 1
    assert alerts[0]["level"] == "low"
    assert alerts[0]["text"] == ""


def test_message_is_escaped_as_html():
    """The message is escaped and its line breaks become <br>"""
    protocols = [
        {
            "related_items": [79],
            "message": "Dose > 4 g\n<b>Avaliar</b> & ajustar",
            "level": "high",
        }
    ]

    result = _find_alerts([_drug(79)], protocols)

    alerts = _protocol_alerts(result, 79)
    assert alerts[0]["text"] == (
        "Dose &gt; 4 g<br>&lt;b&gt;Avaliar&lt;/b&gt; &amp; ajustar"
    )


def test_no_protocols_means_no_protocol_alert():
    """None or an empty list of protocols raises no protocol alert"""
    for protocols in (None, []):
        result = _find_alerts([_drug(80)], protocols)

        assert _protocol_alerts(result, 80) == []
        assert result["stats"]["protocol"] == 0


def test_suspended_item_gets_no_protocol_alert():
    """A suspended item is left out of the alerts, protocol ones included"""
    drug = _drug(81)
    drug.prescription_drug.suspendedDate = datetime.now()
    protocols = [{"related_items": [81], "message": "Mensagem", "level": "high"}]

    result = _find_alerts([drug], protocols)

    assert _protocol_alerts(result, 81) == []
    assert result["stats"]["protocol"] == 0
