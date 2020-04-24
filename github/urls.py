from django.urls import path, re_path
from github import views

urlpatterns = [
    re_path(r'^fileview/(?P<repo>[0-9]+)/(?P<commit>[0-9]+)/(?P<file>[\S]+)$', views.file_view, name='repository_file_view'),
]
