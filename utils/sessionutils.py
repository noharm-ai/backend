import logging
from utils import status

from exception.authorization_error import AuthorizationError


def tryCommit(db, recId, allow=True):
    if not allow:
        db.session.rollback()
        db.session.close()
        db.session.remove()
        return {
            "status": "error",
            "message": "Usuário não autorizado",
        }, status.HTTP_401_UNAUTHORIZED

    try:
        db.session.commit()
        db.session.close()
        db.session.remove()

        return {"status": "success", "data": recId}, status.HTTP_200_OK
    except AuthorizationError as e:
        db.session.rollback()
        db.session.close()
        db.session.remove()

        return {
            "status": "error",
            "message": "Usuário não autorizado.",
        }, status.HTTP_401_UNAUTHORIZED
    except AssertionError as e:
        db.session.rollback()
        db.session.close()
        db.session.remove()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(str(e))

        return {
            "status": "error",
            "message": "Ocorreu um erro inesperado.",
        }, status.HTTP_400_BAD_REQUEST
    except Exception as e:
        db.session.rollback()
        db.session.close()
        db.session.remove()

        logging.basicConfig()
        logger = logging.getLogger("noharm.backend")
        logger.error(str(e))

        return {
            "status": "error",
            "message": "Ocorreu um erro inesperado.",
        }, status.HTTP_500_INTERNAL_SERVER_ERROR
