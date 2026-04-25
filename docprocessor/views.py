from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, ListFlowable, ListItem, Preformatted
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
import re
import os
import json
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from django.conf import settings
from django.core.paginator import Paginator
from .models import Document, ProcessedResult, YouTubeVideo, YouTubeProcessedResult, ChatSession, ChatMessage
from .forms import DocumentUploadForm, DocumentSelectForm, DocumentMultiSelectForm, YouTubeURLForm, ModelSelectionForm
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.core.cache import cache
from .utils import (
    extract_text_from_file, summarize_text, generate_answers,
    analyze_text, get_youtube_video_id,
    get_youtube_transcript, chat_with_openai, translate_text_free,
    recommend_youtube_videos_web, calculate_max_tokens,
    get_document_type_from_filename, temporary_file_from_content,
    get_extracted_text_for_doc,
)
from .utils import _route_chat as chat_with_model

def home(request):
    """Home page view"""
    return render(request, 'docprocessor/home.html')

def dashboard(request):
    """Dashboard view showing user's documents and results with per-section pagination"""
    if request.user.is_authenticated:
        documents_qs = Document.objects.filter(user=request.user).order_by('-uploaded_at')
        actions_qs = ProcessedResult.objects.filter(document__user=request.user).select_related('document').order_by('-processed_at')
        youtube_videos_qs = YouTubeVideo.objects.filter(user=request.user).order_by('-processed_at')
        youtube_results_qs = YouTubeProcessedResult.objects.filter(user=request.user).select_related('youtube_video').order_by('-processed_at')
    else:
        documents_qs = Document.objects.all().order_by('-uploaded_at')
        actions_qs = ProcessedResult.objects.all().select_related('document').order_by('-processed_at')
        youtube_videos_qs = YouTubeVideo.objects.all().order_by('-processed_at')
        youtube_results_qs = YouTubeProcessedResult.objects.all().select_related('youtube_video').order_by('-processed_at')


    # Per-section pagination (5 items per page)
    docs_paginator = Paginator(documents_qs, 5)
    actions_paginator = Paginator(actions_qs, 5)
    yt_paginator = Paginator(youtube_videos_qs, 5)
    res_paginator = Paginator(youtube_results_qs, 5)

    docs_page_number = request.GET.get('docs_page', 1)
    actions_page_number = request.GET.get('actions_page', 1)
    yt_page_number = request.GET.get('yt_page', 1)
    res_page_number = request.GET.get('res_page', 1)

    documents_page = docs_paginator.get_page(docs_page_number)
    actions_page = actions_paginator.get_page(actions_page_number)
    youtube_videos_page = yt_paginator.get_page(yt_page_number)
    youtube_results_page = res_paginator.get_page(res_page_number)

    context = {
        'documents_page': documents_page,
        'actions_page': actions_page,
        'youtube_videos_page': youtube_videos_page,
        'youtube_results_page': youtube_results_page,
    }
    return render(request, 'docprocessor/dashboard.html', context)

@login_required
def delete_document(request, document_id):
    """Delete an uploaded document owned by the current user."""
    document = get_object_or_404(Document, id=document_id, user=request.user)
    if request.method == 'POST':
        title = document.title
        try:
            # File content is stored in database, so just delete the document record
            document.delete()
            messages.success(request, f'Deleted "{title}" successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting document: {e}')
        return redirect('dashboard')
    messages.warning(request, 'Invalid request method for delete.')
    return redirect('dashboard')

@login_required
def delete_processed_result(request, result_id):
    """Delete a processed document result owned by the current user."""
    pr = get_object_or_404(ProcessedResult, id=result_id)
    if pr.document.user != request.user:
        messages.error(request, 'You do not have permission to delete this result.')
        return redirect('dashboard')
    if request.method == 'POST':
        try:
            pr.delete()
            messages.success(request, 'Deleted processed result successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting processed result: {e}')
        return redirect('dashboard')
    messages.warning(request, 'Invalid request method for delete.')
    return redirect('dashboard')


@login_required
def delete_youtube_video(request, video_id):
    """Delete a YouTubeVideo owned by the current user."""
    youtube_video = get_object_or_404(YouTubeVideo, id=video_id, user=request.user)
    if request.method == 'POST':
        title = youtube_video.title or youtube_video.url
        try:
            youtube_video.delete()  # cascades to processed results via FK
            messages.success(request, f'Deleted YouTube video "{title}" successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting YouTube video: {e}')
        return redirect('dashboard')
    messages.warning(request, 'Invalid request method for delete.')
    return redirect('dashboard')


@login_required
def delete_youtube_result(request, result_id):
    """Delete a YouTubeProcessedResult owned by the current user."""
    yt_result = get_object_or_404(YouTubeProcessedResult, id=result_id, user=request.user)
    if request.method == 'POST':
        base = yt_result.youtube_video.title or yt_result.youtube_video.url
        try:
            yt_result.delete()
            messages.success(request, f'Deleted processed result for "{base}" successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting processed result: {e}')
        return redirect('dashboard')
    messages.warning(request, 'Invalid request method for delete.')
    return redirect('dashboard')

def register_view(request):
    """User registration view"""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, 'Welcome! Your account has been created.')
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserCreationForm()
    return render(request, 'docprocessor/register.html', {'form': form})

def upload_document(request):
    """View for uploading documents"""
    if request.method == 'POST':
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            uploaded_file = form.cleaned_data['file']
            
            # Store file content in database
            document.file_content = uploaded_file.read()
            document.filename = uploaded_file.name
            document.file_size = uploaded_file.size
            document.content_type = uploaded_file.content_type
            
            # Default processing type during upload (user selects actual action later)
            document.processing_type = 'summarize'
            
            # Determine document type based on file extension
            document.document_type = get_document_type_from_filename(uploaded_file.name)
            
            # Associate with user if authenticated
            if request.user.is_authenticated:
                document.user = request.user
            
            document.save()
            messages.success(request, 'Document uploaded successfully!')
            # Do not process immediately; send user to dashboard with confirmation
            return redirect('dashboard')
    else:
        form = DocumentUploadForm()
    
    return render(request, 'docprocessor/upload.html', {'form': form})

def serve_document_file(request, document_id):
    """Serve document file from database"""
    document = get_object_or_404(Document, id=document_id)
    
    # Check if user has permission to access this document
    if document.user and document.user != request.user and not request.user.is_staff:
        return HttpResponse("Unauthorized", status=401)
    
    response = HttpResponse(document.file_content, content_type=document.content_type)
    response['Content-Disposition'] = f'inline; filename="{document.filename}"'
    response['Content-Length'] = document.file_size
    return response

def process_document(request, document_id):
    """Process the uploaded document"""
    document = get_object_or_404(Document, id=document_id)
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    
    # Prepare options
    options = {
        'model': selected_model,
        'words': request.GET.get('words'),
        'tokens': request.GET.get('tokens'),
        'length': request.GET.get('length'),
        'preset': request.GET.get('preset')
    }
    
    # Calculate max_tokens logic (simplified here, ideally move calculation to service or keep here if view-specific)
    # For now, let's pass raw params and let service handle or pre-calculate here.
    # To match previous logic exactly, we should pre-calculate max_tokens here or move that logic to service.
    # Let's move the calculation logic to the service in a future step or just duplicate for now to be safe, 
    # but actually the service I wrote expects pre-calculated values or handles them. 
    # Let's update the service to handle raw params or do it here.
    # Doing it here for now to keep service simple.
    
    max_tokens, target_words = calculate_max_tokens(
        words=request.GET.get('words'),
        tokens=request.GET.get('tokens'),
        length=request.GET.get('length')
    )
        
    service_options = {
        'model': selected_model,
        'target_words': target_words,
        'max_tokens': max_tokens,
        'preset': request.GET.get('preset')
    }

    from .tasks import process_document_task
    task = process_document_task.delay(document.id, service_options)
    
    return redirect(f"{reverse('document_processing_status', args=[document.id])}?task_id={task.id}")

def document_processing_status(request, document_id):
    """Show processing status page."""
    document = get_object_or_404(Document, id=document_id)
    task_id = request.GET.get('task_id')
    return render(request, 'docprocessor/processing.html', {
        'document': document,
        'task_id': task_id
    })

def check_processing_status(request, document_id):
    """HTMX endpoint to check task status."""
    task_id = request.GET.get('task_id')
    if not task_id:
        return HttpResponse(status=204)
        
    from celery.result import AsyncResult
    result = AsyncResult(task_id)
    
    if result.state == 'SUCCESS':
        # Result is the ProcessedResult ID
        processed_result_id = result.result
        if processed_result_id:
            target_url = reverse('document_result', args=[processed_result_id])
            response = HttpResponse(status=200)
            response['HX-Redirect'] = target_url
            return response
    elif result.state == 'FAILURE':
        # Handle failure (maybe redirect to dashboard with error)
        target_url = reverse('dashboard')
        messages.error(request, f"Processing failed: {result.result}")
        response = HttpResponse(status=200)
        response['HX-Redirect'] = target_url
        return response
        
    return HttpResponse(status=204)

def document_result_view(request, result_id):
    """View a persisted processed result for a document."""
    pr = get_object_or_404(ProcessedResult, id=result_id)
    document = pr.document
    # Reconstruct a minimal extracted_text preview if the file still exists
    extracted_preview = ''
    try:
        if document.file_content:
            with temporary_file_from_content(document.file_content, suffix=f".{document.document_type}") as temp_file_path:
                extracted_preview = extract_text_from_file(temp_file_path, document.document_type)
        else:
            extracted_preview = ''
    except Exception:
        extracted_preview = ''
    return render(request, 'docprocessor/result.html', {
        'document': document,
        'result': pr,
        'extracted_text': extracted_preview,
    })

@login_required
def translate_processed_result(request, result_id):
    """Translate a persisted ProcessedResult using a free provider (LibreTranslate).
    Creates a new ProcessedResult with the translated text and redirects to it.
    """
    pr = get_object_or_404(ProcessedResult, id=result_id)
    document = pr.document
    # Permission check
    if document.user != request.user:
        messages.error(request, 'You do not have permission to translate this result.')
        return redirect('dashboard')

    if request.method != 'POST':
        return redirect('document_result', result_id=result_id)

    target_lang = (request.POST.get('target_language') or '').strip().lower()
    source_lang = (request.POST.get('source_language') or 'auto').strip().lower()
    if not target_lang:
        messages.error(request, 'Please select a target language.')
        return redirect('document_result', result_id=result_id)

    try:
        translated_text = translate_text_free(pr.result_text, target_language_code=target_lang, source_language_code=source_lang)
        # Treat provider error/unchanged markers as failures, not new results
        marker = translated_text.strip()
        if marker.startswith('[Translation error:') or marker.startswith('[Translation unchanged:'):
            raise Exception(marker.strip('[]'))
        new_pr = ProcessedResult.objects.create(document=document, result_text=translated_text)
        messages.success(request, f'Translated result created ({target_lang}).')
        return redirect('document_result', result_id=new_pr.id)
    except Exception as e:
        messages.error(request, f'Error translating: {e}')
        return redirect('document_result', result_id=result_id)

def process_multi_documents(request):
    """Process multiple documents together, combining text and honoring preset."""
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    ids_param = request.GET.get('ids', '')
    type_param = request.GET.get('type', '').lower()
    preset_param = request.GET.get('preset')
    words_param = request.GET.get('words')
    tokens_param = request.GET.get('tokens')
    length_param = request.GET.get('length')

    id_list = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
    if not id_list:
        messages.error(request, 'No documents selected for processing.')
        return redirect('dashboard')

    documents = Document.objects.filter(id__in=id_list)
    if request.user.is_authenticated:
        documents = documents.filter(user=request.user)
    documents = list(documents)
    if not documents:
        messages.error(request, 'Selected documents not found.')
        return redirect('dashboard')

    # Establish processing type on the first document for display/persistence
    anchor = documents[0]
    if type_param in ['summarize', 'generate', 'analyze']:
        anchor.processing_type = type_param
        anchor.save(update_fields=['processing_type'])

    # Build combined text with simple headers
    combined_parts = []
    for doc in documents:
        try:
            with temporary_file_from_content(doc.file_content, suffix=f".{doc.document_type}") as temp_path:
                txt = extract_text_from_file(temp_path, doc.document_type)
        except Exception:
            txt = ''
        if txt:
            combined_parts.append(f"## {doc.title}\n\n{txt}")
    combined_text = '\n\n'.join(combined_parts)

    # Compute token/word budgets
    max_tokens, target_words = calculate_max_tokens(
        words=words_param,
        tokens=tokens_param,
        length=length_param
    )

    # Process according to type
    if type_param == 'summarize':
        result_text = summarize_text(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)
    elif type_param == 'generate':
        result_text = generate_answers(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)
    else:
        result_text = analyze_text(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param, model=selected_model)

    # Note sources in the result
    titles = ', '.join([d.title for d in documents])
    result_text = f"Sources: {titles}\n\n" + (result_text or '')

    processed_result = ProcessedResult.objects.create(
        document=anchor,
        result_text=result_text
    )

    return render(request, 'docprocessor/result.html', {
        'document': anchor,
        'result': processed_result,
        'extracted_text': combined_text
    })

def _handle_processing_redirect(request, documents, processing_type):
    """Helper to handle common redirection logic for processing views."""
    preset_val = request.POST.get('preset')
    words_val = request.POST.get('words')
    
    if len(documents) == 1:
        document = documents[0]
        document.processing_type = processing_type
        document.save(update_fields=['processing_type'])
        document.document_type = get_document_type_from_filename(document.filename)
        
        redirect_url = reverse('process_document', kwargs={'document_id': document.id})
        params = []
        if words_val:
            params.append(f"words={words_val}")
        if preset_val:
            params.append(f"preset={preset_val}")
        if params:
            redirect_url = f"{redirect_url}?{'&'.join(params)}"
        return redirect(redirect_url)
    else:
        ids = ','.join(str(d.id) for d in documents)
        redirect_url = reverse('process_multi_documents')
        params = [f"ids={ids}", f"type={processing_type}"]
        if words_val:
            params.append(f"words={words_val}")
        if preset_val:
            params.append(f"preset={preset_val}")
        return redirect(f"{redirect_url}?{'&'.join(params)}")

def summarize_view(request):
    """View for summarizing documents"""
    external_result = None
    external_source = None
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    if request.method == 'POST':
        select_form = DocumentSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            return _handle_processing_redirect(request, [select_form.cleaned_data['document']], 'summarize')
    else:
        select_form = DocumentSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        
        max_tokens, target_words = calculate_max_tokens(
            words=request.GET.get('words'),
            tokens=request.GET.get('tokens'),
            length=request.GET.get('length')
        )

        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = summarize_text(transcript, target_words=target_words, max_tokens=max_tokens, model=selected_model)
                    external_source = 'YouTube Transcript'
                    # Persist the result for dashboard/result viewing
                    YouTubeProcessedResult.objects.create(
                        youtube_video=ytv,
                        processing_type='summarize',
                        result_text=external_result,
                        user=request.user if request.user.is_authenticated else None,
                    )
            except YouTubeVideo.DoesNotExist:
                pass
    
    return render(request, 'docprocessor/summarize.html', {
        'select_form': select_form,
        'external_result': external_result,
        'external_source': external_source,
        'youtube_id': request.GET.get('youtube_id'),
    })

def generate_view(request):
    """View for generating answers from documents"""
    external_result = None
    external_source = None
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    if request.method == 'POST':
        select_form = DocumentMultiSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            return _handle_processing_redirect(request, list(select_form.cleaned_data['documents']), 'generate')
    else:
        select_form = DocumentMultiSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        
        max_tokens, target_words = calculate_max_tokens(
            words=request.GET.get('words'),
            tokens=request.GET.get('tokens'),
            length=request.GET.get('length')
        )

        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = generate_answers(transcript, target_words=target_words, max_tokens=max_tokens, model=selected_model)
                    external_source = 'YouTube Transcript'
                    YouTubeProcessedResult.objects.create(
                        youtube_video=ytv,
                        processing_type='generate',
                        result_text=external_result,
                        user=request.user if request.user.is_authenticated else None,
                    )
            except YouTubeVideo.DoesNotExist:
                pass
    
    return render(request, 'docprocessor/generate.html', {
        'select_form': select_form,
        'external_result': external_result,
        'external_source': external_source,
        'youtube_id': request.GET.get('youtube_id'),
    })

def analyze_view(request):
    """View for analyzing documents"""
    external_result = None
    external_source = None
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    if request.method == 'POST':
        select_form = DocumentMultiSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            return _handle_processing_redirect(request, list(select_form.cleaned_data['documents']), 'analyze')
    else:
        select_form = DocumentMultiSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        
        max_tokens, target_words = calculate_max_tokens(
            words=request.GET.get('words'),
            tokens=request.GET.get('tokens'),
            length=request.GET.get('length')
        )

        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = analyze_text(transcript, target_words=target_words, max_tokens=max_tokens, model=selected_model)
                    external_source = 'YouTube Transcript'
                    YouTubeProcessedResult.objects.create(
                        youtube_video=ytv,
                        processing_type='analyze',
                        result_text=external_result,
                        user=request.user if request.user.is_authenticated else None,
                    )
            except YouTubeVideo.DoesNotExist:
                pass

    return render(request, 'docprocessor/analyze.html', {
        'select_form': select_form,
        'external_result': external_result,
        'external_source': external_source,
        'youtube_id': request.GET.get('youtube_id'),
    })


def youtube_result_view(request, result_id):
    """View a persisted result from a YouTube transcript processing"""
    yt_result = get_object_or_404(YouTubeProcessedResult, id=result_id)
    youtube_video = yt_result.youtube_video
    transcript_preview = (youtube_video.transcript or '')
    return render(request, 'docprocessor/youtube_result.html', {
        'youtube_video': youtube_video,
        'yt_result': yt_result,
        'transcript_preview': transcript_preview,
    })

def accessibility_view(request):
    """Accessibility: YouTube Watch & Chat loader (translation removed)"""
    selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
    model_form = ModelSelectionForm(initial_model=selected_model)
    youtube_form = YouTubeURLForm()
    
    youtube_result = None
    youtube_video_obj = None
    youtube_processed_type = None
    youtube_processed_result = None
    embed_url = None
    
    if request.method == 'POST':
        if 'model_submit' in request.POST:
            # Save selected model to session
            model_form = ModelSelectionForm(request.POST)
            if model_form.is_valid():
                request.session['selected_ai_model'] = model_form.cleaned_data['ai_model']
                selected_model = request.session['selected_ai_model']
                messages.success(request, f"Model updated to {selected_model} for all features (except Library).")
            else:
                messages.error(request, 'Invalid model selection.')
        
        elif 'youtube_submit' in request.POST:
            youtube_form = YouTubeURLForm(request.POST)
            if youtube_form.is_valid():
                youtube_url = youtube_form.cleaned_data['url']
                video_id = get_youtube_video_id(youtube_url)
                
                if video_id:
                    transcript = get_youtube_transcript(video_id)
                    
                    youtube_video = youtube_form.save(commit=False)
                    youtube_video.transcript = transcript
                    # Associate with user if authenticated
                    if request.user.is_authenticated:
                        youtube_video.user = request.user
                    youtube_video.save()
                    
                    youtube_result = transcript
                    youtube_video_obj = youtube_video
                    try:
                        if video_id:
                            embed_url = f"https://www.youtube.com/embed/{video_id}?rel=0"
                    except Exception:
                        embed_url = None
                else:
                    messages.error(request, 'Invalid YouTube URL')
        elif 'youtube_action' in request.POST:
            # Process previously saved transcript based on selected action
            action = request.POST.get('youtube_action')
            video_id = request.POST.get('video_id')
            if video_id and action:
                try:
                    youtube_video_obj = YouTubeVideo.objects.get(id=video_id)
                    transcript = youtube_video_obj.transcript or ''
                    if transcript:
                        # Ensure transcript preview still renders after action
                        youtube_result = transcript
                        if action == 'summarize':
                            youtube_processed_type = 'Summary'
                            youtube_processed_result = summarize_text(transcript, model=selected_model)
                        elif action == 'generate':
                            youtube_processed_type = 'Generated Answers'
                            youtube_processed_result = generate_answers(transcript, model=selected_model)
                        elif action == 'analyze':
                            youtube_processed_type = 'Analysis'
                            youtube_processed_result = analyze_text(transcript, model=selected_model)
                    else:
                        messages.error(request, 'No transcript found to process.')
                except YouTubeVideo.DoesNotExist:
                    messages.error(request, 'YouTube video not found.')
    # If we have an object but embed_url not set, compute from URL
    if youtube_video_obj and not embed_url:
        try:
            _vid = get_youtube_video_id(youtube_video_obj.url or '')
            if _vid:
                embed_url = f"https://www.youtube.com/embed/{_vid}?rel=0"
        except Exception:
            embed_url = None
    
    context = {
        'model_form': model_form,
        'selected_model': selected_model,
        'youtube_form': youtube_form,
        'youtube_result': youtube_result,
        'youtube_video': youtube_video_obj,
        'embed_url': embed_url,
        'youtube_processed_type': youtube_processed_type,
        'youtube_processed_result': youtube_processed_result,
    }
    
    return render(request, 'docprocessor/accessibility.html', context)

@login_required
def youtube_watch_chat(request):
    """Watch a YouTube video with a chat grounded in its transcript."""
    # Resolve video
    video_id = request.GET.get('video_id') or request.POST.get('video_id')
    youtube_video = None
    if video_id:
        youtube_video = YouTubeVideo.objects.filter(id=video_id, user=request.user).first()
    # Allow direct URL submit to create video
    if request.method == 'POST' and not youtube_video and request.POST.get('url'):
        url = request.POST.get('url')
        vid = get_youtube_video_id(url)
        if vid:
            transcript = ''
            try:
                transcript = get_youtube_transcript(vid)
            except Exception:
                transcript = ''
            youtube_video = YouTubeVideo.objects.create(url=url, title='', transcript=transcript, user=request.user)
        else:
            messages.error(request, 'Invalid YouTube URL')

    # Compute embed URL if possible
    embed_url = None
    if youtube_video:
        try:
            _vid = get_youtube_video_id(youtube_video.url or '')
            if _vid:
                embed_url = f"https://www.youtube.com/embed/{_vid}?rel=0"
        except Exception:
            embed_url = None

    if not youtube_video:
        # Initial landing: input form
        return render(request, 'docprocessor/youtube_chat.html', {
            'youtube_video': None,
            'embed_url': None,
            'sessions': ChatSession.objects.filter(user=request.user).order_by('-created_at')[:10],
            'active_session': None,
            'chat_messages': [],
        })

    # Ensure we have a session
    session_id = request.GET.get('session_id') or request.POST.get('session_id')
    active_session = None
    if session_id:
        active_session = ChatSession.objects.filter(id=session_id, user=request.user).first()
    if not active_session:
        title = youtube_video.title or 'YouTube Chat'
        active_session = ChatSession.objects.create(user=request.user, title=title)

    # Handle new message
    if request.method == 'POST' and request.POST.get('message'):
        user_message = request.POST.get('message','').strip()
        focus_mode = request.POST.get('focus_mode','0').strip()
        focus_only = focus_mode in ('1','true','on')
        system_prompt = request.POST.get('system_prompt','').strip() or 'You are a helpful AI assistant.'

        if user_message:
            ChatMessage.objects.create(session=active_session, role='user', content=user_message)

            # Build transcript context
            transcript = youtube_video.transcript or ''
            context_text = (transcript[:5000] if transcript else '')

            # Prepare history
            if focus_only:
                history = [{ 'role':'user', 'content': user_message }]
            else:
                history = [{ 'role': m.role, 'content': m.content } for m in active_session.messages.order_by('created_at')]
            
            if context_text:
                history.insert(0, { 'role':'system', 'content': f"Context from YouTube transcript:\n{context_text}" })
            elif focus_only:
                 history.insert(0, { 'role':'system', 'content': "IMPORTANT: No transcript available for this video." })

            # Strengthen persona prompt when in focus-only mode
            system_prompt_final = system_prompt
            if focus_only:
                system_prompt_final = (
                    system_prompt +
                    "\n\nSTRICT FOCUS MODE ENABLED:\n"
                    "- You must answer ONLY using the provided YouTube transcript context.\n"
                    "- If the answer is not in the transcript, say 'I am sorry, but that information is not present in the video transcript.'\n"
                    "- DO NOT use any external knowledge.\n"
                )

            latex_policy = (
                "\n\nMath Rendering Policy: When you include mathematical expressions, format them using LaTeX. "
                "Use $$...$$ for display equations and \\(...\\) or $...$ for inline math. "
                "Prefer proper superscripts with ^ and keep delimiters for client rendering."
            )
            system_prompt_final = system_prompt_final + latex_policy
            selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
            assistant_reply = chat_with_model(history, system_prompt=system_prompt_final, model=selected_model, max_tokens=800)
            ChatMessage.objects.create(session=active_session, role='assistant', content=assistant_reply)

            # If this is an AJAX request, return JSON to avoid full page refresh
            if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
                msgs = [{ 'role': m.role, 'content': m.content } for m in active_session.messages.order_by('created_at')]
                return JsonResponse({
                    'session_id': active_session.id,
                    'messages': msgs,
                    'assistant_reply': assistant_reply or '',
                })

    chat_messages = active_session.messages.order_by('created_at')
    return render(request, 'docprocessor/youtube_chat.html', {
        'youtube_video': youtube_video,
        'embed_url': embed_url,
        'sessions': ChatSession.objects.filter(user=request.user).order_by('-created_at')[:10],
        'active_session': active_session,
        'chat_messages': chat_messages,
    })
def _draw_header_footer(canvas, doc, branding="Smartly", footer_text=""):
    canvas.saveState()
    width, height = letter
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawString(doc.leftMargin, height - 0.5 * inch, branding)
    canvas.setFont('Helvetica', 9)
    canvas.drawRightString(width - doc.rightMargin, 0.5 * inch, f"Page {canvas.getPageNumber()}")
    if footer_text:
        canvas.drawString(doc.leftMargin, 0.5 * inch, footer_text)
    canvas.restoreState()

def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CoverBrand', fontSize=18, leading=22, alignment=TA_CENTER, textColor=colors.HexColor('#2c3e50')))
    styles.add(ParagraphStyle(name='CoverTitle', fontSize=24, leading=28, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Meta', fontSize=10, leading=13, textColor=colors.grey))
    styles.add(ParagraphStyle(name='H1', parent=styles['Heading1'], fontSize=16))
    styles.add(ParagraphStyle(name='H2', parent=styles['Heading2'], fontSize=14))
    styles.add(ParagraphStyle(name='H3', parent=styles['Heading3'], fontSize=12))
    # Use a unique list item style name to avoid collision with ReportLab's default 'Bullet'
    styles.add(ParagraphStyle(name='BulletText', parent=styles['BodyText'], leftIndent=12))
    # Use a unique code style name to avoid collision with default 'Code'
    styles.add(ParagraphStyle(name='CodeBlock', fontName='Courier', fontSize=9, leading=12, backColor=colors.whitesmoke))
    return styles

def _markdown_to_story(text, styles):
    story = []
    lines = text.splitlines()
    in_code = False
    code_lines = []
    list_items = []
    in_list = False
    for line in lines:
        stripped = line.rstrip()
        # Code fences
        if stripped.startswith('```'):
            if in_code:
                story.append(Preformatted('\n'.join(code_lines), styles['CodeBlock']))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        # Headings
        m = re.match(r'^(#{1,3})\s+(.*)$', stripped)
        if m:
            level = len(m.group(1))
            content = m.group(2)
            style_name = 'H1' if level == 1 else 'H2' if level == 2 else 'H3'
            story.append(Paragraph(content, styles[style_name]))
            continue
        # Lists (unordered and ordered)
        m_ul = re.match(r'^\s*[-*]\s+(.*)$', stripped)
        m_ol = re.match(r'^\s*\d+\.\s+(.*)$', stripped)
        if m_ul or m_ol:
            if not in_list:
                list_items = []
                in_list = True
            item_text = (m_ul.group(1) if m_ul else m_ol.group(1))
            list_items.append(ListItem(Paragraph(item_text, styles['BulletText'])))
            continue
        else:
            if in_list:
                story.append(ListFlowable(list_items, bulletType='bullet'))
                list_items = []
                in_list = False
        # Blank line -> spacer
        if stripped.strip() == '':
            story.append(Spacer(1, 0.15 * inch))
        else:
            # Basic HTML line breaks
            paragraph_text = stripped.replace('<br/>', '<br />').replace('<br>', '<br />')
            story.append(Paragraph(paragraph_text, styles['BodyText']))
    # Flush any remaining list
    if in_list:
        story.append(ListFlowable(list_items, bulletType='bullet'))
    # Flush any remaining code block (if not closed correctly)
    if in_code and code_lines:
        story.append(Preformatted('\n'.join(code_lines), styles['CodeBlock']))
    return story
def download_result_pdf(request, result_id):
    """Download a processed document result as PDF"""
    pr = get_object_or_404(ProcessedResult, id=result_id)
    document = pr.document
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = _build_styles()
    story = []
    # Cover page
    story.append(Paragraph("Smartly", styles['CoverBrand']))
    title = f"{document.title}"
    story.append(Paragraph(title, styles['CoverTitle']))
    story.append(Spacer(1, 0.2 * inch))
    subtitle = f"{document.get_processing_type_display()}"
    story.append(Paragraph(subtitle, styles['H2']))
    meta = f"Document Type: {document.get_document_type_display()}<br/>"
    meta += f"Uploaded: {document.uploaded_at:%B %d, %Y %H:%M}<br/>"
    meta += f"Processed: {pr.processed_at:%B %d, %Y %H:%M}"
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(meta, styles['Meta']))
    story.append(PageBreak())
    # Body
    story.append(Paragraph("Result", styles['H1']))
    story.append(Spacer(1, 0.1 * inch))
    story.extend(_markdown_to_story(pr.result_text, styles))
    doc.build(story,
              onFirstPage=lambda c, d: _draw_header_footer(c, d, branding="Smartly", footer_text=document.title),
              onLaterPages=lambda c, d: _draw_header_footer(c, d, branding="Smartly", footer_text=document.title))
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type='application/pdf')
    filename = f"{document.title.replace(' ', '_')}_{document.processing_type}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

def download_youtube_result_pdf(request, result_id):
    """Download a YouTube processed result as PDF"""
    yt_pr = get_object_or_404(YouTubeProcessedResult, id=result_id)
    youtube_video = yt_pr.youtube_video
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = _build_styles()
    story = []
    # Cover page
    story.append(Paragraph("Smartly", styles['CoverBrand']))
    title = youtube_video.title or youtube_video.url
    story.append(Paragraph(title, styles['CoverTitle']))
    story.append(Spacer(1, 0.2 * inch))
    subtitle = yt_pr.get_processing_type_display()
    story.append(Paragraph(subtitle, styles['H2']))
    meta = f"Video: {youtube_video.url}<br/>Processed: {yt_pr.processed_at:%B %d, %Y %H:%M}"
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(meta, styles['Meta']))
    story.append(PageBreak())
    # Body
    story.append(Paragraph("Result", styles['H1']))
    story.append(Spacer(1, 0.1 * inch))
    story.extend(_markdown_to_story(yt_pr.result_text, styles))
    doc.build(story,
              onFirstPage=lambda c, d: _draw_header_footer(c, d, branding="Smartly", footer_text=title),
              onLaterPages=lambda c, d: _draw_header_footer(c, d, branding="Smartly", footer_text=title))
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type='application/pdf')
    base = (youtube_video.title or 'youtube').replace(' ', '_')
    filename = f"{base}_{yt_pr.processing_type}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
def chat_view(request):
    """Interactive chat interface powered by OpenAI, with selectable document context."""
    # Load user's documents for selection
    documents = Document.objects.filter(user=request.user).order_by('-uploaded_at')

    # Determine active session
    session_id = request.GET.get('session_id') or request.POST.get('session_id')
    active_session = None
    if session_id:
        active_session = ChatSession.objects.filter(id=session_id, user=request.user).first()

    # Handle new message submission
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        user_message = request.POST.get('message', '').strip()
        system_prompt = request.POST.get('system_prompt', '').strip() or "You are a helpful AI assistant."
        focus_mode = request.POST.get('focus_mode', '0').strip()
        focus_only = focus_mode in ('1', 'true', 'on')
        selected_ids = request.POST.getlist('documents')
        quick_action = request.POST.get('quick_action', '').strip()
        silent_quick = bool(quick_action)

        if not active_session:
            active_session = ChatSession.objects.create(user=request.user, title=request.POST.get('title', '').strip() or '')
        
        # Update selected documents only when the context form posts (AJAX) or explicit IDs provided.
        # Preserve previous selection when sending a chat message without document checkboxes.
        is_context_update = is_ajax and not user_message
        if is_context_update:
            # Context dropdown submit: reflect current checkbox state
            if selected_ids:
                active_session.documents.set(Document.objects.filter(id__in=selected_ids, user=request.user))
            else:
                active_session.documents.clear()
        elif selected_ids:
            # Explicit IDs provided in a non-context-only update (e.g. standard POST)
            active_session.documents.set(Document.objects.filter(id__in=selected_ids, user=request.user))
        # else: preserve existing session.documents

        # Save user message
        if user_message:
            if not silent_quick:
                ChatMessage.objects.create(session=active_session, role='user', content=user_message)

            # Extract text from all selected documents in parallel, using Redis cache.
            session_docs = list(active_session.documents.all())
            context_snippets = []
            total_chars = 0
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(get_extracted_text_for_doc, doc): doc for doc in session_docs}
                for future in as_completed(futures):
                    doc = futures[future]
                    try:
                        text = future.result() or ''
                    except Exception:
                        text = ''
                    if text and total_chars < 25000:
                        context_snippets.append(f"- {doc.title}:\n{text}")
                        total_chars += len(text)
            context_text = "\n\n".join(context_snippets)

            # Prepare chat history messages
            if focus_only:
                # Strict focus: only current message and provided document context
                history = [
                    {"role": "user", "content": user_message}
                ]
            else:
                history = [
                    {"role": msg.role, "content": msg.content}
                    for msg in active_session.messages.order_by('created_at')
                ]
            
            if context_text:
                history.insert(0, {"role": "system", "content": f"Context from selected documents:\n{context_text}"})
            elif focus_only:
                history.insert(0, {"role": "system", "content": "IMPORTANT: No documents are currently selected. You must inform the user that they need to select documents using the '+' icon (context menu) before you can provide answers based on document content."})

            # Strengthen persona prompt when in focus-only mode
            system_prompt_final = system_prompt
            if focus_only:
                system_prompt_final = (
                    system_prompt +
                    "\n\nSTRICT FOCUS MODE ENABLED:\n"
                    "- You must answer ONLY using the provided document context.\n"
                    "- If the answer is not in the context, say 'I am sorry, but that information is not present in the selected documents.' or 'Out of scope'.\n"
                    "- DO NOT use any external knowledge or general facts outside the context.\n"
                    "- If no context is provided, explain that documents must be selected first."
                )

            # Always enforce LaTeX formatting for math in replies
            latex_policy = (
                "\n\nMath Rendering Policy: When you include mathematical expressions, format them using LaTeX. "
                "Use $$...$$ for display equations and \\(...\\) or $...$ for inline math. "
                "Prefer proper superscripts with ^ (e.g., c^2) and never output plain text like c2 or a2. "
                "Keep the delimiters in the final text so the client can render with KaTeX."
            )
            system_prompt_final = system_prompt_final + latex_policy

            # Route quick action 'recommend_videos' to web search, otherwise use chat_with_openai
            if quick_action == 'recommend_videos':
                try:
                    # Derive region bias from Django LANGUAGE_CODE
                    lc = (getattr(settings, 'LANGUAGE_CODE', 'en-us') or 'en-us').lower()
                    region = None
                    if 'in' in lc:
                        region = 'in-en'
                    elif 'gb' in lc or 'uk' in lc:
                        region = 'uk-en'
                    elif 'us' in lc:
                        region = 'us-en'
                    else:
                        region = 'wt-wt'
                    assistant_reply = recommend_youtube_videos_web(user_message, max_results=5, region=region)
                except Exception as e:
                    assistant_reply = f"Sorry, I couldn’t fetch live recommendations right now. {str(e)}"
            else:
                # Use selected model for chat; provider-agnostic routing
                selected_model = request.session.get('selected_ai_model', 'gpt-3.5-turbo')
                assistant_reply = chat_with_model(history, system_prompt=system_prompt_final, model=selected_model, max_tokens=4000)

            # Save assistant message
            ChatMessage.objects.create(session=active_session, role='assistant', content=assistant_reply)

            if is_ajax:
                return JsonResponse({
                    'session_id': active_session.id,
                    'assistant_reply': assistant_reply,
                })

        # Only context change (no message)
        if is_ajax and not user_message:
            return JsonResponse({
                'session_id': active_session.id,
                'context_updated': True,
                'selected_doc_ids': list(active_session.documents.values_list('id', flat=True))
            })

        return redirect(f"{reverse('chat')}?session_id={active_session.id}")

    # Prepare page context
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    chat_messages = active_session.messages.order_by('created_at') if active_session else []
    selected_doc_ids = set(active_session.documents.values_list('id', flat=True)) if active_session else set()
    return render(request, 'docprocessor/chat.html', {
        'documents': documents,
        'sessions': sessions,
        'active_session': active_session,
        'chat_messages': chat_messages,
        'selected_doc_ids': selected_doc_ids,
    })


@login_required
def delete_chat_session(request, session_id):
    """Delete a chat session and its messages for the current user."""
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    if request.method == 'POST':
        session.delete()
        return redirect('chat')
    # Only allow POST for deletion; redirect back if accessed via GET
    return redirect(f"{reverse('chat')}?session_id={session.id}")


@login_required
def library_view(request):
    """Display user's documents organized by topics on the left and a project recommendations panel on the right."""
    # Fetch user's documents
    documents = Document.objects.filter(user=request.user).order_by('-uploaded_at')

    topics = []
    if documents.exists():
        # Cache key invalidates automatically when the user adds/removes documents
        latest_ts = documents.order_by('-uploaded_at').values_list('uploaded_at', flat=True).first()
        topics_cache_key = (
            f"lib_topics_{request.user.id}_{documents.count()}"
            f"_{latest_ts.timestamp() if latest_ts else 0}"
        )
        topics = cache.get(topics_cache_key)

        if topics is None:
            # Build compact payload — use cached text extraction, fix for binary-backed docs
            payload = []
            for d in documents:
                snippet = get_extracted_text_for_doc(d)[:1200]
                payload.append({
                    'id': d.id,
                    'title': d.title,
                    'type': d.document_type,
                    'snippet': snippet,
                })

            system_prompt = (
                "You categorize documents into clear, high-level topics. "
                "Return strictly compact JSON using the provided document ids."
            )
            user_instruction = (
                "Group the following documents into 4-8 topics based on semantic similarity. "
                "Respond ONLY with JSON shaped as {\"topics\":[{\"name\":\"...\",\"document_ids\":[<ids>]}, ...]}. "
                "Use concise topic names."
            )
            messages = [
                {"role": "user", "content": user_instruction + "\n\n" + json.dumps(payload)}
            ]

            try:
                raw = chat_with_openai(messages, system_prompt=system_prompt, max_tokens=700)
                parsed_topics = []
                try:
                    start = raw.find('{')
                    end = raw.rfind('}')
                    if start != -1 and end != -1:
                        block = raw[start:end+1]
                        data = json.loads(block)
                        parsed_topics = data.get('topics') if isinstance(data, dict) else data
                except Exception:
                    parsed_topics = []

                if not parsed_topics or not isinstance(parsed_topics, list):
                    groups = {}
                    for d in documents:
                        key = d.document_type.upper()
                        groups.setdefault(key, []).append(d)
                    topics = [{'name': k, 'documents': v} for k, v in groups.items()]
                else:
                    id_map = {d.id: d for d in documents}
                    topics = []
                    for t in parsed_topics:
                        name = t.get('name') or 'Topic'
                        ids = t.get('document_ids') or []
                        docs_group = [id_map[i] for i in ids if i in id_map]
                        if docs_group:
                            topics.append({'name': name, 'documents': docs_group})
                    assigned = set(i for t in parsed_topics for i in (t.get('document_ids') or []))
                    leftover = [d for d in documents if d.id not in assigned]
                    if leftover:
                        topics.append({'name': 'Other', 'documents': leftover})
            except Exception:
                groups = {}
                for d in documents:
                    key = d.document_type.upper()
                    groups.setdefault(key, []).append(d)
                topics = [{'name': k, 'documents': v} for k, v in groups.items()]

            cache.set(topics_cache_key, topics, timeout=86400)

    # Analytics Data
    total_docs = documents.count()
    processed_docs = ProcessedResult.objects.filter(document__user=request.user).values('document').distinct().count()
    
    topic_data = []
    for t in topics:
        topic_data.append({
            'name': t['name'],
            'count': len(t['documents'])
        })
    
    # Simple "Learning Time" estimate: 5 mins per processed doc + 2 mins per chat message
    chat_msgs_count = ChatMessage.objects.filter(session__user=request.user, role='user').count()
    estimated_minutes = (processed_docs * 5) + (chat_msgs_count * 2)
    learning_hours = round(estimated_minutes / 60, 1)
    
    processed_percentage = 0
    if total_docs > 0:
        processed_percentage = round((processed_docs / total_docs) * 100)

    return render(request, 'docprocessor/library.html', {
        'topics': topics,
        'documents_count': total_docs,
        'processed_count': processed_docs,
        'processed_percentage': processed_percentage,
        'topic_labels': json.dumps([t['name'] for t in topic_data]),
        'topic_counts': json.dumps([t['count'] for t in topic_data]),
        'learning_hours': learning_hours,
        'chat_activity': chat_msgs_count,
    })


@login_required
def library_recommend_projects(request):
    """Return OpenAI-driven project recommendations based on user's documents as JSON."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    documents = Document.objects.filter(user=request.user)
    if not documents.exists():
        return JsonResponse({'projects': []})

    payload = []
    for d in documents:
        snippet = get_extracted_text_for_doc(d)[:1800]
        payload.append({
            'id': d.id,
            'title': d.title,
            'type': d.document_type,
            'snippet': snippet,
        })

    system_prompt = (
        "You recommend practical, scoped projects aligned to document topics and skills. "
        "Always return strict JSON arrays only."
    )
    user_instruction = (
        "Based on these documents, recommend 4-6 projects. "
        "Return ONLY a JSON array where each item is {\"title\":\"...\",\"description\":\"2-3 sentences\",\"related_document_ids\":[ids],\"skills\":[\"...\"]}. "
        "Use provided ids and keep descriptions concise."
    )
    messages = [
        {"role": "user", "content": user_instruction + "\n\n" + json.dumps({'documents': payload})}
    ]

    raw = chat_with_openai(messages, system_prompt=system_prompt, max_tokens=800)

    projects = []
    try:
        # Extract JSON array from response
        start = raw.find('[')
        end = raw.rfind(']')
        if start != -1 and end != -1:
            arr_block = raw[start:end+1]
            data = json.loads(arr_block)
            if isinstance(data, list):
                projects = data
    except Exception:
        projects = []

    if not projects:
        # Fallback: generate simple projects from titles
        projects = [
            {
                'title': f"Study project: {d.title}",
                'description': 'Create a concise study guide and flashcards covering key concepts.',
                'related_document_ids': [d.id],
                'skills': ['Reading', 'Summarization', 'Note-taking']
            }
            for d in documents[:5]
        ]

    return JsonResponse({'projects': projects})
