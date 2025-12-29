"""Service: queue related operations"""

import json

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User
from utils import status


@has_permission(Permission.READ_BASIC_FEATURES)
def check_sqs_message(request_id: str, user_context: User):
    """Check SQS queue for message with specific request ID"""

    if not request_id:
        raise ValidationError(
            "Request ID inválido",
            "errors.invalidParameter",
            status.HTTP_400_BAD_REQUEST,
        )

    # Get SQS queue URL
    sqs_client = boto3.client("sqs", region_name=Config.NIFI_SQS_QUEUE_REGION)

    try:
        # Get queue URL for "backend" queue
        queue_url_response = sqs_client.get_queue_url(QueueName="backend")
        queue_url = queue_url_response["QueueUrl"]
    except Exception as e:
        raise ValidationError(
            f"Erro ao acessar fila SQS: {str(e)}",
            "errors.sqsError",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Receive messages from queue (check once, don't wait)
    try:
        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,  # Check up to 10 messages
            WaitTimeSeconds=0,  # Don't wait, return immediately
            MessageAttributeNames=["All"],
            AttributeNames=["All"],
        )
    except Exception as e:
        raise ValidationError(
            f"Erro ao ler mensagens da fila: {str(e)}",
            "errors.sqsError",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    messages = response.get("Messages", [])

    # Search for message with matching request ID
    for message in messages:
        message_body = json.loads(message.get("Body", "{}"))
        receipt_handle = message.get("ReceiptHandle")

        message_request_id = message_body.get("requestContext", {}).get("requestId")
        message_response = message_body.get("responsePayload", {})

        try:
            if isinstance(message_response, str):
                message_response = json.loads(message_response)
        except json.JSONDecodeError:
            pass

        # Check if request_id matches in message body or attributes
        if message_request_id == request_id:
            # Delete the message from the queue
            try:
                sqs_client.delete_message(
                    QueueUrl=queue_url, ReceiptHandle=receipt_handle
                )
            except Exception as e:
                raise ValidationError(
                    f"Erro ao deletar mensagem da fila: {str(e)}",
                    "errors.sqsError",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return {
                "found": True,
                "message_id": message.get("MessageId"),
                "receipt_handle": receipt_handle,
                "response": message_response,
                "timestamp": message.get("Attributes", {}).get("SentTimestamp"),
                "deleted": True,
            }

    # Message not found in current batch
    return {
        "found": False,
        "checked_messages": len(messages),
    }
