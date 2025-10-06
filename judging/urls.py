from django.urls import path

from . import views

app_name = 'judging'

urlpatterns = [
    path('', views.JudgeDashboardView.as_view(), name='dashboard'),
    path('launch/', views.ScorePortalLandingView.as_view(), name='launch'),
    path('scan/<slug:slug>/', views.ScanRedirectView.as_view(), name='scan'),
    path('project/<int:pk>/score/', views.ScoreProjectView.as_view(), name='score'),
    path('manage/projects/', views.ProjectListView.as_view(), name='manage_projects'),
    path('manage/projects/create/', views.ProjectCreateView.as_view(), name='project_create'),
    path('manage/projects/<int:pk>/edit/', views.ProjectUpdateView.as_view(), name='project_edit'),
    path('manage/projects/<int:pk>/delete/', views.ProjectDeleteView.as_view(), name='project_delete'),
    path('manage/release/', views.ReleaseWindowView.as_view(), name='release_window'),
    path('manage/release/publish-toggle/', views.ToggleScoresPublicationView.as_view(), name='toggle_scores_public'),
    path('manage/release/<int:pk>/fire/', views.ReleaseActionView.as_view(), name='release_action'),
    path('manage/export/', views.ExportCSVView.as_view(), name='export'),
]
