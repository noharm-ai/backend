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

app_usr = Blueprint('app_usr',__name__)

@app_usr.route("/reports", methods=['GET'])
@jwt_required()
def getReports():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    
    if user: 
        return {
            'status': 'success',
            'reports': Memory.getMem('reports', []),
        }, status.HTTP_200_OK 
    else:
        return {
            'status': 'error',
            'message': 'HTTP_401_UNAUTHORIZED'
        }, status.HTTP_401_UNAUTHORIZED

@app_usr.route("/user", methods=['GET'])
@jwt_required()
def getUser():
    user = User.find(get_jwt_identity())

    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    return {
        'status': 'success',
        'data': {
            'id': user.id,
            'sign': user.config['sign'] if 'sign' in user.config else ''
        }
    }, status.HTTP_200_OK

@app_usr.route("/user", methods=['PUT'])
@jwt_required()
def setUser():
    data = request.get_json()
    user = User.find(get_jwt_identity())

    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    password = data.get('password', None)
    newpassword = data.get('newpassword', None)
    user = User.authenticate(user.email, password)

    if not user or not newpassword: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    update = {'password': func.crypt(newpassword, func.gen_salt('bf',8)) }
    db.session.query(User)\
            .filter(User.id == user.id)\
            .update(update, synchronize_session='fetch')
    
    return tryCommit(db, user.id)

@app_usr.route("/user/forget", methods=['GET'])
def forgetPassword():
    email = request.args.get('email', None)
    user = User.query.filter_by(email=email).first()
    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    expires = timedelta(hours=24)
    reset_token = create_access_token(identity=user.id, expires_delta=expires)

    msg = Message()
    msg.subject = "NoHarm: Esqueci a senha"
    msg.sender = Config.MAIL_SENDER
    msg.recipients = [user.email]
    msg.html = render_template('reset_email.html', user=user.name, token=reset_token, host=Config.MAIL_HOST)
    mail.send(msg)

    return {
        'status': 'success',
        'message': 'Email enviado com sucesso para: ' + email
    }, status.HTTP_200_OK

@app_usr.route("/user/reset", methods=['POST'])
def resetPassword():
    data = request.get_json()

    reset_token = data.get('reset_token', None)
    newpassword = data.get('newpassword', None)

    if not reset_token or not newpassword:
        return { 'status': 'error', 'message': 'Token Inexistente!' }, status.HTTP_400_BAD_REQUEST

    user_token = decode_token(reset_token)
    if not 'sub' in user_token:
        return { 'status': 'error', 'message': 'Token Expirou!' }, status.HTTP_400_BAD_REQUEST

    user_id = user_token['sub']
    user = User.find(user_id)
    if not user: 
        return { 'status': 'error', 'message': 'Usuário Inexistente!' }, status.HTTP_400_BAD_REQUEST

    update = {'password': func.crypt(newpassword, func.gen_salt('bf',8)) }
    db.session.query(User)\
            .filter(User.id == user.id)\
            .update(update, synchronize_session='fetch')
    
    return tryCommit(db, user.id)