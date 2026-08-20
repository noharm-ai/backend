import logging
import re

from flask_mail import Message, Mail

# Conservative, ASCII-only address format. Rejects accented/invisible characters,
# spaces, quotes, angle brackets and separators (",", ";") that show up when more
# than one address is pasted into the field.
# Local part: RFC 5322 "dot-atom" (no leading/trailing/consecutive dots), max 64 chars.
# Domain: dot-separated labels (max 63 chars each) and an alphabetic TLD of 2+ chars,
# so an address without a public domain (e.g. "user@localhost") is rejected.
EMAIL_PATTERN = re.compile(
    r"(?!\.)(?!.*\.\.)[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}(?<!\.)"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}\Z"
)

# RFC 5321 limit for a forward path (local part + "@" + domain).
EMAIL_MAX_LENGTH = 254


def is_valid_email(email: str) -> bool:
    """Check whether the email has a valid format, without touching the network"""
    if not email or len(email) > EMAIL_MAX_LENGTH:
        return False

    return EMAIL_PATTERN.match(email) is not None


def sendEmail(subject, sender, emails, html):
    try:
        msg = Message()
        mail = Mail()
        msg.subject = subject
        msg.sender = sender
        msg.recipients = emails
        msg.html = html
        mail.send(msg)
    except Exception:
        logger = logging.getLogger("noharm.backend")
        logger.error("Could not send new user email")
