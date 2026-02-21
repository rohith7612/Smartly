from celery import shared_task
from .models import Document
from .services import DocumentService
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_document_task(document_id, options=None):
    """
    Celery task to process a document asynchronously.
    """
    try:
        document = Document.objects.get(id=document_id)
        # Call the service to process the document
        # Service returns (processed_result, extracted_text)
        processed_result, _ = DocumentService.process_document(document, options)
        return processed_result.id
    except Document.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        # Re-raise exception so task state becomes FAILURE
        raise e
