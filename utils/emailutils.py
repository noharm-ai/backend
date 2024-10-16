import logging
from flask_mail import Message, Mail


def sendEmail(subject, sender, emails, html):
    try:
        msg = Message()
        mail = Mail()
        msg.subject = subject
        msg.sender = sender
        msg.recipients = emails
        msg.html = html
        mail.send(msg)
    except:
        logger = logging.getLogger("noharm.backend")
        logger.error("Could not send new user email")
