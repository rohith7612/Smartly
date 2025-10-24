from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, ListFlowable, ListItem, Preformatted
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
import re
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login
from .models import Document, ProcessedResult, YouTubeVideo, YouTubeProcessedResult, ChatSession, ChatMessage
from .forms import DocumentUploadForm, DocumentSelectForm, DocumentMultiSelectForm, YouTubeURLForm, TranslationForm
from .utils import (
    extract_text_from_file, summarize_text, generate_answers, 
    analyze_text, translate_text, get_youtube_video_id, 
    get_youtube_transcript, chat_with_openai, translate_text_free,
    recommend_youtube_videos_web
)
import os
from django.conf import settings

def home(request):
    """Home page view"""
    return render(request, 'docprocessor/home.html')

from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db.models import Q

def dashboard(request):
    """Dashboard view showing user's documents and results with per-section pagination"""
    if request.user.is_authenticated:
        documents_qs = Document.objects.filter(user=request.user).order_by('-uploaded_at')
        actions_qs = ProcessedResult.objects.filter(document__user=request.user).order_by('-processed_at')
        youtube_videos_qs = YouTubeVideo.objects.filter(user=request.user).order_by('-processed_at')
        youtube_results_qs = YouTubeProcessedResult.objects.filter(user=request.user).order_by('-processed_at')
    else:
        documents_qs = Document.objects.all().order_by('-uploaded_at')
        actions_qs = ProcessedResult.objects.all().order_by('-processed_at')
        youtube_videos_qs = YouTubeVideo.objects.all().order_by('-processed_at')
        youtube_results_qs = YouTubeProcessedResult.objects.all().order_by('-processed_at')

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
            # Remove file from storage first
            if getattr(document, 'file', None):
                try:
                    document.file.delete(save=False)
                except Exception:
                    pass
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
            # Default processing type during upload (user selects actual action later)
            document.processing_type = 'summarize'
            
            # Determine document type based on file extension
            file_extension = os.path.splitext(document.file.name)[1].lower()
            if file_extension in ['.pdf']:
                document.document_type = 'pdf'
            elif file_extension in ['.docx', '.doc']:
                document.document_type = 'docx'
            elif file_extension in ['.txt']:
                document.document_type = 'txt'
            elif file_extension in ['.jpg', '.jpeg', '.png']:
                document.document_type = 'image'
            
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

def process_document(request, document_id):
    """Process the uploaded document"""
    document = get_object_or_404(Document, id=document_id)
    
    # Extract text from the document
    file_path = document.file.path
    extracted_text = extract_text_from_file(file_path, document.document_type)
    
    # Reply length via words (slider) and optional tokens fallback
    words_param = request.GET.get('words')
    tokens_param = request.GET.get('tokens')
    length_param = request.GET.get('length')
    try:
        target_words = int(words_param) if words_param else None
    except (TypeError, ValueError):
        target_words = None
    # Generous token budget to avoid truncation; approx 3 tokens per word
    try:
        max_tokens = int(tokens_param) if tokens_param else None
    except (TypeError, ValueError):
        max_tokens = None
    if not max_tokens and target_words:
        max_tokens = min(3800, max(256, int(target_words) * 3))
    if not max_tokens and length_param:
        length_map = {'short': 200, 'medium': 500, 'long': 1000}
        max_tokens = length_map.get(length_param.lower())
    if not max_tokens:
        max_tokens = 800

    # Optional preset param to shape output format/type
    preset_param = request.GET.get('preset')

    # Process the text based on the selected processing type
    if document.processing_type == 'summarize':
        result_text = summarize_text(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)
    elif document.processing_type == 'generate':
        result_text = generate_answers(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)
    elif document.processing_type == 'analyze':
        result_text = analyze_text(extracted_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)
    elif document.processing_type == 'translate':
        # Default to English translation
        result_text = translate_text(extracted_text, 'English', max_tokens=max_tokens)
    else:
        result_text = "Unknown processing type"
    
    # Save the processed result
    processed_result = ProcessedResult.objects.create(
        document=document,
        result_text=result_text
    )
    
    return render(request, 'docprocessor/result.html', {
        'document': document,
        'result': processed_result,
        'extracted_text': extracted_text
    })

def document_result_view(request, result_id):
    """View a persisted processed result for a document."""
    pr = get_object_or_404(ProcessedResult, id=result_id)
    document = pr.document
    # Reconstruct a minimal extracted_text preview if the file still exists
    extracted_preview = ''
    try:
        if document.file and document.file.path:
            extracted_preview = extract_text_from_file(document.file.path, document.document_type)[:1000]
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
            txt = extract_text_from_file(doc.file.path, doc.document_type)
        except Exception:
            txt = ''
        if txt:
            combined_parts.append(f"## {doc.title}\n\n{txt}")
    combined_text = '\n\n'.join(combined_parts)

    # Compute token/word budgets
    try:
        target_words = int(words_param) if words_param else None
    except (TypeError, ValueError):
        target_words = None
    try:
        max_tokens = int(tokens_param) if tokens_param else None
    except (TypeError, ValueError):
        max_tokens = None
    if not max_tokens and target_words:
        max_tokens = min(3800, max(256, int(target_words) * 3))
    if not max_tokens and length_param:
        length_map = {'short': 200, 'medium': 500, 'long': 1000}
        max_tokens = length_map.get(length_param.lower())
    if not max_tokens:
        max_tokens = 800

    # Process according to type
    if type_param == 'summarize':
        result_text = summarize_text(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)
    elif type_param == 'generate':
        result_text = generate_answers(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)
    else:
        result_text = analyze_text(combined_text, target_words=target_words, max_tokens=max_tokens, preset=preset_param)

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

def summarize_view(request):
    """View for summarizing documents"""
    external_result = None
    external_source = None
    if request.method == 'POST':
        select_form = DocumentSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            document = select_form.cleaned_data['document']
            # Update processing type for this run
            document.processing_type = 'summarize'
            document.save(update_fields=['processing_type'])
            
            # Determine document type based on file extension
            file_extension = os.path.splitext(document.file.name)[1].lower()
            if file_extension in ['.pdf']:
                document.document_type = 'pdf'
            elif file_extension in ['.docx', '.doc']:
                document.document_type = 'docx'
            elif file_extension in ['.txt']:
                document.document_type = 'txt'
            elif file_extension in ['.jpg', '.jpeg', '.png']:
                document.document_type = 'image'
            
            # Preserve words from slider and selected preset to processing step
            redirect_url = reverse('process_document', kwargs={'document_id': document.id})
            words_val = request.POST.get('words')
            preset_val = request.POST.get('preset')
            params = []
            if words_val:
                params.append(f"words={words_val}")
            if preset_val:
                params.append(f"preset={preset_val}")
            if params:
                redirect_url = f"{redirect_url}?{'&'.join(params)}"
            return redirect(redirect_url)
    else:
        select_form = DocumentSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        words_param = request.GET.get('words')
        tokens_param = request.GET.get('tokens')
        length_param = request.GET.get('length')
        try:
            target_words = int(words_param) if words_param else None
        except (TypeError, ValueError):
            target_words = None
        try:
            max_tokens = int(tokens_param) if tokens_param else None
        except (TypeError, ValueError):
            max_tokens = None
        if not max_tokens and target_words:
            max_tokens = min(3800, max(256, int(target_words) * 3))
        if not max_tokens and length_param:
            length_map = {'short': 200, 'medium': 500, 'long': 1000}
            max_tokens = length_map.get(length_param.lower())
        if not max_tokens:
            max_tokens = 800
        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = summarize_text(transcript, target_words=target_words, max_tokens=max_tokens)
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
    if request.method == 'POST':
        select_form = DocumentMultiSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            documents = list(select_form.cleaned_data['documents'])
            preset_val = request.POST.get('preset') or 'exam_answers'
            words_val = request.POST.get('words')
            if len(documents) <= 1:
                document = documents[0]
                document.processing_type = 'generate'
                document.save(update_fields=['processing_type'])
                # Determine document type based on file extension
                file_extension = os.path.splitext(document.file.name)[1].lower()
                if file_extension in ['.pdf']:
                    document.document_type = 'pdf'
                elif file_extension in ['.docx', '.doc']:
                    document.document_type = 'docx'
                elif file_extension in ['.txt']:
                    document.document_type = 'txt'
                elif file_extension in ['.jpg', '.jpeg', '.png']:
                    document.document_type = 'image'
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
                params = [f"ids={ids}", "type=generate"]
                if words_val:
                    params.append(f"words={words_val}")
                if preset_val:
                    params.append(f"preset={preset_val}")
                return redirect(f"{redirect_url}?{'&'.join(params)}")
    else:
        select_form = DocumentMultiSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        words_param = request.GET.get('words')
        tokens_param = request.GET.get('tokens')
        length_param = request.GET.get('length')
        try:
            target_words = int(words_param) if words_param else None
        except (TypeError, ValueError):
            target_words = None
        try:
            max_tokens = int(tokens_param) if tokens_param else None
        except (TypeError, ValueError):
            max_tokens = None
        if not max_tokens and target_words:
            max_tokens = min(3800, max(256, int(target_words) * 3))
        if not max_tokens and length_param:
            length_map = {'short': 200, 'medium': 500, 'long': 1000}
            max_tokens = length_map.get(length_param.lower())
        if not max_tokens:
            max_tokens = 800
        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = generate_answers(transcript, target_words=target_words, max_tokens=max_tokens)
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
    if request.method == 'POST':
        select_form = DocumentMultiSelectForm(request.POST, user=request.user)
        if select_form.is_valid():
            documents = list(select_form.cleaned_data['documents'])
            preset_val = request.POST.get('preset') or 'question_patterns'
            words_val = request.POST.get('words')
            if len(documents) <= 1:
                document = documents[0]
                document.processing_type = 'analyze'
                document.save(update_fields=['processing_type'])
                # Determine document type based on file extension
                file_extension = os.path.splitext(document.file.name)[1].lower()
                if file_extension in ['.pdf']:
                    document.document_type = 'pdf'
                elif file_extension in ['.docx', '.doc']:
                    document.document_type = 'docx'
                elif file_extension in ['.txt']:
                    document.document_type = 'txt'
                elif file_extension in ['.jpg', '.jpeg', '.png']:
                    document.document_type = 'image'
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
                params = [f"ids={ids}", "type=analyze"]
                if words_val:
                    params.append(f"words={words_val}")
                if preset_val:
                    params.append(f"preset={preset_val}")
                return redirect(f"{redirect_url}?{'&'.join(params)}")
    else:
        select_form = DocumentMultiSelectForm(user=request.user)
        youtube_id = request.GET.get('youtube_id')
        words_param = request.GET.get('words')
        tokens_param = request.GET.get('tokens')
        length_param = request.GET.get('length')
        try:
            target_words = int(words_param) if words_param else None
        except (TypeError, ValueError):
            target_words = None
        try:
            max_tokens = int(tokens_param) if tokens_param else None
        except (TypeError, ValueError):
            max_tokens = None
        if not max_tokens and target_words:
            max_tokens = min(3800, max(256, int(target_words) * 3))
        if not max_tokens and length_param:
            length_map = {'short': 200, 'medium': 500, 'long': 1000}
            max_tokens = length_map.get(length_param.lower())
        if not max_tokens:
            max_tokens = 800
        if youtube_id:
            try:
                ytv = YouTubeVideo.objects.get(id=youtube_id)
                transcript = ytv.transcript or ''
                if transcript:
                    external_result = analyze_text(transcript, target_words=target_words, max_tokens=max_tokens)
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
    """View for accessibility features (translation and YouTube)"""
    translation_form = TranslationForm()
    youtube_form = YouTubeURLForm()
    
    translation_result = None
    youtube_result = None
    youtube_video_obj = None
    youtube_processed_type = None
    youtube_processed_result = None
    
    if request.method == 'POST':
        if 'translate_submit' in request.POST:
            translation_form = TranslationForm(request.POST)
            if translation_form.is_valid():
                text = translation_form.cleaned_data['text']
                source_language = translation_form.cleaned_data['source_language']
                target_language = translation_form.cleaned_data['target_language']
                
                translation_result = translate_text(text, target_language, source_language)
        
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
                            youtube_processed_result = summarize_text(transcript)
                        elif action == 'generate':
                            youtube_processed_type = 'Generated Answers'
                            youtube_processed_result = generate_answers(transcript)
                        elif action == 'analyze':
                            youtube_processed_type = 'Analysis'
                            youtube_processed_result = analyze_text(transcript)
                    else:
                        messages.error(request, 'No transcript found to process.')
                except YouTubeVideo.DoesNotExist:
                    messages.error(request, 'YouTube video not found.')
    
    context = {
        'translation_form': translation_form,
        'youtube_form': youtube_form,
        'translation_result': translation_result,
        'youtube_result': youtube_result,
        'youtube_video': youtube_video_obj,
        'youtube_processed_type': youtube_processed_type,
        'youtube_processed_result': youtube_processed_result,
    }
    
    return render(request, 'docprocessor/accessibility.html', context)
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
        # Update selected documents on session
        if selected_ids:
            active_session.documents.set(Document.objects.filter(id__in=selected_ids, user=request.user))
        else:
            active_session.documents.clear()

        # Save user message
        if user_message:
            if not silent_quick:
                ChatMessage.objects.create(session=active_session, role='user', content=user_message)

            # Build document context (trimmed)
            context_snippets = []
            total_chars = 0
            for doc in active_session.documents.all():
                try:
                    text = extract_text_from_file(doc.file.path, doc.document_type)
                except Exception:
                    text = ''
                snippet = (text or '')[:2000]
                if snippet:
                    context_snippets.append(f"- {doc.title}:\n{snippet}")
                    total_chars += len(snippet)
                if total_chars >= 5000:
                    break
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

            # Strengthen persona prompt when in focus-only mode
            system_prompt_final = system_prompt
            if focus_only:
                system_prompt_final = (
                    system_prompt +
                    "\n\nFocus Mode: Answer strictly using ONLY the provided document context. "
                    "If information is not present, say 'Out of scope' and request clarifying details. "
                    "Do not use external knowledge."
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
                assistant_reply = chat_with_openai(history, system_prompt=system_prompt_final, max_tokens=800)

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
