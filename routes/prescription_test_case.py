"""Route: prescription test cases, created by maintainers in their test schema"""

from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.prescription_test_case_request import PrescriptionTestCaseRequest
from services import prescription_test_case_service

app_pres_test_case = Blueprint("app_pres_test_case", __name__)


@app_pres_test_case.route("/prescriptions/test-case", methods=["POST"])
# not served in production: test cases are only built in the staging environments
@api_endpoint(is_admin=True)
def create_test_case():
    """Create a test case prescription and run prescalc on it"""
    return prescription_test_case_service.create_test_case(
        request_data=PrescriptionTestCaseRequest(**request.get_json())
    )
