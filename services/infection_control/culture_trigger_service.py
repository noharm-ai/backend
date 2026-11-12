"""Service: culture trigger of the infection control evaluations

An evaluation may watch the patient's cultures (an optional trigger, the
pending type InfectionControlPendingTypeEnum.CULTURE_RESULT kept among its
triggers as an int, like expiry and posology): while it is in force, a culture
result that reached the culture summary after the evaluation was made opens a
reason of its drug, settled by a new evaluation.

The cultures are read only from the DynamoDB culture summary
(noharm_cultura_resumo, culture_service.get_culture_summary), the same the
culture card and the protocol variable cultureReleaseTime read, and with the
same reading (culture_service.released_items): only an active item with a lab
result counts (a prediction or a collection still waiting for the lab is not a
result), whatever drug it tests. The summary holds only cultures with an
antibiogram row (a drug): one released without it is not there. The cultures
are the patient's, not only the admission's.

A result counts by when it reached the summary (resultArrival, written by the
culture cache job of backend-private when it first writes that result), not
by the lab's release date: a result can reach it long after its release (the
job runs every 5 minutes, the integration may be late), and the reviewer could
not have seen it before. An item written before the arrival was kept falls
back to its release date.

The culture cache job feeds that table every 5 minutes and then queues for the
light run the followed admissions of the patients with a new released result
whose evaluation in force watches cultures (gatilhos holding CULTURE_RESULT),
so each new result is seen soon after; the full run sees it anyway. Only the
scheduled job reads the summary (see apply_rule).
"""

from dataclasses import dataclass
from datetime import datetime

from models.enums import InfectionControlPendingTypeEnum
from models.infection_control import AntimicrobialEvaluation
from services import culture_service
from services.infection_control.evaluation_triggers import pending_triggers

# the new cultures a reason names (the reason still opens on any of them)
MAX_DETAILED_CULTURES = 10


@dataclass(frozen=True)
class CultureRelease:
    """A released result of the patient's cultures (one material,
    microorganism and drug of the culture summary): when the lab released it
    and when it reached the summary"""

    release_date: datetime
    arrival: datetime
    material: str | None
    microorganism: str | None


def watches_cultures(evaluation: AntimicrobialEvaluation) -> bool:
    """Whether an evaluation turned the culture trigger on"""
    return InfectionControlPendingTypeEnum.CULTURE_RESULT.value in pending_triggers(
        evaluation
    )


def released_cultures(cultures: list[dict]) -> list[CultureRelease]:
    """The released results of the culture summary (grouped by drug, see
    culture_service), with their release and arrival dates"""
    releases = []
    for item in culture_service.released_items(cultures):
        release_date = culture_service.parse_local_datetime(item.get("releaseDate"))
        if release_date is None:
            continue

        arrival = culture_service.parse_local_datetime(item.get("resultArrival"))

        releases.append(
            CultureRelease(
                release_date=release_date,
                arrival=arrival or release_date,
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
    results reached the summary after it was made (None otherwise): the latest
    release and the new cultures, one per material and microorganism, newest
    release first"""
    if not cultures or not watches_cultures(evaluation):
        return None

    since = evaluation.created_at
    new = [c for c in cultures if since < c.arrival <= now]
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
