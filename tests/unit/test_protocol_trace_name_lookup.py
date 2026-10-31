"""Unit tests: how the protocol trace names things and decides applicability
(services.protocol_trace_service).

The trace explains to the pharmacist why each protocol did or did not fire on
a prescription. A protocol config only holds ids (``substance``, ``idDrug`` and
the ``combination`` criteria), so ``_build_name_lookup`` maps every id to a
name before the messages are built:

* ids of items present in the prescription are named from the prescription
  rows themselves, with no extra query;
* ids the protocol expects but the prescription lacks -- the usual reason a
  protocol did *not* fire -- are fetched from the catalog, one query per kind,
  so the message says "não contém nenhum de: Vancomicina" instead of an id;
* anything that is not a numeric id is left alone.

``_get_applicable_types`` and ``_get_applicability`` mirror which protocols run
automatically: aggregated prescriptions take the aggregated protocols, and a
protocol in staging never runs in production. The integration tests in
tests/integration/test_protocol_trace.py cover the inactive and wrong-type
notes against the database; these cover the remaining branches without one.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from models.enums import NoHarmENV, ProtocolStatusTypeEnum, ProtocolTypeEnum
from models.main import Drug, Substance
from services import protocol_trace_service


def _row(id_drug=None, drug_name=None, substance=None):
    """A drug list row, as the prescription view returns it: (presmed, drug,
    ..., substance at index 11)."""
    row = [None] * 12
    row[0] = SimpleNamespace(idDrug=id_drug)
    row[1] = SimpleNamespace(name=drug_name) if drug_name is not None else None
    row[11] = substance
    return tuple(row)


def _substance(id_substance, name):
    """A substance record with only what the lookup reads."""
    return SimpleNamespace(id=id_substance, name=name)


def _catalog(substances=None, drugs=None):
    """A mocked db whose Substance/Drug queries answer the given records.

    Returns (db mock, dict of the ids each kind was queried with).
    """
    queried = {}
    answers = {Substance: substances or [], Drug: drugs or []}

    def query(model):
        q = MagicMock()

        def filter_(criterion):
            # criterion is Model.id.in_([...]); keep the ids it asks for
            queried[model] = sorted(criterion.right.value)
            result = MagicMock()
            result.all.return_value = answers[model]
            return result

        q.filter.side_effect = filter_
        return q

    db = MagicMock()
    db.session.query.side_effect = query
    return db, queried


class TestNameLookupFromPrescription:
    """Names taken from the prescription rows themselves"""

    def test_names_the_items_present_in_the_prescription(self):
        """Ids presentes na prescrição são nomeados a partir das próprias linhas"""
        drug_list = [
            _row(
                id_drug=10,
                drug_name="Dipirona 500mg",
                substance=_substance(1, "Dipirona"),
            ),
            _row(
                id_drug=20,
                drug_name="Omeprazol 20mg",
                substance=_substance(2, "Omeprazol"),
            ),
        ]
        db, queried = _catalog()

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=drug_list, configs=[]
            )

        assert lookup == {
            "substance": {"1": "Dipirona", "2": "Omeprazol"},
            "drug": {"10": "Dipirona 500mg", "20": "Omeprazol 20mg"},
        }
        assert queried == {}

    def test_skips_rows_without_substance_drug_or_drug_id(self):
        """Linhas sem substância, sem medicamento ou sem idDrug não entram no mapa"""
        drug_list = [
            _row(id_drug=10, drug_name=None, substance=None),
            _row(id_drug=None, drug_name="Sem id", substance=None),
        ]
        db, _ = _catalog()

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=drug_list, configs=[]
            )

        assert lookup == {"substance": {}, "drug": {}}

    def test_does_not_query_ids_the_prescription_already_names(self):
        """Ids esperados pelo protocolo e presentes na prescrição não geram consulta"""
        drug_list = [
            _row(
                id_drug=10,
                drug_name="Dipirona 500mg",
                substance=_substance(1, "Dipirona"),
            ),
        ]
        configs = [
            {
                "variables": [
                    {"field": "substance", "value": ["1"]},
                    {"field": "idDrug", "value": ["10"]},
                ]
            }
        ]
        db, queried = _catalog()

        with patch.object(protocol_trace_service, "db", db):
            protocol_trace_service._build_name_lookup(
                drug_list=drug_list, configs=configs
            )

        assert queried == {}
        db.session.query.assert_not_called()


class TestNameLookupFromCatalog:
    """Names fetched for ids the protocol expects but the prescription lacks"""

    def test_fetches_missing_substances_and_drugs(self):
        """Ids ausentes da prescrição são buscados no cadastro"""
        configs = [
            {
                "variables": [
                    {"field": "substance", "value": ["3", "4"]},
                    {"field": "idDrug", "value": [30]},
                ]
            }
        ]
        db, queried = _catalog(
            substances=[_substance(3, "Vancomicina"), _substance(4, "Meropenem")],
            drugs=[SimpleNamespace(id=30, name="Heparina 5000UI")],
        )

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=[], configs=configs
            )

        assert queried == {Substance: [3, 4], Drug: [30]}
        assert lookup == {
            "substance": {"3": "Vancomicina", "4": "Meropenem"},
            "drug": {"30": "Heparina 5000UI"},
        }

    def test_reads_the_ids_of_combination_criteria(self):
        """Critérios de combinação também têm seus ids nomeados"""
        configs = [
            {
                "variables": [
                    {"field": "combination", "substance": ["5"], "drug": ["50"]},
                ]
            }
        ]
        db, queried = _catalog(
            substances=[_substance(5, "Varfarina")],
            drugs=[SimpleNamespace(id=50, name="Marevan 5mg")],
        )

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=[], configs=configs
            )

        assert queried == {Substance: [5], Drug: [50]}
        assert lookup["substance"] == {"5": "Varfarina"}
        assert lookup["drug"] == {"50": "Marevan 5mg"}

    def test_merges_prescription_and_catalog_names_across_protocols(self):
        """Nomes da prescrição e do cadastro se somam, para todos os protocolos"""
        drug_list = [
            _row(
                id_drug=10,
                drug_name="Dipirona 500mg",
                substance=_substance(1, "Dipirona"),
            ),
        ]
        configs = [
            {"variables": [{"field": "substance", "value": ["1", "3"]}]},
            {"variables": [{"field": "substance", "value": ["3", "4"]}]},
        ]
        db, queried = _catalog(
            substances=[_substance(3, "Vancomicina"), _substance(4, "Meropenem")]
        )

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=drug_list, configs=configs
            )

        # one query for every missing substance, each id once
        assert queried == {Substance: [3, 4]}
        assert lookup["substance"] == {
            "1": "Dipirona",
            "3": "Vancomicina",
            "4": "Meropenem",
        }
        assert lookup["drug"] == {"10": "Dipirona 500mg"}

    def test_ignores_values_that_are_not_ids(self):
        """Valores não numéricos não são consultados"""
        configs = [
            {
                "variables": [
                    {"field": "substance", "value": ["abc", "3"]},
                    {"field": "idDrug", "value": ["x1"]},
                ]
            }
        ]
        db, queried = _catalog(substances=[_substance(3, "Vancomicina")])

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=[], configs=configs
            )

        assert queried == {Substance: [3]}
        assert lookup == {"substance": {"3": "Vancomicina"}, "drug": {}}

    def test_an_id_missing_from_the_catalog_stays_unnamed(self):
        """Id inexistente no cadastro simplesmente fica sem nome"""
        configs = [{"variables": [{"field": "idDrug", "value": ["999"]}]}]
        db, queried = _catalog(drugs=[])

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=[], configs=configs
            )

        assert queried == {Drug: [999]}
        assert lookup == {"substance": {}, "drug": {}}

    @pytest.mark.parametrize(
        "configs",
        [
            [None],
            [{}],
            [{"variables": [{"field": "substance", "value": None}]}],
            [{"variables": [{"field": "combination"}]}],
            [{"variables": [{"field": "age", "value": ["65"]}]}],
        ],
        ids=[
            "no-config",
            "no-variables",
            "null-value",
            "empty-combination",
            "other-field",
        ],
    )
    def test_configs_without_ids_do_not_query(self, configs):
        """Configurações sem ids de substância/medicamento não geram consulta"""
        db, _ = _catalog()

        with patch.object(protocol_trace_service, "db", db):
            lookup = protocol_trace_service._build_name_lookup(
                drug_list=[], configs=configs
            )

        assert lookup == {"substance": {}, "drug": {}}
        db.session.query.assert_not_called()


class TestApplicability:
    """Which protocol types run, and the notes when one would not"""

    def test_individual_prescription_takes_the_individual_protocols(self):
        """Prescrição individual executa protocolos individuais"""
        types = protocol_trace_service._get_applicable_types(
            prescription=SimpleNamespace(agg=None)
        )

        assert types == [
            ProtocolTypeEnum.PRESCRIPTION_ALL,
            ProtocolTypeEnum.PRESCRIPTION_ITEM,
            ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL,
        ]

    def test_aggregated_prescription_takes_the_aggregated_protocols(self):
        """Prescrição agregada executa protocolos agregados"""
        types = protocol_trace_service._get_applicable_types(
            prescription=SimpleNamespace(agg=True)
        )

        assert types == [
            ProtocolTypeEnum.PRESCRIPTION_ALL,
            ProtocolTypeEnum.PRESCRIPTION_ITEM,
            ProtocolTypeEnum.PRESCRIPTION_AGG,
        ]

    def _protocol(self, status_type, protocol_type=ProtocolTypeEnum.PRESCRIPTION_ALL):
        """A protocol with only what the applicability check reads."""
        return SimpleNamespace(
            status_type=status_type.value, protocol_type=protocol_type.value
        )

    def test_staging_protocol_does_not_run_in_production(self):
        """Protocolo em homologação não é executado em produção"""
        protocol = self._protocol(ProtocolStatusTypeEnum.STAGING)

        with patch.object(Config, "ENV", NoHarmENV.PRODUCTION.value):
            applicable, notes = protocol_trace_service._get_applicability(
                protocol=protocol,
                applicable_types=[ProtocolTypeEnum.PRESCRIPTION_ALL],
            )

        assert applicable is False
        assert len(notes) == 1
        assert "homologação" in notes[0]

    def test_staging_protocol_runs_outside_production(self):
        """Protocolo em homologação é executado fora de produção"""
        protocol = self._protocol(ProtocolStatusTypeEnum.STAGING)

        with patch.object(Config, "ENV", NoHarmENV.STAGING.value):
            applicable, notes = protocol_trace_service._get_applicability(
                protocol=protocol,
                applicable_types=[ProtocolTypeEnum.PRESCRIPTION_ALL],
            )

        assert applicable is True
        assert notes == []

    def test_notes_add_up_when_several_reasons_apply(self):
        """Homologação em produção e tipo não aplicável geram duas notas"""
        protocol = self._protocol(
            ProtocolStatusTypeEnum.STAGING, ProtocolTypeEnum.PRESCRIPTION_AGG
        )

        with patch.object(Config, "ENV", NoHarmENV.PRODUCTION.value):
            applicable, notes = protocol_trace_service._get_applicability(
                protocol=protocol,
                applicable_types=[
                    ProtocolTypeEnum.PRESCRIPTION_ALL,
                    ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL,
                ],
            )

        assert applicable is False
        assert len(notes) == 2
        assert "homologação" in notes[0]
        assert "tipo" in notes[1]
