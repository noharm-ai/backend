"""Unit tests for intervention_outcome_service._outcome_calc.

``_outcome_calc`` builds the per-item payload the intervention-economy screen
works from, and it is where the money actually gets normalised. For every
prescription item it:

* converts the drug price from the price measure unit to the prescribed one
  (``price / priceFactor``), falling back to the raw price when no conversion
  exists;
* converts the prescribed dose to the drug's default measure unit
  (``dose * doseFactor``);
* flattens the "aprazamento" frequencies (33/44/55/66/99 — "now", "ACM", "SN",
  "agora", "se necessário") to a single daily administration;
* adds the price of the solution/CPOE kit the item belongs to;
* resolves the aggregate prescription id the economy is booked against, from
  the base economy date when one was chosen.

``pricePerDose`` is what ``_calc_economy`` later multiplies by the daily
frequency, so an error anywhere above turns straight into a wrong saved
economy — and the rules are only exercised indirectly through the DB-backed
outcome endpoint today.

The two collaborators that touch the database (``_get_price_kit`` and the
fallback aggregate lookup) are patched, so these tests run against plain
in-memory model instances.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from exception.validation_error import ValidationError
from models.appendix import Frequency, MeasureUnit, MeasureUnitConvert
from models.main import Drug, DrugAttributes
from models.prescription import Prescription, PrescriptionDrug
from services import intervention_outcome_service
from utils import prescriptionutils, status

_ADMISSION = 777001
_SEGMENT = 1
_PRESCRIPTION_DATE = datetime(2024, 3, 15, 8, 0)
_BASE_ECONOMY_DATE = datetime(2024, 3, 20, 0, 0)

_UNIT_DEFAULT = "ZZMG"
_UNIT_PRICE = "ZZG"

_EMPTY_KIT = {"price": 0, "list": []}


def _row(
    *,
    price=10,
    id_measure_unit_price=_UNIT_DEFAULT,
    dose=2,
    pd_id_measure_unit=_UNIT_DEFAULT,
    frequency=3,
    dose_factor=None,
    price_factor=None,
    drug_attr=True,
    id_segment=_SEGMENT,
    prescription_date=_PRESCRIPTION_DATE,
    concilia=None,
    drug=True,
):
    """Build one row of the tuple list ``_outcome_calc`` iterates over.

    The shape mirrors ``intervention_outcome_repository``'s projection:
    (prescription drug, drug, drug attributes, dose conversion, price
    conversion, prescription, default measure unit, frequency).
    """
    prescription_drug = PrescriptionDrug()
    prescription_drug.id = 500001
    prescription_drug.idDrug = 1001
    prescription_drug.idSegment = id_segment
    prescription_drug.dose = dose
    prescription_drug.idMeasureUnit = pd_id_measure_unit
    prescription_drug.frequency = frequency
    prescription_drug.idFrequency = 9
    prescription_drug.interval = "ZZNP name"
    prescription_drug.route = "ORAL"

    drug_record = None
    if drug:
        drug_record = Drug()
        drug_record.id = 1001
        drug_record.name = "ZZTest Drug"

    attributes = None
    if drug_attr:
        attributes = DrugAttributes()
        attributes.idDrug = 1001
        attributes.idSegment = id_segment
        attributes.price = price
        attributes.idMeasureUnit = _UNIT_DEFAULT
        attributes.idMeasureUnitPrice = id_measure_unit_price

    dose_convert = None
    if dose_factor is not None:
        dose_convert = MeasureUnitConvert()
        dose_convert.factor = dose_factor

    price_convert = None
    if price_factor is not None:
        price_convert = MeasureUnitConvert()
        price_convert.factor = price_factor

    prescription = Prescription()
    prescription.id = 400001
    prescription.admissionNumber = _ADMISSION
    prescription.idSegment = id_segment
    prescription.date = prescription_date
    prescription.concilia = concilia

    measure_unit = MeasureUnit()
    measure_unit.id = _UNIT_DEFAULT
    measure_unit.description = "miligrama"

    frequency_record = Frequency()
    frequency_record.id = 9
    frequency_record.description = "8/8 horas"

    return (
        prescription_drug,
        drug_record,
        attributes,
        dose_convert,
        price_convert,
        prescription,
        measure_unit,
        frequency_record,
    )


def _calc(rows, kit=None, date_base_economy=None, destination=False):
    """Run ``_outcome_calc`` with the kit lookup stubbed out."""
    with patch.object(
        intervention_outcome_service,
        "_get_price_kit",
        return_value=kit if kit is not None else _EMPTY_KIT,
    ):
        return intervention_outcome_service._outcome_calc(
            rows,
            user=None,
            date_base_economy=date_base_economy,
            destination=destination,
        )


def _item(rows, **kwargs):
    """Run ``_outcome_calc`` over a single row and return its ``item`` payload."""
    results = _calc(rows, **kwargs)
    assert len(results) == 1

    return results[0]["item"]


class TestPriceConversion:
    """Price is normalised from the price unit to the prescribed unit."""

    def test_same_price_and_default_unit_keeps_the_raw_price(self):
        """No conversion is needed when the drug is priced in its own unit."""
        item = _item([_row(price=10, id_measure_unit_price=_UNIT_DEFAULT)])

        assert item["price"] == "10"
        assert item["conversion"]["priceFactor"] == "1"

    def test_different_price_unit_divides_by_the_conversion_factor(self):
        """A price in grams for a drug dosed in milligrams is divided by the factor."""
        item = _item(
            [
                _row(
                    price=10,
                    id_measure_unit_price=_UNIT_PRICE,
                    price_factor=1000,
                )
            ]
        )

        assert item["price"] == "0.01"
        assert item["conversion"]["priceFactor"] == "1000"

    def test_missing_conversion_falls_back_to_the_raw_price(self):
        """Without a conversion row the price is used as-is rather than dropped."""
        item = _item([_row(price=10, id_measure_unit_price=_UNIT_PRICE)])

        assert item["price"] == "10"
        assert item["conversion"]["priceFactor"] is None

    def test_zero_conversion_factor_falls_back_to_the_raw_price(self):
        """A zero factor would divide by zero, so it is ignored."""
        item = _item(
            [_row(price=10, id_measure_unit_price=_UNIT_PRICE, price_factor=0)]
        )

        assert item["price"] == "10"
        assert item["conversion"]["priceFactor"] is None

    def test_missing_price_leaves_the_item_without_one(self):
        """A drug with no configured price reports price None, not zero."""
        item = _item([_row(price=None)])

        assert item["price"] is None
        assert item["beforeConversion"]["price"] is None

    def test_missing_price_unit_leaves_the_item_without_a_price(self):
        """A price without its measure unit cannot be trusted, so it is dropped."""
        item = _item([_row(price=10, id_measure_unit_price=None)])

        assert item["price"] is None

    def test_item_without_attributes_has_no_price_or_units(self):
        """A drug with no attributes row for the segment still yields an item."""
        item = _item([_row(drug_attr=False)])

        assert item["price"] is None
        assert item["idMeasureUnit"] is None
        assert item["conversion"] == {"doseFactor": None, "priceFactor": None}
        assert item["beforeConversion"]["price"] is None
        assert item["beforeConversion"]["idMeasureUnitPrice"] is None

    def test_the_original_price_is_kept_for_the_ui(self):
        """``beforeConversion`` shows what was configured, before any division."""
        item = _item(
            [
                _row(
                    price=10,
                    id_measure_unit_price=_UNIT_PRICE,
                    price_factor=1000,
                )
            ]
        )

        assert item["beforeConversion"]["price"] == "10"
        assert item["beforeConversion"]["idMeasureUnitPrice"] == _UNIT_PRICE


class TestDoseConversion:
    """Dose is normalised to the drug's default measure unit."""

    def test_dose_is_multiplied_by_the_conversion_factor(self):
        """A dose prescribed in another unit is converted before pricing."""
        item = _item([_row(dose=2, pd_id_measure_unit=_UNIT_PRICE, dose_factor=1000)])

        assert item["dose"] == "2000"
        assert item["conversion"]["doseFactor"] == "1000"

    def test_dose_already_in_the_default_unit_is_not_converted(self):
        """When the prescribed unit is the drug's own unit the factor is 1."""
        item = _item([_row(dose=2, pd_id_measure_unit=_UNIT_DEFAULT)])

        assert item["dose"] == "2"
        assert item["conversion"]["doseFactor"] == "1"

    def test_missing_conversion_keeps_the_prescribed_dose(self):
        """An unconvertible dose is reported as prescribed, not discarded."""
        item = _item([_row(dose=2, pd_id_measure_unit=_UNIT_PRICE)])

        assert item["dose"] == "2"
        assert item["conversion"]["doseFactor"] is None

    def test_missing_dose_is_reported_as_none(self):
        """An item without a dose keeps a null dose, and a zero price per dose."""
        item = _item([_row(dose=None)])

        assert item["dose"] is None
        assert item["pricePerDose"] == "0.0"
        assert item["beforeConversion"]["dose"] == 0

    def test_the_prescribed_dose_is_kept_for_the_ui(self):
        """``beforeConversion`` shows the dose as prescribed."""
        item = _item([_row(dose=2, pd_id_measure_unit=_UNIT_PRICE, dose_factor=1000)])

        assert item["beforeConversion"]["dose"] == "2"
        assert item["beforeConversion"]["idMeasureUnit"] == _UNIT_PRICE


class TestFrequency:
    """Frequencies that do not express a daily rate count as one dose a day."""

    @pytest.mark.parametrize("frequency", [33, 44, 55, 66, 99])
    def test_aprazamento_frequencies_count_as_one_a_day(self, frequency):
        """Codes meaning "now" or "if needed" are not a daily rate: they flatten to 1."""
        assert _item([_row(frequency=frequency)])["frequencyDay"] == 1

    @pytest.mark.parametrize("frequency", [1, 3, 6, 24])
    def test_regular_frequencies_are_kept(self, frequency):
        """A real daily frequency is carried through untouched."""
        assert _item([_row(frequency=frequency)])["frequencyDay"] == frequency

    def test_frequency_description_comes_from_the_frequency_record(self):
        """The UI label is read from the joined frequency, when there is one."""
        item = _item([_row()])

        assert item["idFrequency"] == 9
        assert item["frequencyDescription"] == "8/8 horas"


class TestPricePerDose:
    """``pricePerDose`` is price × dose plus the kit it is administered with."""

    def test_price_times_dose_without_a_kit(self):
        """A standalone item costs its converted price times its converted dose."""
        item = _item([_row(price=10, dose=2)])

        assert item["pricePerDose"] == "20.0"
        assert item["priceKit"] == 0

    def test_the_kit_price_is_added(self):
        """A solution's other components are part of what the dose costs."""
        kit = {"price": "7", "list": [{"name": "ZZTest Diluent", "price": "7"}]}
        item = _item([_row(price=10, dose=2)], kit=kit)

        assert item["pricePerDose"] == "27.0"
        assert item["priceKit"] == "7"
        assert item["kit"] == kit

    def test_a_kit_alone_still_produces_a_price(self):
        """An item with no price of its own still carries its kit cost."""
        item = _item([_row(price=None, dose=2)], kit={"price": "7", "list": []})

        assert item["pricePerDose"] == "7.0"

    def test_converted_values_are_what_gets_multiplied(self):
        """Conversions happen before the multiplication, never after."""
        item = _item(
            [
                _row(
                    price=10,
                    id_measure_unit_price=_UNIT_PRICE,
                    price_factor=1000,
                    dose=2,
                    pd_id_measure_unit=_UNIT_PRICE,
                    dose_factor=1000,
                )
            ]
        )

        # price 10/1000 = 0.01 and dose 2*1000 = 2000
        assert item["pricePerDose"] == "20.0"


class TestAggregateId:
    """The economy is booked against an aggregate prescription id."""

    def test_aggregate_id_is_built_from_the_prescription_date(self):
        """Without a base economy date the item's own date is used."""
        expected = prescriptionutils.gen_agg_id(
            admission_number=_ADMISSION,
            id_segment=_SEGMENT,
            pdate=_PRESCRIPTION_DATE,
        )

        assert _item([_row()])["idPrescriptionAggregate"] == str(expected)

    def test_base_economy_date_overrides_the_prescription_date(self):
        """A chosen base date moves the economy to that day's aggregate."""
        expected = prescriptionutils.gen_agg_id(
            admission_number=_ADMISSION,
            id_segment=_SEGMENT,
            pdate=_BASE_ECONOMY_DATE,
        )
        item = _item([_row()], date_base_economy=_BASE_ECONOMY_DATE)

        assert item["idPrescriptionAggregate"] == str(expected)

    def test_without_a_segment_the_aggregate_prescription_is_looked_up(self):
        """A segmentless prescription falls back to the stored aggregate row."""
        aggregate = Prescription()
        aggregate.id = 400999

        with patch.object(intervention_outcome_service, "db") as mock_db:
            query = mock_db.session.query.return_value
            query.filter.return_value = query
            query.first.return_value = aggregate

            item = _item([_row(id_segment=None)])

        assert item["idPrescriptionAggregate"] == "400999"

    def test_missing_aggregate_prescription_raises_for_the_origin(self):
        """The origin item cannot be priced without an aggregate: fail loudly."""
        with patch.object(intervention_outcome_service, "db") as mock_db:
            query = mock_db.session.query.return_value
            query.filter.return_value = query
            query.first.return_value = None

            with pytest.raises(ValidationError) as excinfo:
                _calc([_row(id_segment=None)])

        assert excinfo.value.httpStatus == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.code == "errors.businessRules"

    def test_missing_aggregate_prescription_skips_a_destination_item(self):
        """A substitute candidate that cannot be resolved is dropped silently."""
        with patch.object(intervention_outcome_service, "db") as mock_db:
            query = mock_db.session.query.return_value
            query.filter.return_value = query
            query.first.return_value = None

            assert _calc([_row(id_segment=None)], destination=True) == []


class TestItemIdentification:
    """The fields the screen uses to label each item."""

    def test_ids_are_serialised_as_strings(self):
        """Prescription ids go to the UI as strings to survive JSON precision."""
        item = _item([_row()])

        assert item["idPrescription"] == "400001"
        assert item["idPrescriptionDrug"] == "500001"
        assert item["prescriptionDate"] == _PRESCRIPTION_DATE.isoformat()

    def test_drug_name_and_unit_description_come_from_the_joins(self):
        """Names shown on screen are read from the joined catalog rows."""
        item = _item([_row()])

        assert item["idDrug"] == 1001
        assert item["name"] == "ZZTest Drug"
        assert item["idMeasureUnit"] == _UNIT_DEFAULT
        assert item["measureUnitDescription"] == "miligrama"
        assert item["route"] == "ORAL"

    def test_item_without_a_drug_record_falls_back_to_the_np_label(self):
        """A non-padronizado item has no catalog drug: it is labelled "NP"."""
        item = _item([_row(drug=False)])

        assert item["name"] == "NP"
        assert item["idDrug"] == 1001
        assert item["drugNpName"] == "ZZNP name"

    @pytest.mark.parametrize(
        ("concilia", "expected"), [(None, False), ("s", True), ("", True)]
    )
    def test_conciliation_flag_reflects_the_prescription(self, concilia, expected):
        """Any non-null ``concilia`` marks the item as coming from a conciliation."""
        item = _item([_row(concilia=concilia)])

        assert item["concilia"] is expected


class TestMultipleItems:
    """The whole list is processed, in order."""

    def test_every_row_produces_one_item(self):
        """Each prescription item of the intervention gets its own payload."""
        results = _calc([_row(price=10, dose=2), _row(price=5, dose=4)])

        assert [r["item"]["pricePerDose"] for r in results] == ["20.0", "20.0"]

    def test_an_empty_list_produces_no_items(self):
        """Nothing to price is an empty result, not an error."""
        assert _calc([]) == []
