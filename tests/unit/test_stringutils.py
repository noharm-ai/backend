import pytest

from utils import stringutils


@pytest.mark.parametrize(
    "name, prepared_name",
    [
        ("ZINPASS 10mg 1cp/dia", "ZINPASS"),
        ("DOXAZOSINA 4mg 1cp/dia", "DOXAZOSINA"),
        ("ZINPASS 10mg 1cp/dia tardinha", "ZINPASS"),
        (
            "PANTOPRAZOL 40MG CPR - 1CPR - às 06:00 h - às 06:00 h",
            "PANTOPRAZOL  CPR 1CPR",
        ),
        ("PROPAFENONA 150MG - 1CPR - 09-21 h", "PROPAFENONA  1CPR"),
    ],
)
def test_prepare_drug_name(name, prepared_name):
    """Teste stringutils - prepare_drug_name"""

    assert stringutils.prepare_drug_name(name) == prepared_name
