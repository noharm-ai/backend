import os
from flask_jwt_extended import (get_jwt_identity)

from models.main import *
from exception.validation_error import ValidationError

def api_endpoint():
    def inner(f):
        def decorator_f(*args, **kwargs):
            try:
                userContext = User.find(get_jwt_identity())
                dbSession.setSchema(userContext.schema)
                os.environ['TZ'] = 'America/Sao_Paulo'
                
                result = f(*args, **kwargs)
                
                # TODO: review this rule
                if userContext.permission():
                    db.session.commit()
                else:
                    # block users "suporte"
                    db.session.rollback()

                return {
                    'status': 'success',
                    'data': result
                }, status.HTTP_200_OK
            except ValidationError as e:
                db.session.rollback()

                return {
                    'status': 'error',
                    'message': e.message,
                    'code': e.code
                }, e.httpStatus
            except AssertionError as e:
                db.session.rollback()

                logging.basicConfig()
                logger = logging.getLogger('noharm.backend')
                logger.error(str(e))

                return {
                    'status': 'error',
                    'message': str(e)
                }, status.HTTP_400_BAD_REQUEST
            except Exception as e:
                db.session.rollback()

                logging.basicConfig()
                logger = logging.getLogger('noharm.backend')
                logger.error(str(e))

                return {
                    'status': 'error',
                    'message': str(e)
                }, status.HTTP_500_INTERNAL_SERVER_ERROR

        decorator_f.__name__ = f.__name__
        return decorator_f
    return inner