from flask import g

from models.main import db
from models.appendix import Memory, GlobalMemory
from models.enums import MemoryEnum, FeatureEnum, AppFeatureFlagEnum, GlobalMemoryEnum


def has_feature(user_feature: FeatureEnum):
    """
    Tenant features
    """
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


def has_feature_flag(flag: AppFeatureFlagEnum):
    """
    System features
    """
    feature_flags = g.get("feature_flags", {})

    if not feature_flags:
        memory = (
            db.session.query(GlobalMemory)
            .filter(GlobalMemory.kind == GlobalMemoryEnum.FEATURE_FLAGS.value)
            .first()
        )

        if memory != None:
            feature_flags = memory.value
            g.feature_flags = feature_flags

    return feature_flags.get(flag.value, False)
