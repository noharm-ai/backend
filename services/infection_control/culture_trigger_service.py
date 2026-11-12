"""Service: culture trigger of the infection control evaluations

An evaluation may watch the patient's cultures (an optional trigger, the
pending type InfectionControlPendingTypeEnum.CULTURE_RESULT kept among its
triggers as an int, like expiry and posology): while it is in force, a culture
result released after the evaluation was made opens a reason of its drug,
settled by a new evaluation.

The cultures are read only from the DynamoDB culture summary
(noharm_cultura_resumo, culture_service.get_culture_summary), the same the
culture card and the protocol variable cultureReleaseTime read, and with the
same reading: only an active item with a lab result counts (a prediction or a
collection still waiting for the lab is not a result), whatever drug it tests.
The cultures are the patient's, not only the admission's.

The culture cache job of backend-private feeds that table every 5 minutes and
then queues for the light run the followed admissions of the patients with a
new released result whose evaluation in force watches cultures (gatilhos
holding CULTURE_RESULT), so each new result is seen soon after; the full run
sees it anyway.

Only results the reviewer could not have seen count: released after the
evaluation was made. So a new evaluation never reopens the reason on the
culture that opened it.
"""

from dataclasses import dataclass
from datetime import datetime

from models.enums import InfectionControlPendingTypeEnum
from models.infection_control import AntimicrobialEvaluation
from services import culture_service

# the new cultures a reason names (the reason still opens on any of them)
MAX_DETAILED_CULTURES = 10


@dataclass(frozen=True)
class CultureRelease:
    """A released result of the patient's cultures (one material,
    microorganism and drug of the culture summary)"""

    release_date: datetime
    material: str | None
    microorganism: str | None


def watches_cultures(evaluation: AntimicrobialEvaluation) -> bool:
    """Whether an evaluation turned the culture trigger on (gatilhos keeps the
    pending types as ints and the triggers with parameters as objects)"""
    return InfectionControlPendingTypeEnum.CULTURE_RESULT.value in (
        evaluation.triggers or []
    )


def _parse_date(value) -> datetime | None:
    """A release date of the culture summary in local time, as the rule
    compares it (None when missing or invalid)"""
    if not value:
        return None

    try:
        date = datetime.fromisoformat(f"{value}")
    except (TypeError, ValueError):
        return None

    # the integration may or may not carry an offset: one that does is read
    # in local time, as the evaluations are kept
    if date.tzinfo is not None:
        date = date.astimezone().replace(tzinfo=None)

    return date


def released_cultures(cultures: list[dict]) -> list[CultureRelease]:
    """The released results of the culture summary (grouped by drug, see
    culture_service), as latest_release_date reads them: an item without a
    lab result is a prediction or a pending collection, and doesn't count"""
    releases = []
    for drug in cultures or []:
        for item in drug.get("items") or []:
            if item.get("result") is None:
                continue

            release_date = _parse_date(item.get("releaseDate"))
            if release_date is None:
                continue

            releases.append(
                CultureRelease(
                    release_date=release_date,
                    material=item.get("material"),
                    microorganism=item.get("microorganism"),
                )
            )

    return releases


def load_cultures(
    schema: str, evaluations: list[AntimicrobialEvaluation], patient
) -> list[CultureRelease] | None:
    """The released culture results of the admission's patient, read once for
    the rule (None when no evaluation in force watches cultures). A failure to
    read the summary reads as no culture (culture_service logs it): the
    reasons already open stay open, as the rule never resolves them alone"""
    if not any(watches_cultures(e) for e in evaluations):
        return None

    if patient is None:
        return []

    return released_cultures(
        culture_service.get_culture_summary(schema=schema, id_patient=patient.idPatient)
    )


def culture_match(
    evaluation: AntimicrobialEvaluation,
    cultures: list[CultureRelease] | None,
    now: datetime,
) -> dict | None:
    """The details of the reason an evaluation watching cultures opens, when
    results were released after it was made (None otherwise): the latest
    release and the new cultures, one per material and microorganism, newest
    first"""
    if not cultures or not watches_cultures(evaluation):
        return None

    since = evaluation.created_at
    new = [c for c in cultures if since < c.release_date <= now]
    if not new:
        return None

    # the drugs tested against a culture each have an item: one entry per
    # material and microorganism, with its latest release
    latest: dict[tuple, CultureRelease] = {}
    for culture in new:
        key = (culture.material, culture.microorganism)
        if key not in latest or culture.release_date > latest[key].release_date:
            latest[key] = culture

    ordered = sorted(
        latest.values(),
        key=lambda c: (c.release_date, c.material or "", c.microorganism or ""),
        reverse=True,
    )

    return {
        "releaseDate": ordered[0].release_date.isoformat(),
        "cultures": [
            {
                "material": c.material,
                "microorganism": c.microorganism,
                "releaseDate": c.release_date.isoformat(),
            }
            for c in ordered[:MAX_DETAILED_CULTURES]
        ],
    }
