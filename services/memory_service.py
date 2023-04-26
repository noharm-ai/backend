from models.main import db
from models.appendix import *
from models.prescription import *

from flask_jwt_extended import (get_jwt_identity)

def has_feature(feature):
    user = User.query.get(get_jwt_identity())
    user_features = user.config['features'] if user.config and 'features' in user.config else []

    if feature in user_features:
        return True

    features = db.session.query(Memory).filter(Memory.kind == 'features').first()

    if features is None:
        return False
    
    if (feature not in features.value):
        return False

    return True

def get_memory(key):
    return db.session.query(Memory).filter(Memory.kind == key).first()