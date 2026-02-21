from .models import Document, ProcessedResult
from .utils import (
    extract_text_from_file, summarize_text, generate_answers, 
    analyze_text, temporary_file_from_content
)

class DocumentService:
    @staticmethod
    def process_document(document, options=None):
        """
        Process a document based on its processing_type and options.
        Returns the created ProcessedResult object.
        """
        options = options or {}
        selected_model = options.get('model', 'gpt-3.5-turbo')
        
        # Extract text using the temporary file context manager
        with temporary_file_from_content(document.file_content, suffix=f".{document.document_type}") as temp_file_path:
            extracted_text = extract_text_from_file(temp_file_path, document.document_type)
        
        # Parse options
        target_words = options.get('target_words')
        max_tokens = options.get('max_tokens')
        preset_param = options.get('preset')
        
        # Process the text based on the selected processing type
        if document.processing_type == 'summarize':
            result_text = summarize_text(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)
        elif document.processing_type == 'generate':
            result_text = generate_answers(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)
        elif document.processing_type == 'analyze':
            result_text = analyze_text(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)
        else:
            result_text = "Unknown processing type"

        
        # Save the processed result
        processed_result = ProcessedResult.objects.create(
            document=document,
            result_text=result_text
        )
        
        return processed_result, extracted_text
