import sys
import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


from config import Config
from services.alert_interaction_service import find_relations
from models.prescription import PrescriptionDrug, DrugAttributes, Drug, Frequency
from models.main import db, Drug, Substance

from conftest import _get_mock_row

# Create a Flask app
app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = Config.POTGRESQL_CONNECTION_STRING
app.config["SQLALCHEMY_BINDS"] = {"report": Config.REPORT_CONNECTION_STRING}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 250,
    "pool_pre_ping": True,
    "pool_size": 20,
    "max_overflow": 30,
}

# Initialize SQLAlchemy with the app
db.init_app(app)

# Create the engine and session
engine = create_engine(app.config["SQLALCHEMY_DATABASE_URI"])
Session = sessionmaker(bind=engine)


@pytest.fixture
def app_context():
    with app.app_context():
        yield


@pytest.mark.usefixtures("app_context")
def test_find_relations_drug_interaction(monkeypatch):
    drug_list = [
        _get_mock_row(id_prescription_drug=1, dose=10, drug_name="Drug A"),
        _get_mock_row(id_prescription_drug=2, dose=20, drug_name="Drug B"),
    ]

    def mock_get_allergies(*args, **kwargs):
        # Simulate an allergy to Drug A

        return []

        """
        return [
            type(
                "obj",
                (object,),
                {
                    "idDrug": "1",
                    "idPatient": "1",
                    "drugName": "Drug A Substance",
                    "active": True,
                    "createdAt": datetime.now(),
                },
            )
        ]
        """

    def mock_get_active_relations(*args, **kwargs):
        # Simulate the response from the database
        active_relations = {}
        # Example mock data that mimics the database response
        mock_data = [
            {
                "sctida": "211111",
                "sctidb": "111111",
                "kind": "it",
                "text": "Drug A interacts with Drug B",
                "level": 1,
            },
        ]

        for item in mock_data:
            key = f"{item['sctida']}-{item['sctidb']}-{item['kind']}"
            active_relations[key] = {
                "sctida": item["sctida"],
                "sctidb": item["sctidb"],
                "kind": item["kind"],
                "text": item["text"],
                "level": item["level"],
            }

        return active_relations

    monkeypatch.setattr(
        "services.alert_interaction_service.db.session.scalar",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_allergies", mock_get_allergies
    )
    monkeypatch.setattr(
        "services.alert_interaction_service._get_active_relations",
        mock_get_active_relations,
    )

    results = find_relations(drug_list, id_patient=1, is_cpoe=False)

    # Assert alerts structure
    assert "alerts" in results
    assert "2" in results["alerts"]
    assert "1" in results["alerts"]

    # Assert alert details for idPrescriptionDrug '2'
    alert_2 = results["alerts"]["2"][0]
    assert alert_2["idPrescriptionDrug"] == "2"
    assert alert_2["key"] == "211111-111111-it"
    assert alert_2["type"] == "it"
    assert alert_2["level"] == 1
    assert alert_2["relation"] == "1"
    assert (
        alert_2["text"]
        == "Interação Medicamentosa: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert alert details for idPrescriptionDrug '1'
    alert_1 = results["alerts"]["1"][0]
    assert alert_1["idPrescriptionDrug"] == "1"
    assert alert_1["key"] == "211111-111111-it"
    assert alert_1["type"] == "it"
    assert alert_1["level"] == 1
    assert alert_1["relation"] == "1"
    assert (
        alert_1["text"]
        == "Interação Medicamentosa: Drug A interacts with Drug B (Drug B e Drug A)"
    )

    # Assert stats structure
    assert "stats" in results
    assert results["stats"]["it"] == 1
    assert results["stats"]["dt"] == 0
    assert results["stats"]["dm"] == 0
    assert results["stats"]["iy"] == 0
    assert results["stats"]["sl"] == 0
    assert results["stats"]["rx"] == 0
