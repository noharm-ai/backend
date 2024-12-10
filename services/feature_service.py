from flask import g

from models.main import db
from models.appendix import Memory
from models.enums import MemoryEnum, FeatureEnum


def is_cpoe():
    return g.get("is_cpoe", False)


def has_feature(user_feature: FeatureEnum):
    features = g.get("features", [])

    if not features:
        features_memory = (
            db.session.query(Memory)
            .filter(Memory.kind == MemoryEnum.FEATURES.value)
            .first()
        )
        if features_memory:
            features = features_memory.value
            g.features = features

    return user_feature.value in features
