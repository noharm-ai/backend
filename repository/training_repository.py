"""Repository: training related operations"""

from models.main import db
from models.appendix import Training, TrainingItem


def list_trainings() -> list[Training]:
    """List all active training records ordered by position"""
    return (
        db.session.query(Training)
        .filter(Training.active == True)
        .order_by(Training.position)
        .all()
    )


def list_training_items(training_id: int) -> list[TrainingItem]:
    """List all active items of a training record ordered by position"""
    return (
        db.session.query(TrainingItem)
        .filter(
            TrainingItem.training_id == training_id,
            TrainingItem.active == True,
        )
        .order_by(TrainingItem.position)
        .all()
    )
