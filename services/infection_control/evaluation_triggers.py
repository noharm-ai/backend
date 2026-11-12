"""Service: the triggers of an antimicrobial evaluation

ci_avaliacao_atm.gatilhos keeps the optional pending types an evaluation
watches as ints and every trigger with parameters as an object with a `type`
(an exam trigger, see exam_trigger_service). Read them here, never from the
raw list. Kept apart from the rule (infection_control_status_service), which
imports the trigger services, so they can all read them.
"""

from models.infection_control import AntimicrobialEvaluation


def pending_triggers(evaluation: AntimicrobialEvaluation) -> list[int]:
    """The optional reasons an evaluation watches for (pending types): its
    triggers (gatilhos) also keep the triggers with parameters, as objects"""
    return [t for t in evaluation.triggers or [] if isinstance(t, int)]
