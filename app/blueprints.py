"""Blueprint registration.

This module imports and registers all Flask blueprints for the application.
"""

# Core routes
# Admin routes
from routes.admin.admin_drug import app_admin_drug
from routes.admin.admin_exam import app_admin_exam
from routes.admin.admin_frequency import app_admin_freq
from routes.admin.admin_global_exam import app_admin_global_exam
from routes.admin.admin_global_memory import app_admin_global_memory
from routes.admin.admin_integration import app_admin_integration
from routes.admin.admin_integration_remote import app_admin_integration_remote
from routes.admin.admin_intervention_reason import app_admin_interv
from routes.admin.admin_memory import app_admin_memory
from routes.admin.admin_protocol import app_admin_protocol
from routes.admin.admin_relation import app_admin_relation
from routes.admin.admin_report import app_admin_report
from routes.admin.admin_segment import app_admin_segment
from routes.admin.admin_substance import app_admin_subs
from routes.admin.admin_tag import app_admin_tag
from routes.admin.admin_unit import app_admin_unit
from routes.admin.admin_unit_conversion import app_admin_unit_conversion
from routes.authentication import app_auth
from routes.conciliation import app_conciliation
from routes.drugs import app_drugs
from routes.exams import app_exams
from routes.intervention import app_itrv
from routes.lists import app_lists
from routes.memory import app_mem
from routes.names import app_names
from routes.navigation import app_navigation
from routes.notes import app_note
from routes.outlier import app_out
from routes.outlier_generate import app_gen
from routes.patient import app_pat
from routes.prescription import app_pres
from routes.prescription_crud import app_pres_crud
from routes.protocol import app_protocol
from routes.queue import app_queue

# Regulation routes
from routes.regulation.regulation import app_regulation

# Report routes
from routes.reports.reports_antimicrobial import app_rpt_antimicrobial
from routes.reports.reports_config_rpt import app_rpt_config
from routes.reports.reports_culture import app_rpt_culture
from routes.reports.reports_custom import app_rpt_custom
from routes.reports.reports_exams import app_rpt_exams
from routes.reports.reports_general import app_rpt_general
from routes.reports.reports_integration import app_rpt_integration
from routes.reports.reports_prescription_history import app_rpt_prescription_history
from routes.reports.reports_regulation import app_rpt_regulation
from routes.segment import app_seg
from routes.static import app_stc
from routes.substance import app_sub
from routes.summary import app_summary
from routes.support import app_support
from routes.tag import app_tag
from routes.user import app_usr
from routes.user_admin import app_user_admin


def register_blueprints(app):
    """Register all application blueprints.

    Args:
        app: Flask application instance
    """
    # Core blueprints
    app.register_blueprint(app_auth)
    app.register_blueprint(app_out)
    app.register_blueprint(app_pres)
    app.register_blueprint(app_seg)
    app.register_blueprint(app_gen)
    app.register_blueprint(app_itrv)
    app.register_blueprint(app_stc)
    app.register_blueprint(app_sub)
    app.register_blueprint(app_mem)
    app.register_blueprint(app_pat)
    app.register_blueprint(app_usr)
    app.register_blueprint(app_note)
    app.register_blueprint(app_drugs)
    app.register_blueprint(app_names)
    app.register_blueprint(app_summary)
    app.register_blueprint(app_support)
    app.register_blueprint(app_conciliation)
    app.register_blueprint(app_tag)
    app.register_blueprint(app_protocol)
    app.register_blueprint(app_exams)
    app.register_blueprint(app_lists)
    app.register_blueprint(app_queue)
    app.register_blueprint(app_navigation)
    app.register_blueprint(app_user_admin)
    app.register_blueprint(app_pres_crud)

    # Admin blueprints
    app.register_blueprint(app_admin_freq)
    app.register_blueprint(app_admin_interv)
    app.register_blueprint(app_admin_memory)
    app.register_blueprint(app_admin_drug)
    app.register_blueprint(app_admin_integration)
    app.register_blueprint(app_admin_integration_remote)
    app.register_blueprint(app_admin_segment)
    app.register_blueprint(app_admin_exam)
    app.register_blueprint(app_admin_unit_conversion)
    app.register_blueprint(app_admin_subs)
    app.register_blueprint(app_admin_relation)
    app.register_blueprint(app_admin_unit)
    app.register_blueprint(app_admin_tag)
    app.register_blueprint(app_admin_protocol)
    app.register_blueprint(app_admin_global_exam)
    app.register_blueprint(app_admin_global_memory)
    app.register_blueprint(app_admin_report)

    # Report blueprints
    app.register_blueprint(app_rpt_general)
    app.register_blueprint(app_rpt_culture)
    app.register_blueprint(app_rpt_antimicrobial)
    app.register_blueprint(app_rpt_config)
    app.register_blueprint(app_rpt_prescription_history)
    app.register_blueprint(app_rpt_exams)
    app.register_blueprint(app_rpt_integration)
    app.register_blueprint(app_rpt_regulation)
    app.register_blueprint(app_rpt_custom)

    # Regulation blueprints
    app.register_blueprint(app_regulation)
