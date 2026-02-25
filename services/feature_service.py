from flask import g

from config import Config
from models.appendix import GlobalMemory, Memory
from models.enums import (
    AppFeatureFlagEnum,
    FeatureEnum,
    GlobalMemoryEnum,
    MemoryEnum,
    NoHarmENV,
)
from models.main import db


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


def has_user_feature(user_feature: FeatureEnum):
    """
    Check if user has a specific feature
    """
    if Config.ENV == NoHarmENV.TEST.value:
        return []

    features = g.get("user_features", [])

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
