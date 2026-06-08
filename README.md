# Lima Eraser

Додаток для очищення GPX-треків від координатних аномалій: GPS-стрибків, "телепортів" та локальних нелогічних відхилень маршруту. Додаток може працювати з локальними `.gpx` файлами або з активностями Strava через OAuth.

Ця інструкція описує локальний запуск через Docker: від встановлення Docker Desktop і створення власного Strava API Application до запуску сайту на `http://127.0.0.1:8000/`.

## Можливості

- Завантаження GPX-файлу з комп'ютера й автоматичне очищення треку.
- Порівняння оригінального й очищеного маршруту на карті.
- Вхід через Strava, вибір активності зі списку й очищення її GPX.
- Завантаження очищеного GPX назад у Strava.

## Вимоги

- Windows 10/11, macOS або Linux.
- Git.
- Docker Desktop з Docker Compose.
- Обліковий запис Strava, якщо потрібна інтеграція зі Strava.

Python локально встановлювати не потрібно, якщо запускаєте додаток через Docker.

## 1. Встановіть Docker

### Windows

1. Завантажте Docker Desktop: https://www.docker.com/products/docker-desktop/
2. Встановіть Docker Desktop.
3. Під час встановлення погодьтеся на використання WSL 2, якщо інсталятор це запропонує.
4. Перезавантажте комп'ютер, якщо Docker попросить.
5. Запустіть Docker Desktop і дочекайтеся статусу `Docker Desktop is running`.

Перевірте встановлення в PowerShell:

```powershell
docker --version
docker compose version
```

Якщо команда `docker compose version` не працює, оновіть Docker Desktop до актуальної версії.

### macOS або Linux

Встановіть Docker за офіційною інструкцією для вашої системи:

```text
https://docs.docker.com/get-docker/
```

Після встановлення перевірте:

```bash
docker --version
docker compose version
```

## 2. Отримайте код проєкту

Склонуйте репозиторій або відкрийте папку з уже завантаженим проєктом:

```powershell
git clone https://github.com/vkovalchuk-91/lima_eraser.git
cd lima_eraser
```

Якщо проєкт уже є на комп'ютері, просто перейдіть у його папку:

```powershell
cd C:\Users\vkovalchuk\Desktop\lima_eraser
```

## 3. Створіть Strava API Application

Цей крок потрібен для входу через Strava, вибору активностей зі Strava та завантаження очищеного GPX назад у Strava.

1. Відкрийте https://www.strava.com/settings/api
2. Увійдіть у свій Strava-акаунт.
3. Створіть API Application або відкрийте вже існуючий.
4. Заповніть основні поля:
   - `Application Name`: будь-яка назва, наприклад `Lima Eraser Local`
   - `Category`: можна вибрати `Data Importer` або найближчу доступну категорію
   - `Club`: можна залишити порожнім
   - `Website`: `http://127.0.0.1:8000/`
   - `Application Description`: короткий опис, наприклад `Local GPX cleaner`
   - `Authorization Callback Domain`: `127.0.0.1`
5. Збережіть застосунок.
6. Скопіюйте `Client ID` і `Client Secret`.

Для іконки застосунку можна використати файл з репозиторію:

```text
tracks/static/tracks/icons/strava_app_icon.png
```

Важливо: у полі `Authorization Callback Domain` у Strava вказується тільки домен `127.0.0.1`, без `http://`, порту й шляху.

## 4. Створіть `.env`

У корені проєкту створіть файл `.env` з прикладу:

```powershell
Copy-Item .env.example .env
```

Відкрийте `.env` і заповніть Strava-ключі:

```env
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,testserver
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000

STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
STRAVA_REDIRECT_URI=http://127.0.0.1:8000/strava/callback/
```

Замініть:

- `your_client_id` на `Client ID` зі Strava.
- `your_client_secret` на `Client Secret` зі Strava.

Для локального запуску `STRAVA_REDIRECT_URI` має залишатися саме таким:

```text
http://127.0.0.1:8000/strava/callback/
```

Файл `.env` містить секрети, тому його не потрібно комітити в Git.

## 5. Запустіть додаток локально

Переконайтеся, що Docker Desktop запущений, і виконайте:

```powershell
docker compose up --build
```

Під час першого запуску Docker:

- збере образ додатка;
- встановить Python-залежності;
- застосує міграції Django;
- збере static-файли;
- запустить сервер на порту `8000`.

Після запуску відкрийте:

```text
http://127.0.0.1:8000/
```

Щоб зупинити додаток, натисніть `Ctrl+C` у терміналі.

Для запуску у фоновому режимі:

```powershell
docker compose up --build -d
```

Щоб зупинити фоновий запуск:

```powershell
docker compose down
```

## 6. Як користуватися

### Очищення локального GPX

1. Відкрийте `http://127.0.0.1:8000/`.
2. Оберіть `.gpx` файл.
3. Дочекайтеся обробки.
4. Порівняйте оригінальний та очищений маршрут на карті.
5. Завантажте очищений GPX.

### Очищення активності зі Strava

1. Натисніть `Увійти через Strava`.
2. Дозвольте доступ до активностей.
3. Оберіть активність зі списку.
4. Натисніть `Очистити`.
5. За потреби завантажте очищений GPX назад у Strava.

Перед завантаженням очищеної активності назад у Strava додаток попросить вручну видалити оригінальну неочищену активність. Це потрібно, щоб Strava не відхилила upload як дублікат.

Якщо ви раніше авторизували додаток без дозволу `activity:write`, вийдіть зі Strava в додатку й увійдіть знову, щоб надати дозвіл на завантаження активностей.

## Де зберігаються дані

Під час Docker-запуску локальні дані зберігаються в папках проєкту:

- `docker-data` - SQLite-база даних.
- `media` - завантажені та очищені GPX-файли.
- `staticfiles` - зібрані static-файли Django.

Ці папки можна видалити, якщо потрібно повністю очистити локальний стан додатка.

## Корисні команди

Переглянути логи:

```powershell
docker compose logs -f web
```

Перезапустити додаток:

```powershell
docker compose restart web
```

Перебудувати образ після змін у коді:

```powershell
docker compose up --build
```

Виконати Django-тести в контейнері:

```powershell
docker compose run --rm web python manage.py test
```

Відкрити shell у контейнері:

```powershell
docker compose run --rm web sh
```

## Типові проблеми

### Docker не запускається

Переконайтеся, що Docker Desktop відкритий і має статус `Docker Desktop is running`. На Windows також перевірте, що увімкнений WSL 2.

### Порт 8000 уже зайнятий

Зупиніть інший процес, який використовує порт `8000`, або змініть порт у `docker-compose.yml`:

```yaml
ports:
  - "8001:8000"
```

Після цього відкривайте `http://127.0.0.1:8001/`.

Якщо використовуєте інтеграцію зі Strava на іншому порту, оновіть `STRAVA_REDIRECT_URI` у `.env` і callback URL відповідно до нового порту.

### Strava показує помилку авторизації

Перевірте три значення:

- У Strava `Authorization Callback Domain` має бути `127.0.0.1`.
- У `.env` має бути `STRAVA_REDIRECT_URI=http://127.0.0.1:8000/strava/callback/`.
- Сайт потрібно відкривати через `http://127.0.0.1:8000/`, а не через інший домен.

### Не працює завантаження очищеного GPX у Strava

Перевірте, що після авторизації ви надали дозвіл `activity:write`. Якщо ні, вийдіть зі Strava в додатку й авторизуйтеся знову.

Також Strava може відхилити upload як дублікат, якщо оригінальна активність ще існує. Перед завантаженням очищеної версії видаліть оригінал вручну в Strava.

## Алгоритм очищення

Очищення виконується в кілька етапів:

1. Пошук основного географічного кластера треку через робастний центр і IQR-поріг.
2. Видалення одиничних GPS-стрибків, де швидкість до та після точки нереалістична.
3. Пошук локальних аномальних відхилень, коли трек різко відходить убік і повертається назад.
4. Додатковий пошук великих стрибків у GPX без timestamp-ів, де швидкість неможливо порахувати.
