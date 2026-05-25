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

> **Важно:** всегда запускать через `.venv\Scripts\python.exe`, иначе Sherlock и Snoop не найдут свои зависимости.

Для работы Telegram-сбора нужны переменные окружения:

```powershell
$env:TELEGRAM_API_ID="your_api_id"
$env:TELEGRAM_API_HASH="your_api_hash"
$env:TELEGRAM_SESSION="osint_session"
```

Также поддерживаются короткие алиасы `TG_API_ID` и `TG_API_HASH`.

Можно не задавать переменные вручную, а заполнить локальный файл `.env` в корне проекта:

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

## Identity matching model

Этот AI-модуль оценивает, принадлежит ли найденный Sherlock/Snoop аккаунт тому же человеку, что и Telegram-профиль. Для каждого внешнего аккаунта считается `same-person score`, verdict и объяснение.

Экспорт кандидатов для ручной разметки:

```powershell
.venv\Scripts\python.exe train_identity_matcher.py --export-candidates identity_pairs.csv
```

В файле `identity_pairs.csv` нужно заполнить колонку `label`:

- `1` — аккаунт принадлежит тому же человеку;
- `0` — аккаунт принадлежит другому человеку.

Если ручной разметки мало, можно добавить осторожную weak-разметку:

```powershell
.venv\Scripts\python.exe auto_label_identity_pairs.py --input identity_pairs.csv --synthetic-negatives 100
```

Скрипт не перезаписывает ручные метки, делает backup `identity_pairs.csv.bak`, заполняет только уверенные пустые строки и добавляет синтетические отрицательные пары для баланса классов.

Обучение модели:

```powershell
.venv\Scripts\python.exe train_identity_matcher.py --labels identity_pairs.csv
```

Артефакты сохраняются в `models/`:

- `identity_matcher.joblib` — модель account matching;
- `identity_matcher_report.json` — accuracy, precision, recall, F1, ROC-AUC, confusion matrix.

Если обученной модели нет, приложение использует explainable scoring по признакам: сходство username, риск коллизии коротких ников, источник Sherlock/Snoop, тип сайта, пересечение bio и URL.

## Демонстрационный сценарий

1. Запустить `app.py`.
2. Во вкладке сбора проверить, что Telegram API ID/API Hash подтянулись из env, или ввести их вручную.
3. Собрать группу или выполнить realtime-проверку одного профиля.
4. Дождаться проверки Sherlock и, если установлен, Snoop по username.
5. Открыть карточку профиля: посмотреть Telegram-данные, внешние аккаунты, источники `sherlock`/`snoop`, OSINT-балл и AI-классификацию.
6. Во вкладке NLP-поиска выполнить запросы `python backend`, `figma designer`, `devops`, `osint analyst`.
7. Сравнить семантический и гибридный режимы.
8. Экспортировать enriched dataset, OSINT-report и Markdown-сводку.

## Основные файлы

- `app.py` — основной Tkinter-интерфейс.
- `telegram_service.py` — сбор групп и realtime-проверка отдельных Telegram-профилей.
- `sherlock_integration.py` — запуск Sherlock и разбор найденных аккаунтов.
- `snoop_integration.py` — опциональный запуск Snoop и разбор CSV-отчетов.
- `database.py` — SQLite-схема, аналитика, отчеты и CSV-экспорт.
- `nlp_search_engine.py` — семантический и гибридный поиск.
- `ai_classifier.py` — AI-классификация профилей и fallback-правила.
- `train_classifier.py` — обучение классификатора и расчет метрик.
- `identity_matcher.py` — оценка, найден ли аккаунт того же человека или возможная коллизия username.
- `train_identity_matcher.py` — экспорт пар для разметки и обучение модели same-person matching.
- `auto_label_identity_pairs.py` — осторожная weak-разметка и генерация синтетических отрицательных пар.
- `COURSEWORK_STRUCTURE.md` — разделение работы между участниками.
- `NLP_IMPROVEMENT_BRIEF.md` — описание AI/NLP-части.

## Кибербезопасность

Вкладка **«Кибербезопасность»** реализует:

- **Угрозный профайлинг** — детектирование ключевых слов из категорий `high / medium / analyst` с контекстным окном ±55 символов для подавления ложных срабатываний («защита от фишинга» ≠ фишинг).
- **OPSEC-балл (0–100)** — оценка цифрового следа: Privacy-инструменты (Tor, VPN), открытые PII (телефон, email, IP в bio), количество внешних аккаунтов.
- **Детекция аномалий** — клоны с похожими username, аномальное число аккаунтов у одного профиля.
- **Детекция ботов и координированного поведения** — regex-паттерны bot-username, поиск prefix-семей (≥3 аккаунтов с общим 4-буквенным префиксом).
- **Граф связей** (`link_graph.py`, networkx) — ребра по общим Telegram-группам (вес 1) и доверенным сайтам (вес 2), метрики центральности, мосты, поиск бот-кластеров.
- **Экспорт security-отчёта** — Markdown с методологией, топ угроз, аномалиями и координированным поведением.

Обновить анализ и открыть граф можно кнопками в шапке вкладки. Для визуализации графа требуется `networkx` (входит в `requirements.txt`).

## Разделение частей

OSINT-часть отвечает за сбор, хранение и обогащение открытых данных: Telegram, Sherlock, Snoop, цифровой след, отчеты.

AI/NLP-часть отвечает за анализ собранных данных: семантический поиск, гибридное ранжирование, классификацию, обучение модели, метрики и объяснение результатов.

Кибербезопасность-часть отвечает за оценку угроз, OPSEC-профайлинг, детекцию ботов и координированного поведения, граф связей профилей.
