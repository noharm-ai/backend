"""Unit tests for the antimicrobial timeline courses (services.infection_control.antimicrobial_timeline_service).

The service turns prescribed antimicrobial items into treatment courses. The
two prescribing styles must end up the same:

* daily prescribers repeat the drug on each day's prescription, so a course is
  a chain of one-day items. A single missing day keeps the course; two missing
  days start a new one;
* CPOE hospitals keep one order from its start to its expire date, renewed by
  a new order. The planned end is the expire date of the latest order.

For daily prescribers the planned end comes from ``periodo_total``, counted
from the first day of the course.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from services.infection_control import antimicrobial_timeline_service as svc

DAY = timedelta(days=1)
T0 = datetime(2026, 3, 1, 8, 0)


def _row(
    start,
    expire=None,
    id_drug=1,
    cpoe=False,
    suspended_date=None,
    dose=1.0,
    frequency="8/8h",
    period_total=None,
    id_prescription=None,
):
    """A repository row of one prescribed antimicrobial item"""
    id_prescription = id_prescription or int(start.timestamp())
    return SimpleNamespace(
        id_prescription=id_prescription,
        id_prescription_drug=int(f"{id_prescription}{id_drug}"),
        id_drug=id_drug,
        drug=f"Drug {id_drug}",
        substance=None,
        atb_level=None,
        cpoe=cpoe,
        date=start,
        expire=expire,
        suspended_date=suspended_date,
        dose=dose,
        doseconv=dose,
        measure_unit="g",
        frequency=frequency,
        daily_frequency=3,
        route="IV",
        period_total=period_total,
    )


def _daily(days, start=T0, **kwargs):
    """One daily prescription per offset in `days`, each valid for 24 hours"""
    return [_row(start + d * DAY, expire=start + (d + 1) * DAY, **kwargs) for d in days]


def _courses(rows, now):
    """Build and serialize the courses the way the endpoint does"""
    items = [svc.build_item(r, now=now) for r in rows]
    return [svc.serialize_course(c, now=now) for c in svc.group_courses(items)]


class TestDailyPrescriber:
    def test_consecutive_days_are_one_active_course(self):
        now = T0 + 4 * DAY + timedelta(hours=3)
        courses = _courses(_daily(range(5)), now=now)

        assert len(courses) == 1
        assert courses[0]["status"] == svc.STATUS_ACTIVE
        assert courses[0]["start"] == T0.isoformat()
        assert courses[0]["end"] == (T0 + 5 * DAY).isoformat()
        assert courses[0]["days"] == 5
        assert courses[0]["prescriptionCount"] == 5
        assert courses[0]["gaps"] == []

    def test_one_missing_day_keeps_the_course_and_shows_the_gap(self):
        now = T0 + 10 * DAY
        courses = _courses(_daily([0, 1, 3, 4]), now=now)

        assert len(courses) == 1
        assert courses[0]["gaps"] == [
            {"start": (T0 + 2 * DAY).isoformat(), "end": (T0 + 3 * DAY).isoformat()}
        ]

    def test_two_missing_days_start_a_new_course(self):
        now = T0 + 10 * DAY
        courses = _courses(_daily([0, 1, 4, 5]), now=now)

        assert len(courses) == 2
        assert [c["days"] for c in courses] == [2, 2]
        assert all(c["status"] == svc.STATUS_FINISHED for c in courses)

    def test_prescription_time_jitter_is_not_a_gap(self):
        rows = [
            _row(T0, expire=T0 + DAY),
            # next day's prescription issued a few hours late
            _row(
                T0 + DAY + timedelta(hours=5), expire=T0 + 2 * DAY + timedelta(hours=5)
            ),
        ]
        courses = _courses(rows, now=T0 + 10 * DAY)

        assert len(courses) == 1
        assert courses[0]["gaps"] == []

    def test_missing_expire_date_counts_as_one_day(self):
        courses = _courses([_row(T0)], now=T0 + 10 * DAY)

        assert courses[0]["end"] == (T0 + DAY).isoformat()
        assert courses[0]["days"] == 1

    def test_planned_end_comes_from_period_total(self):
        rows = _daily(range(3), period_total=7)
        courses = _courses(rows, now=T0 + 2 * DAY + timedelta(hours=1))

        assert courses[0]["plannedEnd"] == (T0 + 7 * DAY).isoformat()
        assert courses[0]["plannedDays"] == 7
        assert courses[0]["days"] == 3

    def test_no_planned_end_without_period_total(self):
        courses = _courses(_daily(range(3)), now=T0 + DAY)

        assert courses[0]["plannedEnd"] is None
        assert courses[0]["plannedDays"] is None

    def test_suspension_ends_the_course(self):
        rows = _daily(range(2)) + [
            _row(
                T0 + 2 * DAY,
                expire=T0 + 3 * DAY,
                suspended_date=T0 + 2 * DAY + timedelta(hours=4),
            )
        ]
        courses = _courses(rows, now=T0 + 10 * DAY)

        assert courses[0]["status"] == svc.STATUS_SUSPENDED
        assert courses[0]["end"] == (T0 + 2 * DAY + timedelta(hours=4)).isoformat()
        assert courses[0]["days"] == 3

    def test_dose_change_splits_the_regimens(self):
        rows = _daily(range(2), dose=1.0) + _daily(range(2, 4), dose=2.0)
        courses = _courses(rows, now=T0 + 10 * DAY)

        assert len(courses) == 1
        assert [(r["dose"], r["start"], r["end"]) for r in courses[0]["regimens"]] == [
            (1.0, T0.isoformat(), (T0 + 2 * DAY).isoformat()),
            (2.0, (T0 + 2 * DAY).isoformat(), (T0 + 4 * DAY).isoformat()),
        ]

    def test_each_drug_has_its_own_course(self):
        rows = _daily(range(3), id_drug=1) + _daily(range(1, 2), id_drug=2)
        courses = _courses(rows, now=T0 + 10 * DAY)

        assert [(c["idDrug"], c["days"]) for c in courses] == [(1, 3), (2, 1)]


class TestCpoe:
    def test_order_planned_end_is_its_expire_date(self):
        rows = [_row(T0, expire=T0 + 7 * DAY, cpoe=True)]
        courses = _courses(rows, now=T0 + 2 * DAY + timedelta(hours=1))

        assert courses[0]["status"] == svc.STATUS_ACTIVE
        assert courses[0]["plannedEnd"] == (T0 + 7 * DAY).isoformat()
        assert courses[0]["plannedDays"] == 7
        assert courses[0]["days"] == 3

    def test_renewed_order_continues_the_course(self):
        rows = [
            _row(T0, expire=T0 + 3 * DAY, cpoe=True),
            _row(T0 + 3 * DAY, expire=T0 + 10 * DAY, cpoe=True),
        ]
        courses = _courses(rows, now=T0 + 4 * DAY)

        assert len(courses) == 1
        assert courses[0]["plannedEnd"] == (T0 + 10 * DAY).isoformat()
        assert courses[0]["prescriptionCount"] == 2

    def test_overlapping_orders_merge(self):
        rows = [
            _row(T0, expire=T0 + 5 * DAY, cpoe=True, suspended_date=T0 + 2 * DAY),
            _row(T0 + 2 * DAY, expire=T0 + 8 * DAY, cpoe=True, dose=2.0),
        ]
        courses = _courses(rows, now=T0 + 20 * DAY)

        assert len(courses) == 1
        assert courses[0]["status"] == svc.STATUS_FINISHED
        assert courses[0]["end"] == (T0 + 8 * DAY).isoformat()
        assert courses[0]["days"] == 8

    def test_suspended_order(self):
        rows = [_row(T0, expire=T0 + 7 * DAY, cpoe=True, suspended_date=T0 + 3 * DAY)]
        courses = _courses(rows, now=T0 + 5 * DAY)

        assert courses[0]["status"] == svc.STATUS_SUSPENDED
        assert courses[0]["end"] == (T0 + 3 * DAY).isoformat()
        assert courses[0]["plannedEnd"] == (T0 + 7 * DAY).isoformat()
        assert courses[0]["days"] == 3

    def test_future_suspension_is_still_active(self):
        rows = [_row(T0, expire=T0 + 7 * DAY, cpoe=True, suspended_date=T0 + 3 * DAY)]
        courses = _courses(rows, now=T0 + DAY)

        assert courses[0]["status"] == svc.STATUS_ACTIVE
        assert courses[0]["end"] == (T0 + 3 * DAY).isoformat()

    def test_open_ended_order_runs_until_now(self):
        now = T0 + 4 * DAY + timedelta(hours=2)
        courses = _courses([_row(T0, cpoe=True)], now=now)

        assert courses[0]["end"] == now.isoformat()
        assert courses[0]["plannedEnd"] is None
        assert courses[0]["days"] == 5


class TestDischarge:
    def test_course_is_clipped_at_discharge(self):
        rows = [_row(T0, expire=T0 + 7 * DAY, cpoe=True)]
        items = [svc.build_item(r, now=T0 + DAY) for r in rows]
        course = svc.group_courses(items)[0]

        result = svc.serialize_course(
            course, now=T0 + DAY, discharge_date=T0 + timedelta(hours=12)
        )

        assert result["status"] == svc.STATUS_FINISHED
        assert result["end"] == (T0 + timedelta(hours=12)).isoformat()
        assert result["days"] == 1
