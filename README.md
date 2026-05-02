# OSINT Desktop

Локальное desktop-приложение для курсовой работы по сбору и анализу открытых данных из Telegram. Проект разделен на две равнозначные части: OSINT-сбор и AI/NLP-анализ.

## Возможности

- Сбор открытых профилей из Telegram-групп через `Telethon`.
- Realtime-проверка одного Telegram-профиля по `@username`, ссылке `t.me/...` или user id.
- Сохранение профилей, связей с группами и статусов проверок в `SQLite`.
- Интеграция `Sherlock` для поиска внешних аккаунтов по username.
- Расчет `osint_score` и уровня цифрового следа.
- Семантический и гибридный NLP-поиск по профилям.
- AI-классификация профилей: `backend`, `frontend`, `designer`, `devops`, `analyst_security`, `other`.
- Обучение классификатора поверх эмбеддингов `sentence-transformers` с отчетом по метрикам.
- Экспорт baseline/enriched CSV, OSINT-отчетов и Markdown-сводки для курсовой.

## Установка

```powershell
py -3.12 -m pip install -r requirements.txt
```

Для работы Telegram-сбора нужны переменные окружения:

```powershell
$env:TELEGRAM_API_ID="your_api_id"
$env:TELEGRAM_API_HASH="your_api_hash"
$env:TELEGRAM_SESSION="osint_session"
```

## Запуск

Графический интерфейс:

```powershell
py -3.12 app.py
```

CLI-сценарии:

```powershell
py -3.12 parser.py --group rabota_chaty1 --limit 100
py -3.12 ai_search.py
py -3.12 exp_csv.py
py -3.12 con_db.py
```

Обучение AI-классификатора:

```powershell
py -3.12 train_classifier.py
```

Если модель эмбеддингов еще не скачана локально:

```powershell
py -3.12 train_classifier.py --download-model
```

После обучения артефакты сохраняются в `models/`:

- `profile_classifier.joblib` — обученный классификатор;
- `profile_classifier_report.json` — accuracy, classification report, confusion matrix и примеры.

## Демонстрационный сценарий

1. Запустить `app.py`.
2. Во вкладке сбора указать Telegram API ID/API Hash.
3. Собрать группу или выполнить realtime-проверку одного профиля.
4. Дождаться проверки Sherlock по username.
5. Открыть карточку профиля: посмотреть Telegram-данные, внешние аккаунты, OSINT-балл и AI-классификацию.
6. Во вкладке NLP-поиска выполнить запросы `python backend`, `figma designer`, `devops`, `osint analyst`.
7. Сравнить семантический и гибридный режимы.
8. Экспортировать enriched dataset, OSINT-report и Markdown-сводку.

## Основные файлы

- `app.py` — основной Tkinter-интерфейс.
- `telegram_service.py` — сбор групп и realtime-проверка отдельных Telegram-профилей.
- `sherlock_integration.py` — запуск Sherlock и разбор найденных аккаунтов.
- `database.py` — SQLite-схема, аналитика, отчеты и CSV-экспорт.
- `nlp_search_engine.py` — семантический и гибридный поиск.
- `ai_classifier.py` — AI-классификация профилей и fallback-правила.
- `train_classifier.py` — обучение классификатора и расчет метрик.
- `COURSEWORK_STRUCTURE.md` — разделение работы между участниками.
- `NLP_IMPROVEMENT_BRIEF.md` — описание AI/NLP-части.

## Разделение частей

OSINT-часть отвечает за сбор, хранение и обогащение открытых данных: Telegram, Sherlock, цифровой след, отчеты.

AI/NLP-часть отвечает за анализ собранных данных: семантический поиск, гибридное ранжирование, классификацию, обучение модели, метрики и объяснение результатов.
