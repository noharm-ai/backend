"""Helpers to create admin-exam test fixtures in the DB.

demo.segmentoexame carries no seed data, so this module owns every row it
creates. Exam types are prefixed with ``zzt`` and segments use the 991x range
so nothing collides with the seed segments (1, 2) or with the 9901/9902
segments reserved by test_admin_protocol.py.
"""

from sqlalchemy import text

from tests.conftest import session, session_commit


def create_test_segment(id_segment: int, name: str, tp_segment: int = 1) -> None:
    """Insert a segment into demo.segmento (idempotent)."""
    session.execute(
        text(
            "INSERT INTO demo.segmento (idsegmento, nome, status, tp_segmento, cpoe) "
            "VALUES (:id, :name, 1, :tp_segment, false) "
            "ON CONFLICT (idsegmento) DO NOTHING"
        ),
        {"id": id_segment, "name": name, "tp_segment": tp_segment},
    )
    session_commit()


def create_test_segment_exam(
    id_segment: int,
    type_exam: str,
    name: str = "ZZTest Exam",
    initials: str = "ZZ",
    min: float = 1,
    max: float = 10,
    ref: str = "ref",
    order: int = 1,
    active: bool = True,
    tp_exam_ref: str | None = None,
) -> None:
    """Insert a segment exam into demo.segmentoexame (idempotent)."""
    session.execute(
        text(
            "INSERT INTO demo.segmentoexame "
            "  (idsegmento, tpexame, tpexame_ref, abrev, nome, min, max, referencia, "
            "   posicao, ativo, update_at, update_by) "
            "VALUES "
            "  (:id_segment, :type_exam, :tp_exam_ref, :initials, :name, :min, :max, "
            "   :ref, :order, :active, now(), 1) "
            "ON CONFLICT (idsegmento, tpexame) DO NOTHING"
        ),
        {
            "id_segment": id_segment,
            "type_exam": type_exam,
            "tp_exam_ref": tp_exam_ref,
            "initials": initials,
            "name": name,
            "min": min,
            "max": max,
            "ref": ref,
            "order": order,
            "active": active,
        },
    )
    session_commit()


def create_test_global_exam(
    tp_exam: str,
    name: str,
    initials: str = "ZZ",
    measureunit: str = "mg/dL",
    active: bool = True,
    min_adult: float = 1,
    max_adult: float = 2,
    ref_adult: str = "adult ref",
    min_pediatric: float = 3,
    max_pediatric: float = 4,
    ref_pediatric: str = "pediatric ref",
) -> None:
    """Insert a global exam into public.exame (idempotent)."""
    session.execute(
        text(
            "INSERT INTO public.exame "
            "  (tpexame, nome, abrev, unidade, ativo, min_adulto, max_adulto, "
            "   referencia_adulto, min_pediatrico, max_pediatrico, referencia_pediatrico, "
            "   created_at, created_by) "
            "VALUES "
            "  (:tp_exam, :name, :initials, :measureunit, :active, :min_adult, :max_adult, "
            "   :ref_adult, :min_pediatric, :max_pediatric, :ref_pediatric, now(), 1) "
            "ON CONFLICT (tpexame) DO NOTHING"
        ),
        {
            "tp_exam": tp_exam,
            "name": name,
            "initials": initials,
            "measureunit": measureunit,
            "active": active,
            "min_adult": min_adult,
            "max_adult": max_adult,
            "ref_adult": ref_adult,
            "min_pediatric": min_pediatric,
            "max_pediatric": max_pediatric,
            "ref_pediatric": ref_pediatric,
        },
    )
    session_commit()


def get_segment_exam_row(id_segment: int, type_exam: str):
    """Read a segment exam straight from the DB, bypassing the service layer."""
    return session.execute(
        text(
            "SELECT idsegmento, tpexame, tpexame_ref, abrev, nome, min, max, "
            "       referencia, posicao, ativo, update_by "
            "FROM demo.segmentoexame "
            "WHERE idsegmento = :id_segment AND tpexame = :type_exam"
        ),
        {"id_segment": id_segment, "type_exam": type_exam},
    ).first()


def get_segment_exam_types(id_segment: int) -> list[str]:
    """Exam types configured for a segment, ordered by name."""
    return [
        row[0]
        for row in session.execute(
            text(
                "SELECT tpexame FROM demo.segmentoexame "
                "WHERE idsegmento = :id_segment ORDER BY nome"
            ),
            {"id_segment": id_segment},
        ).all()
    ]


def delete_segment_exams(id_segments) -> None:
    """Remove every segment exam of the given segments."""
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE idsegmento IN :ids").bindparams(
            ids=tuple(id_segments)
        )
    )
    session_commit()


def delete_segment_exams_by_type(type_exams) -> None:
    """Remove segment exams of the given types across every segment."""
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame IN :types").bindparams(
            types=tuple(type_exams)
        )
    )
    session_commit()


def delete_segments(id_segments) -> None:
    """Remove the given test segments."""
    session.execute(
        text("DELETE FROM demo.segmento WHERE idsegmento IN :ids").bindparams(
            ids=tuple(id_segments)
        )
    )
    session_commit()


def delete_global_exams(tp_exams) -> None:
    """Remove the given global exams."""
    session.execute(
        text("DELETE FROM public.exame WHERE tpexame IN :types").bindparams(
            types=tuple(tp_exams)
        )
    )
    session_commit()
