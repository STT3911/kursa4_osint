# OSINT + AI Coursework

Локальная система для учебного анализа открытых данных Telegram-профилей. Проект разделен на две части разработки:

1. **Кибербезопасность и OSINT** - сбор открытых данных, хранение, обогащение внешними аккаунтами, оценка цифрового следа.
2. **Искусственный интеллект и NLP** - семантический поиск, классификация профилей, проверка принадлежности найденных аккаунтов.

## Состав проекта

### Часть 1. Кибербезопасность и OSINT

- сбор открытых Telegram-профилей через `Telethon`;
- локальная база `SQLite`;
- сохранение групп, bio, username, аватаров и статусов проверок;
- username-enrichment через `Sherlock`, опциональный `Snoop` и ручной `Maigret`;
- расчет `osint_score` и уровня цифрового следа;
- экспорт CSV и Markdown-отчетов;
- меры безопасности: `.env`, session-файлы и реальные API-ключи не входят в архив.

Подробно: [CYBERSECURITY_PART.md](CYBERSECURITY_PART.md).

### Часть 2. Искусственный интеллект и NLP

- семантический и гибридный поиск по профилям;
- fallback-поиск без embedding-модели;
- AI-классификация профилей по профессиональным направлениям;
- обученная модель `models/profile_classifier.joblib`;
- identity matching для оценки, может ли внешний аккаунт принадлежать тому же человеку;
- обученная модель `models/identity_matcher.joblib`;
- отчеты с метриками в `models/*.json`.

Подробно: [AI_PART.md](AI_PART.md).

## Основные файлы

- `app.py` - основной desktop-интерфейс.
- `streamlit_app.py` - демонстрационная веб-витрина для защиты.
- `telegram_service.py` - Telegram-сбор и realtime-проверка профилей.
- `database.py` - SQLite-схема, аналитика, экспорт и карточки профилей.
- `sherlock_integration.py` - запуск Sherlock.
- `snoop_integration.py` - опциональный запуск Snoop.
- `maigret_integration.py` - ручная углубленная проверка Maigret.
- `nlp_search_engine.py` - семантический и гибридный поиск.
- `ai_classifier.py` - AI-классификация и fallback-правила.
- `identity_matcher.py` - модель same-person matching.
- `train_classifier.py` - обучение классификатора профилей.
- `train_identity_matcher.py` - обучение модели identity matching.
- `auto_label_identity_pairs.py` - weak-разметка пар для identity matching.

## Установка

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Для live-сбора Telegram нужен локальный `.env`:

```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION=osint_session
```

В архив и репозиторий `.env` и `*.session` не кладутся.

## Запуск

Desktop-приложение:

```powershell
.\.venv\Scripts\python.exe app.py
```

Веб-витрина:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8502
```

Обучение моделей:

```powershell
.\.venv\Scripts\python.exe train_classifier.py --download-model
.\.venv\Scripts\python.exe train_identity_matcher.py --labels identity_pairs.csv
```

## Проверка

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Передача без GitHub

Инструкция по ZIP-архиву лежит в [HANDOFF_WITHOUT_GITHUB.md](HANDOFF_WITHOUT_GITHUB.md).

