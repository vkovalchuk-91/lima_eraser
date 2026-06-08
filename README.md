# GPX Eraser

Django-додаток для автоматичного очищення GPX-треків від координатних аномалій, зокрема стрибків, спричинених спотворенням GPS/РЕБ.

## Запуск

```powershell
. .\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Після запуску відкрийте http://127.0.0.1:8000/ і оберіть `.gpx` файл. Карти побудуються автоматично.

## Запуск через Docker Compose

Перед першим запуском створіть `.env` із прикладу й заповніть Strava-ключі, якщо потрібна інтеграція зі Strava:

```powershell
Copy-Item .env.example .env
```

Запустіть додаток:

```powershell
docker compose up --build
```

Після запуску відкрийте http://127.0.0.1:8000/. SQLite-база зберігається в `docker-data`, а очищені GPX-файли — у `media`.

Для запуску за доменом через nginx додайте в `.env`:

```text
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=lima-eraser.pp.ua,www.lima-eraser.pp.ua,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://lima-eraser.pp.ua,https://www.lima-eraser.pp.ua,http://lima-eraser.pp.ua,http://www.lima-eraser.pp.ua
STRAVA_REDIRECT_URI=https://lima-eraser.pp.ua/strava/callback/
```

У nginx для production додайте окрему роздачу static/media перед proxy:

```nginx
location /static/ {
    alias /home/slengpack/lima_eraser/staticfiles/;
}

location /media/ {
    alias /home/slengpack/lima_eraser/media/;
}
```

## Встановлення з нуля

```powershell
py -3.12 -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Strava

Щоб обирати треки зі Strava, створіть застосунок у Strava Developers і додайте callback URL:

```text
http://127.0.0.1:8000/strava/callback/
```

Іконка для Strava API Application готова тут:

```text
tracks/static/tracks/icons/strava_app_icon.png
```

Перед запуском створіть `.env` поруч із `manage.py`:

```powershell
Copy-Item .env.example .env
```

Заповніть значення:

```text
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
STRAVA_REDIRECT_URI=http://127.0.0.1:8000/strava/callback/
```

Після цього запустіть сервер:

```powershell
python manage.py runserver
```

На головній сторінці натисніть "Увійти через Strava", після авторизації оберіть активність і натисніть "Очистити".
Очищений GPX можна завантажити назад у Strava кнопкою "Завантажити в Strava".
Для треків, обраних зі Strava, перед завантаженням очищеної активності додаток попросить вручну видалити оригінальну неочищену активність, щоб Strava не відхилила upload як дублікат.
Для треків, обраних зі Strava, новий upload використовує ту саму назву, тип активності й опис.
Якщо ви авторизувалися до появи цієї кнопки, вийдіть зі Strava в додатку й увійдіть знову, щоб надати дозвіл `activity:write`.

## Алгоритм

Очищення виконується у три етапи:

1. Пошук основного географічного кластера треку через робастний центр і IQR-поріг, щоб прибрати далекі телепорти координат.
2. Видалення одиничних GPS-стрибків, де швидкість до та після точки нереалістична, а прямий перехід між сусідніми точками виглядає правдоподібним.
3. Пошук локальних аномальних відхилень: якщо трек різко відходить убік від маршруту і швидко повертається назад, видаляється весь проміжок між двома опорними точками.

На прикладі `Morning_Ride (11).gpx` алгоритм зменшує дистанцію з `24742.16 км` до `97.81 км`.
