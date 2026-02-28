import os
import logging
import re
try:
    import pdfplumber
except ImportError:
    pdfplumber = None
import docx
import pytesseract
from PIL import Image, ImageOps, ImageFilter
from openai import OpenAI
from django.conf import settings
try:
    # Optional providers; import lazily so app works without them
    from anthropic import Anthropic
except Exception:
    Anthropic = None
try:
    from google import genai
except Exception:
    genai = None
try:
    from huggingface_hub import InferenceClient
except Exception:
    InferenceClient = None
from youtube_transcript_api import YouTubeTranscriptApi
import re
import json
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse, parse_qs, quote, unquote
from contextlib import contextmanager
import tempfile
import time
from router.models import ModelProfile, ModelRuntimeStats
from router.task_features import extract_task_features
from router.minimax_router import select_model as get_best_model

@contextmanager
def temporary_file_from_content(content, suffix=None):
    """Context manager for creating a temporary file from content and cleaning up after."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(content)
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)

def calculate_max_tokens(words=None, tokens=None, length=None):
    """Calculate max_tokens based on words, tokens, or length preset."""
    try:
        target_words = int(words) if words else None
    except (TypeError, ValueError):
        target_words = None
    try:
        max_tokens = int(tokens) if tokens else None
    except (TypeError, ValueError):
        max_tokens = None
    if not max_tokens and target_words:
        max_tokens = min(3800, max(256, int(target_words) * 3))
    if not max_tokens and length:
        length_map = {'short': 200, 'medium': 500, 'long': 1000}
        max_tokens = length_map.get(length.lower())
    if not max_tokens:
        max_tokens = 800
    return max_tokens, target_words

def get_document_type_from_filename(filename):
    """Determine document type based on file extension."""
    if not filename:
        return 'txt'
    file_extension = os.path.splitext(filename)[1].lower()
    if file_extension in ['.pdf']:
        return 'pdf'
    elif file_extension in ['.docx', '.doc']:
        return 'docx'
    elif file_extension in ['.txt']:
        return 'txt'
    elif file_extension in ['.jpg', '.jpeg', '.png']:
        return 'image'
    return 'txt'

# Configure OpenAI API key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or getattr(settings, 'OPENAI_API_KEY', None)
openai_client = None
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY') or getattr(settings, 'ANTHROPIC_API_KEY', None)
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY') or getattr(settings, 'GOOGLE_API_KEY', None)
HF_API_KEY = os.getenv('HUGGINGFACE_API_KEY') or getattr(settings, 'HUGGINGFACE_API_KEY', None)

# Configure Tesseract OCR binary path if provided via env or settings
_tesseract_cmd = os.getenv('TESSERACT_CMD') or getattr(settings, 'TESSERACT_CMD', None)
if _tesseract_cmd:
    try:
        pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd
    except Exception:
        # Silently ignore misconfig; we'll surface a clearer error during use
        pass

def extract_text_from_pdf(file_path):
    """Extract text from PDF file using pdfplumber for better reliability and layout preservation."""
    if pdfplumber is None:
        return "Error: PDF extraction library (pdfplumber) failed to load. Please try reinstalling dependencies or use a TXT/DOCX file."
    
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"
    return text

def extract_text_from_docx(file_path):
    """Extract text from DOCX file"""
    doc = docx.Document(file_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text

def extract_text_from_image(file_path):
    """Extract text from image using OCR with light preprocessing.
    - Supports JPG/PNG and similar raster formats.
    - Applies grayscale + contrast + slight sharpening to improve OCR.
    - Uses page segmentation mode suitable for blocks of text.
    """
    try:
        image = Image.open(file_path)
        # Convert to grayscale and lightly enhance contrast
        img = ImageOps.grayscale(image)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=150, threshold=3))
        # Optional light normalization for very dark or bright scans
        img = ImageOps.autocontrast(img, cutoff=2)

        # Use an OCR configuration tuned for uniform text blocks
        ocr_config = "--psm 6"
        text = pytesseract.image_to_string(img, config=ocr_config)
        return text.strip()
    except pytesseract.TesseractNotFoundError:
        return (
            "OCR not available: Tesseract binary not found. "
            "Install Tesseract OCR and set TESSERACT_CMD to its path (e.g., "
            "C:\\Program Files\\Tesseract-OCR\\tesseract.exe on Windows)."
        )
    except Exception as e:
        return f"Error extracting text from image: {str(e)}"

def extract_text_from_file(file_path, file_type):
    """Extract text from file based on file type"""
    if file_type == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_type == 'docx':
        return extract_text_from_docx(file_path)
    elif file_type == 'image':
        return extract_text_from_image(file_path)
    elif file_type == 'txt':
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    else:
        return "Unsupported file type"

def get_youtube_video_id(url):
    """Extract YouTube video ID from URL"""
    youtube_regex = r'(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(youtube_regex, url)
    return match.group(1) if match else None

def get_youtube_transcript(video_id):
    """Get full transcript from YouTube video using the best available method."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # Try the most common class method first
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            # Fallback to instance fetch if class method is missing (seen in some versions)
            transcript_api = YouTubeTranscriptApi()
            if hasattr(transcript_api, 'fetch'):
                transcript_list = transcript_api.fetch(video_id)
                # Some versions return an object that needs to be converted or iterated
                if hasattr(transcript_list, 'to_raw_data'):
                    transcript_list = transcript_list.to_raw_data()
            else:
                return f"Error: YouTubeTranscriptApi version mismatch (no get_transcript or fetch)"

        # Combine all segments into one full text string
        if isinstance(transcript_list, list):
            transcript = ' '.join([item.get('text', '') for item in transcript_list if isinstance(item, dict)])
            return transcript
        else:
            return str(transcript_list)
            
    except Exception as e:
        return f"Error getting transcript: {str(e)}"

def _route_chat(messages, system_prompt=None, model="gpt-3.5-turbo", max_tokens=4000):
    """Route chat to the appropriate provider based on model string.
    Resolve API keys at call time to avoid import-order issues.
    """
    def _strip_think_blocks(text):
        try:
            if not isinstance(text, str):
                return text
            # Remove <think>...</think> blocks
            stripped = re.sub(r"<\s*think\b[^>]*>[\s\S]*?<\s*/\s*think\s*>", "", text, flags=re.IGNORECASE)
            if stripped.strip():
                return stripped
            # If stripping leaves nothing, extract inner <think> content and return it without tags
            inner_parts = re.findall(r"<\s*think\b[^>]*>([\s\S]*?)<\s*/\s*think\s*>", text, flags=re.IGNORECASE)
            joined = "\n\n".join([p.strip() for p in inner_parts if isinstance(p, str) and p.strip()])
            return joined if joined.strip() else text
        except Exception:
            return text
    try:
        start_time = time.time()
        m = (model or "gpt-3.5-turbo").lower()
        
        # MiniMax Routing Integration
        actual_model_name = model
        selected_model_obj = None
        
        # Phase 10: Experimental Mode Logging
        if m != "auto" and getattr(settings, 'ENABLE_ROUTER_EXPERIMENT', False):
            try:
                # Predict what Auto would have chosen for comparison
                combined_text_exp = (system_prompt or "") + (messages[-1].get('content', '') if messages else "")
                task_type_exp = "chat"
                exp_features = extract_task_features(combined_text_exp, task_type_exp)
                exp_model = get_best_model(exp_features)
                if exp_model:
                    logging.getLogger(__name__).info(f"[EXPERIMENT] Static choice: {model} | Router would have chosen: {exp_model.model_name}")
            except Exception:
                pass

        if m == "auto":
            # Extract features from the latest message for routing
            # We use the system prompt + last user message as a proxy for the task content
            combined_text = (system_prompt or "") + (messages[-1].get('content', '') if messages else "")
            # Default task type detection
            task_type = "chat"
            if "summarize" in (system_prompt or "").lower(): task_type = "summarize"
            elif "analyze" in (system_prompt or "").lower(): task_type = "analyze"
            elif "generate" in (system_prompt or "").lower(): task_type = "generate"
            
            features = extract_task_features(combined_text, task_type)
            selected_model_obj = get_best_model(features)
            if selected_model_obj:
                actual_model_name = selected_model_obj.model_name
                m = actual_model_name.lower()
                logging.getLogger(__name__).info(f"MiniMax Router selected: {actual_model_name}")
            else:
                actual_model_name = "gpt-3.5-turbo"
                m = "gpt-3.5-turbo"

        ALLOW_FALLBACKS = bool(getattr(settings, 'ALLOW_MODEL_FALLBACKS', False))
        # Resolve keys dynamically each call
        OPENAI_KEY = os.getenv('OPENAI_API_KEY') or getattr(settings, 'OPENAI_API_KEY', None)
        
        # Ensure client is initialized if key is present
        global openai_client
        if OPENAI_KEY and not openai_client:
             openai_client = OpenAI(api_key=OPENAI_KEY)
             
        ANTH_KEY = os.getenv('ANTHROPIC_API_KEY') or getattr(settings, 'ANTHROPIC_API_KEY', None)
        GOOGLE_KEY = os.getenv('GOOGLE_API_KEY') or getattr(settings, 'GOOGLE_API_KEY', None)
        HF_KEY = os.getenv('HUGGINGFACE_API_KEY') or getattr(settings, 'HUGGINGFACE_API_KEY', None)
        logging.getLogger(__name__).debug(
            f"Routing chat: model='{model}', fallbacks={'on' if ALLOW_FALLBACKS else 'off'}, "
            f"keys={{'openai':{bool(OPENAI_KEY)}, 'anthropic':{bool(ANTH_KEY)}, 'google':{bool(GOOGLE_KEY)}, 'hf':{bool(HF_KEY)}}}"
        )
        # Consolidate effective system instruction: persona + any system messages (e.g., doc context)
        sys_msgs = [
            (msg.get('content') or '').strip()
            for msg in (messages or []) if msg.get('role') == 'system'
        ]
        effective_system = (system_prompt or '').strip()
        if sys_msgs:
            extra = "\n\n".join([s for s in sys_msgs if s])
            effective_system = (effective_system + ("\n\n" + extra if effective_system else extra)).strip()
        # Use only the latest user message for single-turn providers to reduce drift
        last_user_msg = ''
        for msg in reversed(messages or []):
            if msg.get('role') == 'user':
                last_user_msg = (msg.get('content') or '').strip()
                break
        def _finish(res_text, used_model_name):
            try:
                duration = time.time() - start_time
                # Attempt to log runtime stats
                mod_prof = ModelProfile.objects.filter(model_name=used_model_name).first()
                if mod_prof:
                    # Estimate tokens for cost
                    # In a real scenario, we'd get this from the API response
                    in_tokens = extract_task_features(str(messages), "chat")["token_count"]
                    out_tokens = extract_task_features(res_text, "chat")["token_count"]
                    cost = (in_tokens/1000 * mod_prof.price_per_1k_input_tokens) + (out_tokens/1000 * mod_prof.price_per_1k_output_tokens)
                    
                    stat = ModelRuntimeStats.objects.create(
                        model=mod_prof,
                        task_type="chat", # or dynamic
                        actual_latency=duration,
                        actual_cost=cost,
                        token_count=in_tokens + out_tokens
                    )

                    # Trigger Hallucination Audit for substantive tasks
                    # Don't audit the judge itself to avoid infinite loops
                    if used_model_name != "MiniMaxAI/MiniMax-M2:novita" and res_text and len(res_text) > 50:
                        from router.tasks import audit_hallucination_task
                        # Get a snippet of the source content from messages
                        source_snippet = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), "")
                        if source_snippet:
                             audit_hallucination_task.delay(stat.id, source_snippet, res_text)
            except Exception as le:
                logging.getLogger(__name__).error(f"Failed to log runtime stats: {le}")
            return res_text

        if m.startswith("claude") or m.startswith("anthropic"):
            if Anthropic is None or not ANTH_KEY:
                logging.getLogger(__name__).warning(
                    f"Anthropic not configured: import={'ok' if Anthropic else 'missing'}, key_present={bool(ANTH_KEY)}"
                )
                if not ALLOW_FALLBACKS:
                    return _finish(f"Provider not configured for model '{model}'. Set ANTHROPIC_API_KEY to use this model.\n\n[model: {model}]", model)
                # Provider not configured: fall back to OpenAI only if allowed
                final_messages = []
                if system_prompt:
                    final_messages.append({"role": "system", "content": system_prompt})
                final_messages.extend(messages)
                if not openai_client:
                     return "OpenAI client not initialized."
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=final_messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo]", "gpt-3.5-turbo")
            client = Anthropic(api_key=ANTH_KEY)
            # Anthropic: pass effective system instruction and latest user turn
            user_content = [{"type": "text", "text": last_user_msg or ''}]
            try:
                resp = client.messages.create(
                    model=actual_model_name,
                    max_tokens=max_tokens,
                    system=effective_system or None,
                    messages=[{"role": "user", "content": user_content}]
                )
            except Exception as e:
                logging.getLogger(__name__).exception(f"Anthropic call failed for model='{actual_model_name}': {e}")
                if not ALLOW_FALLBACKS:
                    return _finish(f"Error calling Anthropic model '{actual_model_name}': {str(e)}\n\n[model: {actual_model_name}]", actual_model_name)
                
                # Fallback to OpenAI only if allowed
                final_messages = []
                if effective_system:
                    final_messages.append({"role": "system", "content": effective_system})
                final_messages.extend([m for m in messages if m.get('role') != 'system'])
                if not openai_client:
                     return "OpenAI client not initialized."
                
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=final_messages,
                        max_tokens=max_tokens,
                        temperature=0.3,
                    )
                    return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo (fallback)]", "gpt-3.5-turbo")
                except Exception as fallback_err:
                    return _finish(f"Anthropic error: {str(e)}. Fallback error: {str(fallback_err)}\n\n[model: {actual_model_name}]", actual_model_name)
            out = []
            for p in getattr(resp, 'content', []):
                try:
                    if getattr(p, 'type', '') == 'text':
                        out.append(p.text)
                except Exception:
                    pass
            logging.getLogger(__name__).debug(
                f"Anthropic success: model='{actual_model_name}', tokens={max_tokens}, reply_len={len(''.join(out))}"
            )
            return _finish((("".join(out) or "") + f"\n\n[model: {actual_model_name}]"), actual_model_name)
        elif m.startswith("gemini") or m.startswith("google") or m.startswith("models/gemini"):
            if genai is None or not GOOGLE_KEY:
                logging.getLogger(__name__).warning(
                    f"Gemini not configured: import={'ok' if genai else 'missing'}, key_present={bool(GOOGLE_KEY)}"
                )
                if not ALLOW_FALLBACKS:
                    return _finish(f"Provider not configured for model '{model}'. Set GOOGLE_API_KEY to use this model.\n\n[model: {model}]", model)
                # Provider not configured: gracefully fall back to OpenAI
                final_messages = []
                if system_prompt:
                    final_messages.append({"role": "system", "content": system_prompt})
                final_messages.extend(messages)
                if not openai_client:
                     return "OpenAI client not initialized."
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=final_messages,
                    max_tokens=max_tokens or 2000,
                    temperature=0.3,
                )
                return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo]", "gpt-3.5-turbo")
            
            # Initialize client with API key
            client = genai.Client(api_key=GOOGLE_KEY)
            
            try:
                # Prepare configuration
                config = {"max_output_tokens": max_tokens}
                if effective_system:
                    config["system_instruction"] = effective_system
                
                # Generate content
                prompt_in = last_user_msg or ""
                resp = client.models.generate_content(
                    model=actual_model_name, 
                    contents=prompt_in,
                    config=config
                )
                
                text_out = getattr(resp, 'text', '') or ""
                if not text_out:
                    # Defensive check for parts
                    try:
                        text_out = resp.candidates[0].content.parts[0].text
                    except Exception:
                        text_out = str(resp)
                
                logging.getLogger(__name__).debug(
                    f"Gemini success: model='{actual_model_name}', reply_len={len(text_out)}"
                )
                return _finish((text_out + f"\n\n[model: {actual_model_name}]"), actual_model_name)
            except Exception as e:
                logging.getLogger(__name__).error(
                    f"Gemini generate_content failed for model='{actual_model_name}': {e}"
                )
                if not ALLOW_FALLBACKS:
                    return _finish(f"Error calling Gemini model '{actual_model_name}': {str(e)}\n\n[model: {actual_model_name}]", actual_model_name)
                
                # Fallback to OpenAI
                final_messages = []
                if effective_system:
                    final_messages.append({"role": "system", "content": effective_system})
                final_messages.extend([m for m in messages if m.get('role') != 'system'])
                if not openai_client:
                     return "OpenAI client not initialized."
                
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=final_messages,
                        max_tokens=max_tokens,
                        temperature=0.3,
                    )
                    return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo (fallback)]", "gpt-3.5-turbo")
                except Exception as fallback_err:
                    return _finish(f"Gemini error: {str(e)}. Fallback error: {str(fallback_err)}\n\n[model: {actual_model_name}]", actual_model_name)
        elif (('/' in (actual_model_name or '')) and not m.startswith('models/gemini')) or m.startswith('hf') or ('huggingface' in m):
            # Hugging Face Inference API
            if InferenceClient is None or not HF_KEY:
                logging.getLogger(__name__).warning(
                    f"HuggingFace not configured: import={'ok' if InferenceClient else 'missing'}, key_present={bool(HF_KEY)}"
                )
                if not ALLOW_FALLBACKS:
                    return _finish(f"Provider not configured for Hugging Face model '{actual_model_name}'. Set HUGGINGFACE_API_KEY to use this model.\n\n[model: {actual_model_name}]", actual_model_name)
                # Provider not configured: fallback to OpenAI only if allowed
                final_messages = []
                if effective_system:
                    final_messages.append({"role": "system", "content": effective_system})
                final_messages.extend(messages)
                if not openai_client:
                     return "OpenAI client not initialized."
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=final_messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo]", "gpt-3.5-turbo")
            # Build chat messages for OpenAI-compatible chat completions
            final_messages = []
            if effective_system:
                final_messages.append({"role": "system", "content": effective_system})
            # Filter out system messages since they are already in effective_system
            final_messages.extend([m for m in messages if m.get('role') != 'system'])
            try:
                # Normalize model/provider for Inference Providers router
                raw_model = (actual_model_name or '').strip()
                hf_model = raw_model
                provider = 'hf-inference'
                # ... [hf routing logic same as before, but using actual_model_name]
                # (Skipping for brevity in replacement, but I should keep the logic)

                # If model is of form "org/repo:suffix", detect provider/policy vs revision
                if ':' in raw_model and '/' in raw_model:
                    base, suffix = raw_model.split(':', 1)
                    low = suffix.strip().lower()
                    provider_aliases = {
                        'hf': 'hf-inference',
                        'hf-inference': 'hf-inference',
                        'novita': 'novita',
                        'groq': 'groq',
                        'together': 'together',
                        'fireworks': 'fireworks-ai',
                        'fireworks-ai': 'fireworks-ai',
                        'fal': 'fal-ai',
                        'fal-ai': 'fal-ai',
                        'sambanova': 'sambanova',
                        'cohere': 'cohere',
                        'replicate': 'replicate',
                        'fastest': 'auto',
                        'cheapest': 'auto',
                    }
                    if low in provider_aliases:
                        provider = provider_aliases[low]
                        hf_model = base
                    else:
                        # Treat suffix as Hub revision when not a known provider/policy
                        hf_model = f"{base}@{suffix}"
                # Also support explicit provider via "org/repo@provider"
                if '@' in hf_model and '/' in hf_model:
                    base, alias = hf_model.split('@', 1)
                    hf_model = base
                    alias = alias.strip().lower()
                    provider_map = {
                        'hf': 'hf-inference',
                        'hf-inference': 'hf-inference',
                        'novita': 'novita',
                        'groq': 'groq',
                        'together': 'together',
                        'fireworks-ai': 'fireworks-ai',
                        'fal-ai': 'fal-ai',
                        'sambanova': 'sambanova',
                        'cohere': 'cohere',
                        'replicate': 'replicate',
                    }
                    provider = provider_map.get(alias, provider)
                client = InferenceClient(
                    provider=provider,
                    api_key=HF_KEY,
                )
                logging.getLogger(__name__).debug(
                    f"HuggingFace routing: base_model='{hf_model}', provider='{provider}'"
                )
                # Call OpenAI-compatible chat completions on the router
                try:
                    completion = client.chat.completions.create(
                        model=hf_model,
                        messages=final_messages,
                        max_tokens=max_tokens,
                        temperature=0.3,
                    )
                except Exception as e:
                    logging.getLogger(__name__).error(f"HF Request failed: model={hf_model}, error={e}")
                    raise e

                # Extract content defensively from OpenAI-compatible response
                content = None
                try:
                    if completion and hasattr(completion, 'choices') and completion.choices:
                        choice = completion.choices[0]
                        # Handle both object and dict access
                        message = getattr(choice, 'message', None)
                        if message:
                            content = getattr(message, 'content', None)
                        
                        if content is None and isinstance(choice, dict):
                            content = choice.get('message', {}).get('content')
                        
                        # Handle list content (some providers return segments)
                        if isinstance(content, list):
                            parts = []
                            for part in content:
                                if isinstance(part, dict):
                                    parts.append(part.get('text', '') or part.get('content', ''))
                                elif isinstance(part, str):
                                    parts.append(part)
                            content = "".join(parts)
                except Exception as e:
                    logging.getLogger(__name__).error(f"Error parsing HF response: {e}")
                
                text_out = content or ''
                text_out = _strip_think_blocks(text_out)
                
                if not text_out.strip():
                    logging.getLogger(__name__).warning(f"HF returned empty content for model='{hf_model}'")
                    return _finish(f"Error: The model '{hf_model}' returned an empty response. Please try again.\n\n[model: {hf_model}:{provider}]", actual_model_name)

                logging.getLogger(__name__).debug(
                    f"HuggingFace success: model='{hf_model}', provider='{provider}', reply_len={len(text_out)}"
                )
                return _finish(text_out + f"\n\n[model: {hf_model}:{provider}]", actual_model_name)
            except Exception:
                logging.getLogger(__name__).exception(
                    f"HuggingFace call failed for model='{actual_model_name}'"
                )
                if not ALLOW_FALLBACKS:
                    return _finish(f"Error calling Hugging Face model '{actual_model_name}'.\n\n[model: {actual_model_name}]", actual_model_name)
                # Fallback to OpenAI on error only if allowed
                final_messages = []
                if effective_system:
                    final_messages.append({"role": "system", "content": effective_system})
                final_messages.extend(messages)
                if not openai_client:
                     return "OpenAI client not initialized."
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=final_messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return _finish((response.choices[0].message.content or "") + "\n\n[model: gpt-3.5-turbo]", "gpt-3.5-turbo")
        else:
            # Default OpenAI
            final_messages = []
            if system_prompt:
                final_messages.append({"role": "system", "content": system_prompt})
            final_messages.extend(messages)
            if not openai_client:
                 return "OpenAI client not initialized."
            response = openai_client.chat.completions.create(
                model=actual_model_name or "gpt-3.5-turbo",
                messages=final_messages,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            out = response.choices[0].message.content or ""
            out = _strip_think_blocks(out)
            return _finish((out + f"\n\n[model: {actual_model_name or 'gpt-3.5-turbo'}]"), actual_model_name or "gpt-3.5-turbo")
    except Exception as e:
        # Log failure for the router to see
        try:
            mod_prof = ModelProfile.objects.filter(model_name=actual_model_name if 'actual_model_name' in locals() else model).first()
            if mod_prof:
                ModelRuntimeStats.objects.create(
                    model=mod_prof,
                    task_type="chat",
                    actual_latency=0, # Signal failure
                    actual_cost=0,
                    token_count=0
                )
        except Exception:
            pass
        return f"Error chatting: {str(e)}\n\n[model: {model or 'unknown'}]"


def summarize_text(text, target_words=None, max_tokens=500, preset=None, model=None):
    """Summarize text using selected model/provider with optional preset formatting."""
    try:
        word_instruction = "" if not target_words else f" in approximately {int(target_words)} words"
        preset_instruction = ""
        if preset == 'bullet_points':
            preset_instruction = "Format strictly as a markdown bullet list. Use '-' at the start of each line. No introduction or conclusion. Keep bullets concise and study-friendly."
        elif preset == 'detailed_summary':
            preset_instruction = " Provide a comprehensive paragraph-style summary."
        elif preset == 'study_notes':
            preset_instruction = " Produce study notes: headings for topics, sub-bullets for key concepts and definitions."
        elif preset == 'brief_summary':
            preset_instruction = " Keep it brief for quick revision."
        messages = [
            {"role": "user", "content": f"Summarize the following text{word_instruction} and {preset_instruction} Avoid omitting key points.\n\n{text}"}
        ]
        return _route_chat(messages, system_prompt="You are a helpful assistant that summarizes text clearly and faithfully.", model=model or "gpt-3.5-turbo", max_tokens=max_tokens)
    except Exception as e:
        return f"Error summarizing text: {str(e)}"

def generate_answers(text, target_words=None, max_tokens=500, preset=None, model=None):
    """Generate answers using selected model/provider with optional preset type."""
    try:
        word_instruction = "" if not target_words else f" in approximately {int(target_words)} words"
        preset_instruction = ""
        if preset == 'exam_answers':
            preset_instruction = " Generate comprehensive, step-by-step exam answers. Use numbered steps and short headings for clarity."
        elif preset == 'practice_questions':
            preset_instruction = " Create 6-10 practice questions with detailed answers. Format as a numbered list where each item contains 'Q:' followed by the question and 'A:' followed by the answer."
        elif preset == 'study_plan':
            preset_instruction = " Draft a personalized study schedule. Use a bullet list grouped by days/weeks with time blocks and goals."
        messages = [
            {"role": "user", "content": f"Generate clear, step-by-step answers{word_instruction} to the following questions or content.{preset_instruction}\n\n{text}"}
        ]
        return _route_chat(messages, system_prompt="You are a helpful assistant that generates accurate, well-structured answers.", model=model or "gpt-3.5-turbo", max_tokens=max_tokens)
    except Exception as e:
        return f"Error generating answers: {str(e)}"

def analyze_text(text, target_words=None, max_tokens=500, preset=None, model=None):
    """Analyze text using selected model/provider with optional preset for analysis type."""
    try:
        word_instruction = "" if not target_words else f" in approximately {int(target_words)} words"
        preset_instruction = ""
        if preset == 'question_patterns':
            preset_instruction = " Identify recurring question patterns and topics. Output a bullet list. For each pattern, include a short label and 1-2 example phrasings."
        elif preset == 'predict_questions':
            preset_instruction = " Predict likely exam questions based on the content. Output as a numbered list of questions only, optionally include one-sentence rationale per item."
        elif preset == 'topic_importance':
            preset_instruction = " Rank topics by exam importance as a numbered list from most to least important, with a brief justification for each."
        messages = [
            {"role": "user", "content": f"Analyze the following text, identify key insights, and rank topics by importance{word_instruction}.{preset_instruction}\n\n{text}"}
        ]
        return _route_chat(messages, system_prompt="You are a helpful assistant that analyzes text and ranks topics by importance.", model=model or "gpt-3.5-turbo", max_tokens=max_tokens)
    except Exception as e:
        return f"Error analyzing text: {str(e)}"

def translate_text_free(text, target_language_code, source_language_code='auto'):
    """Translate text using the free LibreTranslate API.
    - Tries multiple public endpoints for resilience.
    - Falls back to form-encoded POST if JSON fails.
    - Splits large inputs into chunks to avoid payload limits.
    - Does not require any API key.
    - target_language_code: e.g., 'es', 'fr', 'de', 'hi', 'en'.
    """
    endpoints = [
        'https://libretranslate.de/translate',
        'https://translate.argosopentech.com/translate',
        'https://translate.astian.org/translate',
        'https://libretranslate.com/translate',
    ]

    def _detect_language(sample_text):
        """Detect language using LibreTranslate /detect endpoint across fallbacks.
        Returns a language code or None if detection fails.
        """
        sample = (sample_text or '').strip()
        if not sample:
            return None
        sample = sample[:1000]
        detect_paths = [e.replace('/translate', '/detect') for e in endpoints]
        payload = {'q': sample}
        # Try JSON then form-encoded for each endpoint
        for endpoint in detect_paths:
            try:
                data_json = json.dumps(payload).encode('utf-8')
                req_json = urlrequest.Request(endpoint, data=data_json, headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'Smartly/1.0'})
                with urlrequest.urlopen(req_json, timeout=20) as resp:
                    body = resp.read().decode('utf-8')
                    parsed = json.loads(body)
                    # Expected: list of { language: 'en', confidence: 0.99 }
                    if isinstance(parsed, list) and parsed:
                        lang = parsed[0].get('language')
                        if lang:
                            return lang
            except Exception:
                pass
            try:
                data_form = urlencode(payload).encode('utf-8')
                req_form = urlrequest.Request(endpoint, data=data_form, headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json', 'User-Agent': 'Smartly/1.0'})
                with urlrequest.urlopen(req_form, timeout=20) as resp:
                    body = resp.read().decode('utf-8')
                    parsed = json.loads(body)
                    if isinstance(parsed, list) and parsed:
                        lang = parsed[0].get('language')
                        if lang:
                            return lang
            except Exception:
                continue
        return None

    def _translate_chunk(chunk):
        chunk = chunk or ''
        if not chunk.strip():
            return ''
        # Determine source language if auto was requested
        src = source_language_code or 'auto'
        if (src == 'auto'):
            detected = _detect_language(chunk)
            if detected:
                src = detected
        payload = {
            'q': chunk,
            'source': src,
            'target': target_language_code,
            'format': 'text'
        }
        for endpoint in endpoints:
            # Try JSON first
            try:
                data_json = json.dumps(payload).encode('utf-8')
                req_json = urlrequest.Request(
                    endpoint,
                    data=data_json,
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'User-Agent': 'Smartly/1.0'
                    }
                )
                with urlrequest.urlopen(req_json, timeout=30) as resp:
                    body = resp.read().decode('utf-8')
                    parsed = json.loads(body)
                    translated = parsed.get('translatedText', '')
                    if translated and translated != chunk:
                        return translated
            except HTTPError as e:
                # Attempt to read error body to see if it contains JSON we can parse
                try:
                    err_body = e.read().decode('utf-8')
                    parsed_err = json.loads(err_body)
                    translated = parsed_err.get('translatedText', '')
                    if translated:
                        return translated
                except Exception:
                    pass
                # Fall through to form-encoded attempt
            except (URLError, Exception):
                # Fall through to form-encoded attempt
                pass

            # Form-encoded fallback
            try:
                data_form = urlencode(payload).encode('utf-8')
                req_form = urlrequest.Request(
                    endpoint,
                    data=data_form,
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Accept': 'application/json',
                        'User-Agent': 'Smartly/1.0'
                    }
                )
                with urlrequest.urlopen(req_form, timeout=30) as resp:
                    body = resp.read().decode('utf-8')
                    parsed = json.loads(body)
                    translated = parsed.get('translatedText', '')
                    if translated and translated != chunk:
                        return translated
            except Exception:
                # Try next endpoint
                continue

        # Secondary fallback: MyMemory Translated API (free)
        try:
            def _mm_code(code: str) -> str:
                c = (code or '').lower()
                # Normalize Chinese variants
                if c in ('zh', 'zh-cn', 'cn', 'zh-hans'):
                    return 'zh-CN'
                if c in ('zh-tw', 'tw', 'zh-hant', 'zh-hk', 'hk'):
                    return 'zh-TW'
                # MyMemory does NOT support 'auto' or empty sources; default to English
                if not c or c in ('auto', 'und', 'unknown'):
                    return 'en'
                # Return as-is for typical 2-letter codes
                return code

            def _mm_translate_small(text_part: str) -> str:
                src_pair = f"{_mm_code(payload['source'])}|{_mm_code(payload['target'])}"
                query = urlencode({'q': text_part, 'langpair': src_pair})
                url = f"https://api.mymemory.translated.net/get?{query}"
                req_mm = urlrequest.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'Smartly/1.0'})
                with urlrequest.urlopen(req_mm, timeout=30) as resp:
                    body = resp.read().decode('utf-8')
                    parsed = json.loads(body)
                    translated = ''
                    if isinstance(parsed, dict):
                        translated = (parsed.get('responseData') or {}).get('translatedText', '')
                        if translated == text_part:
                            matches = parsed.get('matches') or []
                            for m in matches:
                                cand = m.get('translation')
                                if cand and cand != text_part:
                                    translated = cand
                                    break
                    return translated

            # MyMemory free API limits q to ~500 chars. Split into ~450-char chunks.
            mm_max = 450
            if len(chunk) <= mm_max:
                mm_out = _mm_translate_small(chunk)
                if mm_out and mm_out != chunk:
                    return mm_out
            else:
                out_parts = []
                start = 0
                while start < len(chunk):
                    end = min(start + mm_max, len(chunk))
                    newline_pos = chunk.rfind('\n', start, end)
                    space_pos = chunk.rfind(' ', start, end)
                    if newline_pos != -1 and newline_pos > start + 50:
                        end = newline_pos
                    elif space_pos != -1 and space_pos > start + 50:
                        end = space_pos
                    part = chunk[start:end]
                    translated_part = _mm_translate_small(part)
                    out_parts.append(translated_part or part)
                    start = end
                mm_joined = ''.join(out_parts)
                if mm_joined and mm_joined != chunk:
                    return mm_joined
        except Exception:
            pass

        # If none of the endpoints succeeded or translation unchanged
        return f"[Translation unchanged: provider unavailable or returned same text]"

    # Chunk by ~4000 characters to stay under typical API limits
    chunks = []
    max_len = 4000
    text = text or ''
    if len(text) <= max_len:
        chunks = [text]
    else:
        start = 0
        while start < len(text):
            end = min(start + max_len, len(text))
            # try to break at a newline for cleaner splits
            newline_pos = text.rfind('\n', start, end)
            if newline_pos != -1 and newline_pos > start + 1000:
                end = newline_pos
            chunks.append(text[start:end])
            start = end

    translated_parts = [_translate_chunk(c) for c in chunks]
    return ''.join(translated_parts)

def chat_with_openai(messages, system_prompt=None, model="gpt-3.5-turbo", max_tokens=800):
    """Generic chat helper using OpenAI ChatCompletion. Library uses this and must stay OpenAI."""
    try:
        final_messages = []
        if system_prompt:
            final_messages.append({"role": "system", "content": system_prompt})
        final_messages.extend(messages)
        if not openai_client:
             return "OpenAI client not initialized."
        response = openai_client.chat.completions.create(
            model=model,
            messages=final_messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return (response.choices[0].message.content or "") + f"\n\n[model: {model}]"
    except Exception as e:
        return f"Error chatting with OpenAI: {str(e)}\n\n[model: {model}]"


def recommend_youtube_videos_web(query, max_results=5, timeout=15, region=None):
    """Fetch current YouTube video recommendations using DuckDuckGo HTML search and YouTube oEmbed.
    - Returns a fenced smartly_videos JSON block for rich card rendering.
    - Filters out YouTube Shorts and deduplicates links.
    """
    try:
        q = f"site:youtube.com {query}".strip()
        ddg_url = "https://duckduckgo.com/html/?q=" + quote(q) + (f"&kl={quote(region)}" if region else "")
        req = urlrequest.Request(ddg_url, headers={'User-Agent': 'Smartly/1.0', 'Accept': 'text/html'})
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Error searching for videos: {str(e)}"

    # Extract result links from DuckDuckGo HTML (no-JS version)
    links = []
    try:
        for m in re.finditer(r'<a[^>]+class="[^\"]*result__a[^\"]*"[^>]+href="([^"]+)"', html, re.IGNORECASE):
            href = m.group(1)
            url = href
            if 'uddg=' in href:
                try:
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    if 'uddg' in qs and qs['uddg']:
                        url = unquote(qs['uddg'][0])
                    else:
                        mm = re.search(r'uddg=([^&]+)', href)
                        url = unquote(mm.group(1)) if mm else href
                except Exception:
                    url = href
            # Accept watch links and youtu.be; exclude shorts
            is_watch = ('youtube.com/watch' in url) or ('youtu.be/' in url)
            is_short = ('/shorts/' in url)
            if is_watch and not is_short:
                links.append(url)
            if len(links) >= max_results * 3:
                break
    except Exception:
        pass

    # Deduplicate while preserving order
    unique = []
    seen = set()
    for u in links:
        key = u.split('&')[0]
        if key not in seen:
            seen.add(key)
            unique.append(u)
        if len(unique) >= max_results * 2:
            break

    # Fetch title/channel via YouTube oEmbed (no API key) and build JSON
    results = []
    for link in unique:
        title = None
        channel = None
        thumb = None
        try:
            oembed = "https://www.youtube.com/oembed?format=json&url=" + quote(link, safe='')
            rq = urlrequest.Request(oembed, headers={'User-Agent': 'Smartly/1.0', 'Accept': 'application/json'})
            with urlrequest.urlopen(rq, timeout=timeout) as r2:
                data = json.loads(r2.read().decode('utf-8'))
                title = data.get('title')
                channel = data.get('author_name')
        except Exception:
            pass
        try:
            # Extract video id for thumbnail
            m = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})(?:[&?/]|$)', link)
            vid_id = m.group(1) if m else None
            if vid_id:
                thumb = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
        except Exception:
            thumb = None
        results.append({'url': link, 'title': title or '', 'channel': channel or '', 'thumb': thumb or ''})

    if not results:
        return (
            "I couldn't find live YouTube links right now. Try refining the topic "
            "or check your network."
        )

    # Return structured fenced block for card rendering
    try:
        payload = json.dumps(results[:max_results])
        return f"```smartly_videos\n{payload}\n```"
    except Exception:
        # Fallback to markdown list
        lines = ["Here are current YouTube picks for your topic:", ""]
        for i, r in enumerate(results[:max_results], 1):
            t = r['title'] or f"Video {i}"
            ch = r['channel'] or 'YouTube'
            lines.append(f"- {t} — {ch}\n  {r['url']}")
        return "\n".join(lines)

    # Compose reply
    lines = ["Here are current YouTube picks for your topic:", ""]
    for i, r in enumerate(results, 1):
        t = r['title'] or f"Video {i}"
        ch = r['channel'] or 'YouTube'
        lines.append(f"- {t} — {ch}\n  {r['url']}")
    return "\n".join(lines)