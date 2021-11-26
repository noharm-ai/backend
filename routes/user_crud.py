from sqlalchemy.sql.expression import update
from password_generator import PasswordGenerator
from models.main import *
from models.appendix import *
from flask import Blueprint, request, render_template
from flask_jwt_extended import (jwt_required, get_jwt_identity)
from flask_jwt_extended import create_access_token, decode_token
from .utils import tryCommit
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import render_template
from flask_mail import Message
from config import Config

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
        usuarioEncontrado = User.findByEmail(userEmail)
        
        if usuarioEncontrado != None: 
            return {
                'status': 'error',
                'message': 'Já existe um usuário com este email!',
                'code': 'errors.emailExists'
            }, status.HTTP_400_BAD_REQUEST

       
        nameFound = User.findByName(data.get('name', None))

        if nameFound != None:
            return {
                'status': 'error',
                'message': 'Ja existe um usuário com este nome!',
                'code': 'errors.nameExists'
            }, status.HTTP_400_BAD_REQUEST


        newUser = User()
        newUser.email = data.get('email', None)
        newUser.name = data.get('name', None)
        newUser.external = data.get('external', None)
        newUser.active =  bool(data.get('active', True))
        newUser.schema = user.schema
        pwo = PasswordGenerator()
        pwo.minlen = 6
        pwo.maxlen = 16 
        newUser.password = func.crypt(pwo.generate(), func.gen_salt('bf',8))
        newUser.config = '{ }'
        db.session.add(newUser)
        db.session.flush()
        return tryCommit(db, newUser.id)
    else:
        updatedUser = User.query.get(idUser)

        if (updatedUser is None):
            return { 
                'status': 'error', 'message': '!Usuário Inexistente!', 'code': 'errors.invalidUser'
            }, status.HTTP_400_BAD_REQUEST
    
        changeEmail = updatedUser.email != data.get('email', None)

        if changeEmail:
            userEmail = data.get('email', None)
            usuarioEncontrado = User.findByEmail(userEmail)
    
            if usuarioEncontrado != None: 
                return {
                    'status': 'error',
                    'message': 'Já existe um usuário com este email!',
                    'code': 'errors.emailExists'
                }, status.HTTP_400_BAD_REQUEST


        changeName = updatedUser.name != data.get('name', None)

        if changeName:
            usuarioEncontrado = User.findByName(data.get('name', None))
    
            if usuarioEncontrado != None: 
                return {
                    'status': 'error',
                    'message': 'Já existe um usuário com este nome!',
                    'code': 'errors.nameExists'
                }, status.HTTP_400_BAD_REQUEST



        updatedUser.email = data.get('email', None)
        updatedUser.name = data.get('name', None)
        updatedUser.external = data.get('external', None)
        updatedUser.active =  bool(data.get('active', True))
        
        db.session.add(updatedUser)
        db.session.flush()

        # if changeEmail: 

        #     expires = timedelta(hours=24)
        #     reset_token = create_access_token(identity=updatedUser.id, expires_delta=expires)
            
        #     msg = Message()
        #     msg.subject = "NoHarm: Alteração de email"
        #     msg.sender = Config.MAIL_SENDER
        #     msg.recipients = [updatedUser.email]
        #     msg.html = render_template('reset_email.html', user=updatedUser.name, token=reset_token, host=Config.MAIL_HOST)
        #     mail.send(msg)
        
        # db.session.query(User)\
        #     .filter(User.id == idUser)\
        #     .update(update, synchronize_session='fetch')

        # if 'password' in data.keys(): password = data.get('password', None)
        # if 'newpassword' in data.keys(): newpassword = data.get('newpassword', None)
        # user = User.authenticate(user.email, password)
        # if not user or not newpassword: 
        #     return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST
        # update = {'password': func.crypt(newpassword, func.gen_salt('bf',8)) }
        # db.session.query(User)\
        #         .filter(User.id == user.id)\
        #         .update(update, synchronize_session='fetch')

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