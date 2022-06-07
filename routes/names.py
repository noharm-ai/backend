import requests
from models.main import *
from models.appendix import *
from flask import Blueprint
from flask_jwt_extended import (jwt_required, get_jwt_identity)

app_names = Blueprint('app_names',__name__)

@app_names.route('/names/<int:idPatient>', methods=['GET'])
@jwt_required()
def proxy_name(idPatient):
    user = User.find(get_jwt_identity())
    config = Memory.getNameUrl(user.schema)
    
    url = config["to"].replace("{idPatient}", str(idPatient))

    response = requests.get(\
        url=url,\
        headers=config['headers'])
    
    return response.json()