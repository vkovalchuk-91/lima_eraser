from django.urls import path

from . import views

app_name = "tracks"

urlpatterns = [
    path("", views.index, name="index"),
    path("download/<str:token>/", views.download_cleaned, name="download"),
    path("strava/upload/<str:token>/", views.upload_cleaned_to_strava, name="strava_upload"),
    path(
        "strava/upload-status/<int:upload_id>/",
        views.strava_upload_status,
        name="strava_upload_status",
    ),
    path("strava/login/", views.strava_login, name="strava_login"),
    path("strava/callback/", views.strava_callback, name="strava_callback"),
    path("strava/activities/", views.strava_activities, name="strava_activities"),
    path(
        "strava/activities/<int:activity_id>/clean/",
        views.clean_strava_activity,
        name="clean_strava_activity",
    ),
    path("strava/logout/", views.strava_logout, name="strava_logout"),
]
