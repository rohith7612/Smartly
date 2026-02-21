# Smartly - AI Document Processing Platform

A powerful Django-based web application that leverages multiple AI providers to process documents and YouTube videos. Transform your content with intelligent summarization, question generation, analysis, and translation capabilities.

## 🚀 Features

### Document Processing
- **Multi-format Support**: PDF, DOCX, TXT, and image files with OCR
- **AI-powered Analysis**: Summarization, question generation, content analysis, and translation
- **Multiple AI Providers**: OpenAI GPT models, Anthropic Claude, Google Gemini, Hugging Face
- **Batch Processing**: Process multiple documents simultaneously
- **Professional Export**: Generate beautifully formatted PDF reports

### YouTube Integration
- **Transcript Extraction**: Automatic transcript retrieval from YouTube videos
- **Video Analysis**: Apply AI processing to video content
- **Watch & Chat**: Interactive chat interface grounded in video transcripts
- **Embed Support**: Watch videos while analyzing content

### Advanced Features
- **Document Chat**: Context-aware conversations with your documents
- **Library Organization**: AI-powered document categorization
- **Project Recommendations**: AI-suggested projects based on your content
- **Multi-language Support**: Translation capabilities with multiple providers
- **User Management**: Secure authentication and user-specific content isolation

## 🛠️ Technology Stack

### Backend
- **Framework**: Django 4.2.23
- **Database**: PostgreSQL (production), SQLite (development)
- **AI Integration**: OpenAI, Anthropic, Google Gemini, Hugging Face
- **File Processing**: PyPDF2, python-docx, pytesseract (OCR)
- **PDF Generation**: ReportLab

### Frontend
- **Framework**: Bootstrap 5
- **Icons**: Font Awesome
- **Typography**: Inter font
- **Styling**: Custom CSS with CSS variables

### Deployment
- **Static Files**: WhiteNoise
- **WSGI Server**: Gunicorn
- **Database URL**: dj-database-url for configuration

## 📋 Prerequisites

- Python 3.8+
- PostgreSQL (for production)
- Tesseract OCR (optional, for image text extraction)
- AI Provider API keys (OpenAI, Anthropic, Google, Hugging Face)

## 🔧 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/smartly.git
cd smartly
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your API keys:

```env
# AI Provider API Keys
OPENAI_API_KEY="your-openai-api-key"
ANTHROPIC_API_KEY="your-anthropic-api-key"
GOOGLE_API_KEY="your-google-api-key"
HUGGINGFACE_API_KEY="your-huggingface-api-key"

# Database Configuration
DATABASE_URL="postgresql://user:password@localhost:5432/smartly"

# Optional: Tesseract OCR Configuration
TESSERACT_CMD="C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
TESSDATA_PREFIX="C:\\Program Files\\Tesseract-OCR\\tessdata"
```

### 5. Run Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser
```bash
python manage.py createsuperuser
```

### 7. Run the Development Server
```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000` to access the application.

## 📖 Usage Guide

### Document Upload and Processing

1. **Upload Documents**: Click "Upload Document" and select your files
2. **Choose Processing Type**: Select from summarization, question generation, analysis, or translation
3. **Process**: The system will extract text and apply AI processing
4. **View Results**: Access processed results in your dashboard
5. **Export**: Download results as professional PDF documents

### YouTube Video Processing

1. **Accessibility Section**: Navigate to the accessibility page
2. **Enter YouTube URL**: Paste the video URL and load the transcript
3. **Process Transcript**: Apply AI processing to the video content
4. **Watch & Chat**: Use the interactive chat interface while watching

### Document Chat Feature

1. **Chat Interface**: Access the chat feature from the navigation
2. **Select Documents**: Choose which documents to include in the context
3. **Ask Questions**: Interact with AI about your document content
4. **Focus Mode**: Enable focus mode to restrict answers to document content only

### Library Organization

1. **Library View**: Access your personal document library
2. **AI Categorization**: Documents are automatically organized by topic
3. **Project Recommendations**: Get AI-suggested projects based on your content
4. **Quick Access**: Easily find and manage your processed documents

## 🔧 Configuration

### AI Model Selection

Users can select their preferred AI model from the accessibility page:
- **OpenAI**: GPT-3.5 Turbo, GPT-4, GPT-4o, GPT-4o Mini
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Haiku
- **Google**: Gemini 2.5 Pro, Gemini 2.5 Flash
- **Hugging Face**: MiniMax M2 Novita

### Processing Options

Each processing type supports various parameters:
- **Length Control**: Specify word count or token limits
- **Presets**: Pre-configured settings for different use cases
- **Language Selection**: Target language for translations

## 🚀 Performance Optimization

The application includes several performance optimizations:

### Database Optimization
- **Query Optimization**: Uses `select_related` and `prefetch_related` for efficient queries
- **Database Indexes**: Custom indexes on frequently queried fields
- **Field Selection**: Only necessary fields are loaded from database

### Caching
- **Page Caching**: Home page cached for 15 minutes
- **Session Caching**: Extracted text cached to avoid re-processing
- **Statistics Caching**: Dashboard statistics cached for 5 minutes

### Memory Management
- **Chunked File Reading**: Large text files processed in chunks
- **Memory-efficient Text Extraction**: Optimized PDF and DOCX processing
- **Temporary File Cleanup**: Automatic cleanup of temporary files

### Pagination
- **Per-section Pagination**: Dashboard uses separate pagination for each content type
- **Optimized Querysets**: Pagination works with optimized database queries

## 🔒 Security Features

- **User Authentication**: Secure user registration and login
- **Permission-based Access**: Users can only access their own content
- **CSRF Protection**: Django's built-in CSRF protection
- **File Type Validation**: Secure file upload handling

## 🧪 Testing

Run the test suite:
```bash
python manage.py test
```

## 🚢 Deployment

### Production Checklist

1. **Environment Variables**: Set production environment variables
2. **Database**: Configure PostgreSQL database
3. **Static Files**: Run `python manage.py collectstatic`
4. **Security**: Set `DEBUG=False` and configure `ALLOWED_HOSTS`
5. **SSL**: Configure HTTPS with proper SSL certificates
6. **Monitoring**: Set up error tracking and logging

### Docker Deployment

```dockerfile
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "smartly.wsgi:application", "--bind", "0.0.0.0:8000"]
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 API Documentation

The application provides several endpoints for document processing:

### Document Endpoints
- `POST /upload/` - Upload documents
- `GET /process/<id>/` - Process document with AI
- `GET /result/<id>/` - View processing results
- `GET /download/result/<id>/` - Download result as PDF

### YouTube Endpoints
- `POST /accessibility/` - Process YouTube videos
- `GET /youtube/watch/` - Watch and chat with video
- `GET /youtube_result/<id>/` - View YouTube processing results

### Chat Endpoints
- `GET /chat/` - Access chat interface
- `POST /chat/` - Send chat messages
- `GET /chat/<id>/delete/` - Delete chat sessions

## 📊 Performance Monitoring

The application includes built-in performance optimizations:

- **Database Query Monitoring**: Track query performance
- **Cache Hit Rates**: Monitor caching effectiveness
- **Memory Usage**: Optimized memory management for large files
- **Response Times**: Fast page loads with caching

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Django framework for the robust web foundation
- Multiple AI providers for powerful text processing capabilities
- Bootstrap for the responsive UI framework
- Open source libraries for document processing and OCR


**Smartly** - Transform your documents with the power of AI. 🚀
