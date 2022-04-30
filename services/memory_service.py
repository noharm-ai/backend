from flask_api import status

from models.main import db
from models.appendix import *
from models.prescription import *

def has_feature(feature):
    features = db.session.query(Memory).filter(Memory.kind == 'features').first()

    if features is None:
        return False

    
    if (feature not in features.value):
        return False

    return True