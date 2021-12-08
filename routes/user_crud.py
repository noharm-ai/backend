from sqlalchemy.sql.expression import update
from password_generator import PasswordGenerator
from models.main import *
from models.appendix import *
from flask import Blueprint, request, render_template
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from flask_jwt_extended import create_access_token, decode_token
from .utils import tryCommit, sendEmail
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import render_template
from config import Config
from flask_mail import Message, Mail


app_user_crud = Blueprint('app_user_crud',__name__)

@app_user_crud.route("/editUser", methods=['PUT'])
@app_user_crud.route('/editUser/<int:idUser>', methods=['PUT'])
@jwt_required()
def createUser(idUser = None):
    data = request.get_json()
    user = User.query.get(get_jwt_identity())

    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!', 'code': 'errors.invalidUser' }, status.HTTP_400_BAD_REQUEST
    
    dbSession.setSchema(user.schema)

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    if ('userAdmin' not in roles):
        return {
            'status': 'error',
            'message': 'Usuário não autorizado',
            'code': 'errors.unauthorizedUser'
        }, status.HTTP_401_UNAUTHORIZED

    if not idUser: 
    
        userEmail = data.get('email', None)
        userNotFound = User.findByEmail(userEmail)
        
        if userNotFound != None: 
            return {
                'status': 'error',
                'message': 'Já existe um usuário com este email!',
                'code': 'errors.emailExists'
            }, status.HTTP_400_BAD_REQUEST

        userName = data.get('name', None)
        userByName = User.findByName(userName)

        if userByName != None:
            return {
                'status': 'error',
                'message': 'Ja existe um usuário com este nome!',
                'code': 'errors.nameExists'
            }, status.HTTP_400_BAD_REQUEST


        newUser = User()
        newUser.email = userEmail
        newUser.name = userName
        newUser.external = data.get('external', None)
        newUser.active =  bool(data.get('active', True))
        newUser.schema = user.schema
        pwo = PasswordGenerator()
        pwo.minlen = 6
        pwo.maxlen = 16
        password = pwo.generate()
        newUser.password = func.crypt(password, func.gen_salt('bf', 8))
        newUser.config = '{ }'
        db.session.add(newUser)
        db.session.flush()

        response, rstatus = tryCommit(db, newUser.id)
        print("!!!!RESPOSTA!!!!",rstatus)

        if rstatus == status.HTTP_200_OK:
            sendEmail(
                "Boas-vindas noHarm: Credenciais",
                Config.MAIL_SENDER,
                [userEmail],
                render_template('new_user.html', user= userName, email= userEmail, password=password , host=Config.MAIL_HOST)
            )

        return response
    else:
        updatedUser = User.query.get(idUser)

        if (updatedUser is None):
            return { 
                'status': 'error', 'message': '!Usuário Inexistente!', 'code': 'errors.invalidUser'
            }, status.HTTP_400_BAD_REQUEST
    

        if updatedUser.name != data.get('name', None):
            userFound = User.findByName(data.get('name', None))
    
            if userFound != None: 
                return {
                    'status': 'error',
                    'message': 'Já existe um usuário com este nome!',
                    'code': 'errors.nameExists'
                }, status.HTTP_400_BAD_REQUEST


        updatedUser.name = data.get('name', None)
        updatedUser.external = data.get('external', None)
        updatedUser.active =  bool(data.get('active', True))
        
        db.session.add(updatedUser)
        db.session.flush()
        
        return tryCommit(db, updatedUser.id)

@app_user_crud.route('/users', methods=['GET'])
@jwt_required()
def getUsers():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    roles = user.config['roles'] if user.config and 'roles' in user.config else []
    
    if ('userAdmin' not in roles): 
        return {
            'status': 'error',
            'message': 'Usuário não autorizado',
            'code': 'errors.unauthorizedUser',
        }, status.HTTP_401_UNAUTHORIZED

    users = User.query.filter_by(schema=user.schema).all()

    results = []
    for u in users:
        results.append({
            'id': u.id,
            'external': u.external,
            'name': u.name,
            'email': u.email,
            'active': u.active
        })

    return {
        'status': 'success',
        'data': results
    }, status.HTTP_200_OK