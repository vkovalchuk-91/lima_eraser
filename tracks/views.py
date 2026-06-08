import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

from .gpx_processing import process_gpx, shift_gpx_times
from .strava_api import (
    StravaApiError,
    build_authorization_url,
    exchange_code,
    get_activity_detail,
    get_activity_streams,
    get_upload_status,
    list_activities,
    refresh_token,
    streams_to_gpx,
    upload_gpx_activity,
)


def index(request):
    context = {
        "strava_configured": _strava_configured(),
        "strava_athlete": request.session.get("strava_athlete"),
    }

    if request.method == "POST":
        uploaded_file = request.FILES.get("gpx_file")
        if not uploaded_file:
            context["error"] = "Оберіть GPX-файл для обробки."
        elif not uploaded_file.name.lower().endswith(".gpx"):
            context["error"] = "Файл має бути у форматі .gpx."
        else:
            try:
                result = process_gpx(uploaded_file.read())
            except Exception as exc:
                context["error"] = f"Не вдалося прочитати GPX-файл: {exc}"
            else:
                token = _save_cleaned_file(uploaded_file.name, result["cleaned_bytes"])
                context.update(
                    _track_context(uploaded_file.name, result, token, source="GPX-файл")
                )

    return render(request, "tracks/index.html", context)


def strava_login(request):
    if not _strava_configured():
        return render(
            request,
            "tracks/index.html",
            {
                "error": "Додайте STRAVA_CLIENT_ID і STRAVA_CLIENT_SECRET перед входом у Strava.",
                "strava_configured": False,
            },
        )

    if request.GET.get("reauth"):
        for key in [
            "strava_access_token",
            "strava_refresh_token",
            "strava_expires_at",
            "strava_athlete",
        ]:
            request.session.pop(key, None)

    state = uuid.uuid4().hex
    request.session["strava_oauth_state"] = state
    approval_prompt = "force" if request.GET.get("reauth") else "auto"
    return redirect(
        build_authorization_url(
            settings.STRAVA_CLIENT_ID,
            settings.STRAVA_REDIRECT_URI,
            state,
            approval_prompt=approval_prompt,
        )
    )


def strava_callback(request):
    expected_state = request.session.pop("strava_oauth_state", None)
    if not expected_state or request.GET.get("state") != expected_state:
        return render(
            request,
            "tracks/index.html",
            {
                "error": "Не вдалося підтвердити Strava OAuth state.",
                "strava_configured": _strava_configured(),
            },
        )

    code = request.GET.get("code")
    if not code:
        return render(
            request,
            "tracks/index.html",
            {
                "error": "Strava не повернула authorization code.",
                "strava_configured": _strava_configured(),
            },
        )

    try:
        token_data = exchange_code(
            settings.STRAVA_CLIENT_ID,
            settings.STRAVA_CLIENT_SECRET,
            code,
        )
    except StravaApiError as exc:
        return render(
            request,
            "tracks/index.html",
            {"error": str(exc), "strava_configured": _strava_configured()},
        )

    _store_strava_token(request, token_data)
    return redirect("tracks:strava_activities")


def strava_activities(request):
    access_token = _valid_strava_access_token(request)
    if not access_token:
        return redirect("tracks:strava_login")

    try:
        activities = list_activities(access_token)
    except StravaApiError as exc:
        return render(
            request,
            "tracks/strava_activities.html",
            {"error": str(exc), "activities": []},
        )

    return render(
        request,
        "tracks/strava_activities.html",
        {
            "activities": [_activity_view_model(activity) for activity in activities],
            "athlete": request.session.get("strava_athlete"),
        },
    )


def clean_strava_activity(request, activity_id):
    access_token = _valid_strava_access_token(request)
    if not access_token:
        return redirect("tracks:strava_login")

    try:
        activities = list_activities(access_token, per_page=100)
        activity = next(
            (item for item in activities if int(item["id"]) == int(activity_id)),
            {"id": activity_id, "name": f"Strava activity {activity_id}"},
        )
        activity_detail = get_activity_detail(access_token, activity_id)
        activity.update(activity_detail)
        streams = get_activity_streams(access_token, str(activity_id))
        original_gpx = streams_to_gpx(activity, streams)
        result = process_gpx(original_gpx)
    except (StravaApiError, KeyError, ValueError) as exc:
        return render(
            request,
            "tracks/strava_activities.html",
            {
                "error": f"Не вдалося обробити активність Strava: {exc}",
                "activities": [],
                "athlete": request.session.get("strava_athlete"),
            },
        )

    safe_name = f"strava_{activity_id}.gpx"
    token = _save_cleaned_file(safe_name, result["cleaned_bytes"])
    _remember_strava_upload_metadata(request, token, activity)
    context = {
        "strava_configured": _strava_configured(),
        "strava_athlete": request.session.get("strava_athlete"),
    }
    context.update(
        _track_context(
            activity.get("name") or safe_name,
            result,
            token,
            source="Strava",
        )
    )
    return render(request, "tracks/index.html", context)


def strava_logout(request):
    for key in [
        "strava_access_token",
        "strava_refresh_token",
        "strava_expires_at",
        "strava_athlete",
    ]:
        request.session.pop(key, None)
    return redirect("tracks:index")


def upload_cleaned_to_strava(request, token):
    if request.method != "POST":
        raise Http404("Файл не знайдено.")

    access_token = _valid_strava_access_token(request)
    if not access_token:
        return redirect("tracks:strava_login")

    cleaned_file = _cleaned_file_for_token(token)
    if not cleaned_file:
        raise Http404("Файл не знайдено.")

    upload_metadata = _strava_upload_metadata(request, token, cleaned_file)
    original_activity_id = upload_metadata.get("original_activity_id") or ""
    if original_activity_id and request.POST.get("source_deleted_confirmed") != "1":
        return render(
            request,
            "tracks/strava_upload_confirm.html",
            {
                "token": token,
                "original_activity_id": original_activity_id,
                "original_activity_url": f"https://www.strava.com/activities/{original_activity_id}",
            },
        )

    content = cleaned_file.read_bytes()
    if not original_activity_id:
        content = shift_gpx_times(content, seconds=60)

    try:
        upload_result = upload_gpx_activity(
            access_token=access_token,
            file_name=cleaned_file.name.split("_", 1)[1],
            content=content,
            activity_name=upload_metadata["name"],
            activity_type=upload_metadata["activity_type"],
            description=upload_metadata["description"],
        )
    except StravaApiError as exc:
        return _render_strava_upload_status(request, {"error": str(exc)})

    upload_id = upload_result.get("id")
    status = _poll_strava_upload_status(access_token, upload_id) if upload_id else upload_result
    return _render_strava_upload_status(request, status)


def strava_upload_status(request, upload_id):
    access_token = _valid_strava_access_token(request)
    if not access_token:
        return redirect("tracks:strava_login")

    try:
        status = get_upload_status(access_token, upload_id)
    except StravaApiError as exc:
        status = {"id": upload_id, "error": str(exc)}

    return _render_strava_upload_status(request, status)


def _poll_strava_upload_status(access_token: str, upload_id: int | str) -> dict:
    status: dict = {"id": upload_id, "status": "Upload accepted."}
    for _ in range(6):
        try:
            status = get_upload_status(access_token, upload_id)
        except StravaApiError as exc:
            return {"id": upload_id, "error": str(exc)}

        if status.get("activity_id") or status.get("error"):
            return status
        time.sleep(2)
    return status


def _render_strava_upload_status(request, status: dict):
    activity_id = status.get("activity_id")
    error = status.get("error")
    upload_id = status.get("id") or status.get("id_str")
    message = status.get("status") or "Strava обробляє GPX."

    return render(
        request,
        "tracks/strava_upload_result.html",
        {
            "success": bool(activity_id),
            "processing": bool(upload_id and not activity_id and not error),
            "upload_id": upload_id,
            "activity_id": activity_id,
            "activity_url": f"https://www.strava.com/activities/{activity_id}"
            if activity_id
            else "",
            "message": error or message,
        },
    )


def download_cleaned(request, token):
    if not token.replace("-", "").isalnum():
        raise Http404("Файл не знайдено.")

    cleaned_file = _cleaned_file_for_token(token)
    if not cleaned_file:
        raise Http404("Файл не знайдено.")

    return FileResponse(
        cleaned_file.open("rb"),
        as_attachment=True,
        filename=cleaned_file.name.split("_", 1)[1],
        content_type="application/gpx+xml",
    )


def _save_cleaned_file(original_name: str, content: bytes) -> str:
    token = str(uuid.uuid4())
    safe_name = Path(original_name).name.replace(" ", "_")
    if not safe_name.lower().endswith(".gpx"):
        safe_name = f"{safe_name}.gpx"

    cleaned_dir = Path(settings.MEDIA_ROOT) / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    (cleaned_dir / f"{token}_{safe_name}").write_bytes(content)
    return token


def _cleaned_file_for_token(token: str) -> Path | None:
    if not token.replace("-", "").isalnum():
        return None

    cleaned_dir = Path(settings.MEDIA_ROOT) / "cleaned"
    matches = list(cleaned_dir.glob(f"{token}_*.gpx"))
    return matches[0] if matches else None


def _remember_strava_upload_metadata(request, token: str, activity: dict) -> None:
    request.session[f"cleaned:{token}:strava_upload_metadata"] = {
        "original_activity_id": str(activity.get("id") or ""),
        "name": activity.get("name") or "Strava activity",
        "activity_type": _strava_upload_activity_type(activity),
        "description": activity.get("description") or "",
    }


def _strava_upload_metadata(request, token: str, cleaned_file: Path) -> dict:
    stored_metadata = request.session.get(f"cleaned:{token}:strava_upload_metadata")
    if stored_metadata:
        return stored_metadata

    return {
        "name": cleaned_file.name.split("_", 1)[1].removesuffix(".gpx"),
        "activity_type": "ride",
        "description": "",
        "original_activity_id": "",
    }


def _strava_upload_activity_type(activity: dict) -> str:
    activity_type = activity.get("type") or activity.get("sport_type") or "Ride"
    normalized = str(activity_type).replace("_", "").replace(" ", "").lower()
    aliases = {
        "virtualride": "virtualride",
        "ebikeride": "ebikeride",
        "mountainbikeride": "ride",
        "gravelride": "ride",
        "run": "run",
        "trailrun": "run",
        "walk": "walk",
        "hike": "hike",
        "swim": "swim",
        "workout": "workout",
    }
    return aliases.get(normalized, normalized if normalized else "ride")


def _track_context(file_name: str, result: dict, token: str, source: str) -> dict:
    return {
        "file_name": file_name,
        "source": source,
        "original": result["original"],
        "cleaned": result["cleaned"],
        "original_coordinates": result["original"]["coordinates"],
        "cleaned_coordinates": result["cleaned"]["coordinates"],
        "removed_count": result["removed_count"],
        "original_count": result["original_count"],
        "cleaned_count": result["cleaned_count"],
        "download_token": token,
    }


def _activity_view_model(activity: dict) -> dict:
    distance_km = round(float(activity.get("distance") or 0) / 1000, 2)
    moving_time = _format_seconds(int(activity.get("moving_time") or 0))
    return {
        "id": activity["id"],
        "name": activity.get("name") or "Strava activity",
        "sport_type": activity.get("sport_type") or activity.get("type") or "Activity",
        "start_date_local": activity.get("start_date_local", ""),
        "distance_km": distance_km,
        "moving_time": moving_time,
    }


def _format_seconds(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _strava_configured() -> bool:
    return bool(settings.STRAVA_CLIENT_ID and settings.STRAVA_CLIENT_SECRET)


def _store_strava_token(request, token_data: dict) -> None:
    request.session["strava_access_token"] = token_data["access_token"]
    request.session["strava_refresh_token"] = token_data["refresh_token"]
    request.session["strava_expires_at"] = token_data["expires_at"]
    if token_data.get("athlete"):
        request.session["strava_athlete"] = token_data["athlete"]


def _valid_strava_access_token(request, force_refresh: bool = False) -> str | None:
    access_token = request.session.get("strava_access_token")
    refresh_token_value = request.session.get("strava_refresh_token")
    expires_at = request.session.get("strava_expires_at")

    if not access_token or not refresh_token_value or not expires_at:
        return None

    now = int(datetime.now(tz=timezone.utc).timestamp())
    if not force_refresh and int(expires_at) > now + 60:
        return access_token

    try:
        token_data = refresh_token(
            settings.STRAVA_CLIENT_ID,
            settings.STRAVA_CLIENT_SECRET,
            refresh_token_value,
        )
    except StravaApiError:
        return None

    _store_strava_token(request, token_data)
    return token_data["access_token"]
