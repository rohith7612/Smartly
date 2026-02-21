from django.urls import path
from . import views
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('upload/', views.upload_document, name='upload_document'),
    
    # Document Processing
    path('process/<int:document_id>/', views.process_document, name='process_document'),
    path('document/<int:document_id>/processing/', views.document_processing_status, name='document_processing_status'),
    path('document/<int:document_id>/check-status/', views.check_processing_status, name='check_processing_status'),
    path('process/multi/', views.process_multi_documents, name='process_multi_documents'),
    
    # Document Management
    path('document/<int:document_id>/delete/', views.delete_document, name='delete_document'),
    path('document/<int:document_id>/file/', views.serve_document_file, name='serve_document_file'),
    
    # Results
    path('result/<int:result_id>/', views.document_result_view, name='document_result'),
    path('result/<int:result_id>/translate/', views.translate_processed_result, name='translate_processed_result'),
    path('result/<int:result_id>/delete/', views.delete_processed_result, name='delete_processed_result'),
    path('download/result/<int:result_id>/', views.download_result_pdf, name='download_result_pdf'),
    
    # YouTube
    path('youtube/video/<int:video_id>/delete/', views.delete_youtube_video, name='delete_youtube_video'),
    path('youtube/result/<int:result_id>/delete/', views.delete_youtube_result, name='delete_youtube_result'),
    path('youtube_result/<int:result_id>/', views.youtube_result_view, name='youtube_result'),
    path('download/youtube/<int:result_id>/', views.download_youtube_result_pdf, name='download_youtube_result_pdf'),
    path('youtube/watch/', views.youtube_watch_chat, name='youtube_watch_chat'),
    
    # Features
    path('summarize/', views.summarize_view, name='summarize'),
    path('generate/', views.generate_view, name='generate'),
    path('analyze/', views.analyze_view, name='analyze'),
    path('accessibility/', views.accessibility_view, name='accessibility'),
    path('chat/', views.chat_view, name='chat'),
    path('chat/<int:session_id>/delete/', views.delete_chat_session, name='delete_chat_session'),
    
    # Library
    path('library/', views.library_view, name='library'),
    path('library/recommend/', views.library_recommend_projects, name='library_recommend'),
    
    # Auth
    path('login/', LoginView.as_view(template_name='docprocessor/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('register/', views.register_view, name='register'),
]