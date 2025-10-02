"""INTERNAL FUNCTIONS"""

import logging
from datetime import datetime

from services import (
    prescription_agg_service,
)
from utils.static_context import execute_with_static_context


def prescalc(event: dict, context: any):
    """
    Prescalc: calculates prescription indicators and generate a
    prescription-day prescription record
    """

    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    schema: str = event.get("schema", None)
    id_prescription: int = event.get("id_prescription", None)
    force: bool = event.get("force", False)

    logger.warning("schema: %s | id_prescription: %s", schema, id_prescription)

    def _prescalc_operation(user_context, schema, id_prescription, force):
        """Internal operation function for prescalc with automatic exception handling."""
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema=schema,
            id_prescription=id_prescription,
            force=force,
            user_context=user_context,
            public=False,
        )
        return id_prescription

    params = {
        "schema": schema,
        "id_prescription": id_prescription,
        "force": force,
    }

    logger.warning("params: %s", str(params))

    return execute_with_static_context(
        schema=schema, operation_func=_prescalc_operation, params=params
    )


def atendcalc(schema: str, admission_number: int, str_date: str):
    """
    Atendcalc: creates a prescription-day based on the admission number
    Used for CPOE
    """

    def _atendcalc_operation(user_context, schema, admission_number, str_date):
        p_date = (
            datetime.strptime(str_date, "%Y-%m-%d").date()
            if str_date
            else datetime.today().date()
        )
        prescription_agg_service.create_agg_prescription_by_date(
            schema, admission_number, p_date, user_context=user_context, public=False
        )

        return admission_number

    params = {
        "schema": schema,
        "admission_number": admission_number,
        "str_date": str_date,
    }

    return execute_with_static_context(
        schema=schema, operation_func=_atendcalc_operation, params=params
    )
