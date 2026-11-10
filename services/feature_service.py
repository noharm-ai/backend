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
    Tenant features (the features memory), read once per request
    """
    features = g.get("features", None)

    if features is None:
        features_memory = (
            db.session.query(Memory)
            .filter(Memory.kind == MemoryEnum.FEATURES.value)
            .first()
        )
        features = features_memory.value if features_memory else []
        if features_memory:
            g.features = features

    return user_feature.value in features


def set_features(features: list):
    """Keeps the tenant features a caller has just read (the features memory)
    for the rest of the request, so has_feature doesn't read them again"""
    g.features = features


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
    System features (the feature flags global memory), read once per request:
    no flags is an answer too, and is not read again
    """
    feature_flags = g.get("feature_flags", None)

    if feature_flags is None:
        memory = (
            db.session.query(GlobalMemory)
            .filter(GlobalMemory.kind == GlobalMemoryEnum.FEATURE_FLAGS.value)
            .first()
        )

        feature_flags = (memory.value if memory is not None else None) or {}
        g.feature_flags = feature_flags

    return feature_flags.get(flag.value, False)
