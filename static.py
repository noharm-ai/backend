"""INTERNAL FUNCTIONS"""

from datetime import datetime

from services import (
    prescription_agg_service,
)
from services.infection_control import infection_control_job_service
from utils import logger
from utils.static_context import execute_with_static_context


def prescalc(event: dict, context: any):
    """
    Prescalc: calculates prescription indicators and generate a
    prescription-day prescription record
    """

    schema: str = event.get("schema", None)
    id_prescription: int = event.get("id_prescription", None)
    force: bool = event.get("force", False)

    logger.backend_logger.warning(
        "schema: %s | id_prescription: %s", schema, id_prescription
    )

    def _prescalc_operation(user_context, schema, id_prescription, force):
        """Internal operation function for prescalc with automatic exception handling."""
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema=schema,
            id_prescription=id_prescription,
            force=force,
            user_context=user_context,
        )
        return id_prescription

    params = {
        "schema": schema,
        "id_prescription": id_prescription,
        "force": force,
    }

    logger.backend_logger.warning("params: %s", str(params))

    return execute_with_static_context(
        schema=schema, operation_func=_prescalc_operation, params=params
    )


def atendcalc(event: dict, context: any):
    # def atendcalc(schema: str, admission_number: int, str_date: str):
    """
    Atendcalc: creates a prescription-day based on the admission number
    Used for CPOE
    """

    schema: str = event.get("schema", None)
    admission_number: int = event.get("admission_number", None)

    logger.backend_logger.warning(
        "schema: %s | admission_number: %s", schema, admission_number
    )

    def _atendcalc_operation(user_context, schema, admission_number, str_date):
        p_date = (
            datetime.strptime(str_date, "%Y-%m-%d").date()
            if str_date
            else datetime.today().date()
        )
        prescription_agg_service.create_agg_prescription_by_date(
            schema, admission_number, p_date, user_context=user_context
        )

        return admission_number

    params = {
        "schema": schema,
        "admission_number": admission_number,
        "str_date": None,
    }

    return execute_with_static_context(
        schema=schema, operation_func=_atendcalc_operation, params=params
    )


def infection_control_sync(event: dict, context: any):
    """
    Infection control job: apply the rule to one followed admission. Called
    by the scheduled job in backend-private, one admission at a time
    """

    schema: str = event.get("schema", None)
    admission_number: int = event.get("admission_number", None)

    def _infection_control_sync_operation(user_context, schema, admission_number):
        """Internal operation function for the infection control job."""
        return infection_control_job_service.sync_followed_admission(
            schema=schema,
            admission_number=admission_number,
            user_context=user_context,
        )

    params = {"schema": schema, "admission_number": admission_number}

    return execute_with_static_context(
        schema=schema, operation_func=_infection_control_sync_operation, params=params
    )


# if __name__ == "__main__":
#     prescalc({"schema": "--", "id_prescription": 0}, None)
