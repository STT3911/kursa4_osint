# OSINT Desktop

Локальное desktop-приложение для курсовой работы по сбору и анализу открытых данных из Telegram. Проект разделен на две равнозначные части: OSINT-сбор и AI/NLP-анализ.

## Возможности

- Сбор открытых профилей из Telegram-групп через `Telethon`.
- Realtime-проверка одного Telegram-профиля по `@username`, ссылке `t.me/...` или user id.
- Сохранение профилей, связей с группами и статусов проверок в `SQLite`.
- Интеграция `Sherlock` для поиска внешних аккаунтов по username.
- Опциональная интеграция `Snoop` как второго инструмента username-enrichment.
- Интеграция `Maigret` для ручной углубленной проверки username по большому набору площадок.
- Расчет `osint_score` и уровня цифрового следа.
- Семантический и гибридный NLP-поиск по профилям.
- AI-классификация профилей: `backend`, `frontend`, `designer`, `devops`, `analyst_security`, `other`.
- Обучение классификатора поверх эмбеддингов `sentence-transformers` с отчетом по метрикам.
- Экспорт baseline/enriched CSV, OSINT-отчетов и Markdown-сводки.

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

Также поддерживаются короткие алиасы `TG_API_ID` и `TG_API_HASH`.

Можно не задавать переменные вручную, а заполнить локальный файл `.env` в корне проекта:

```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION=osint_session
```

Файл `.env` добавлен в `.gitignore`, поэтому реальные ключи не должны попадать в репозиторий. Шаблон лежит в `.env.example`.

## Опциональная установка Snoop

Snoop не хранится в репозитории проекта. Рекомендуемый вариант:

```powershell
git clone https://github.com/snooppr/snoop tools/snoop
.\.venv\Scripts\python.exe -m pip install -r tools\snoop\requirements.txt
```

Альтернативно можно указать путь к Snoop через переменную окружения:

```powershell
$env:SNOOP_DIR="D:\path\to\snoop"
```

Если Snoop не установлен, приложение продолжит работать с Sherlock, Telegram и AI/NLP.

## Maigret

`Maigret` установлен через `requirements.txt` и используется как ручная углубленная проверка выбранного профиля. Такой режим выбран специально: массовый запуск Maigret по всей базе может занимать много времени и создавать лишнюю сетевую нагрузку, а для защиты курсовой достаточно показать проверку на конкретной карточке профиля.

## Запуск

Графический интерфейс:

```powershell
py -3.12 app.py
```

Веб-дашборд для демонстрации аналитики:

```powershell
streamlit run streamlit_app.py
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

## Identity matching model

Этот AI-модуль оценивает, принадлежит ли найденный Sherlock/Snoop/Maigret аккаунт тому же человеку, что и Telegram-профиль. Для каждого внешнего аккаунта считается `same-person score`, verdict и объяснение.

Экспорт кандидатов для ручной разметки:

```powershell
py -3.12 train_identity_matcher.py --export-candidates identity_pairs.csv
```

В файле `identity_pairs.csv` нужно заполнить колонку `label`:

- `1` — аккаунт принадлежит тому же человеку;
- `0` — аккаунт принадлежит другому человеку.

Если ручной разметки мало, можно добавить осторожную weak-разметку:

```powershell
py -3.12 auto_label_identity_pairs.py --input identity_pairs.csv --synthetic-negatives 100
```

Скрипт не перезаписывает ручные метки, делает backup `identity_pairs.csv.bak`, заполняет только уверенные пустые строки и добавляет синтетические отрицательные пары для баланса классов.

Обучение модели:

```powershell
py -3.12 train_identity_matcher.py --labels identity_pairs.csv
```

Артефакты сохраняются в `models/`:

- `identity_matcher.joblib` — модель account matching;
- `identity_matcher_report.json` — accuracy, precision, recall, F1, ROC-AUC, confusion matrix.

Если обученной модели нет, приложение использует explainable scoring по признакам: сходство username, риск коллизии коротких ников, источник Sherlock/Snoop/Maigret, тип сайта, пересечение bio и URL.

## Демонстрационный сценарий

1. Запустить `app.py` или `streamlit run streamlit_app.py`.
2. Во вкладке сбора проверить, что Telegram API ID/API Hash подтянулись из env, или ввести их вручную.
3. Собрать группу или выполнить realtime-проверку одного профиля.
4. Дождаться проверки Sherlock и, если установлен, Snoop по username.
5. Открыть карточку профиля и запустить Maigret для ручной углубленной проверки username.
6. Посмотреть Telegram-данные, внешние аккаунты, источники `sherlock`/`snoop`/`maigret`, OSINT-балл и AI-классификацию.
7. Во вкладке NLP-поиска выполнить запросы `python backend`, `figma designer`, `devops`, `osint analyst`.
8. Сравнить семантический и гибридный режимы.
9. Экспортировать enriched dataset, OSINT-report и Markdown-сводку.

## Основные файлы

- `app.py` — основной Tkinter-интерфейс.
- `streamlit_app.py` — веб-дашборд для демонстрации аналитики и профилей.
- `telegram_service.py` — сбор групп и realtime-проверка отдельных Telegram-профилей.
- `sherlock_integration.py` — запуск Sherlock и разбор найденных аккаунтов.
- `snoop_integration.py` — опциональный запуск Snoop и разбор CSV-отчетов.
- `maigret_integration.py` — запуск Maigret и разбор CSV/JSON-отчетов.
- `database.py` — SQLite-схема, аналитика, отчеты и CSV-экспорт.
- `nlp_search_engine.py` — семантический и гибридный поиск.
- `ai_classifier.py` — AI-классификация профилей и fallback-правила.
- `train_classifier.py` — обучение классификатора и расчет метрик.
- `identity_matcher.py` — оценка, найден ли аккаунт того же человека или возможная коллизия username.
- `train_identity_matcher.py` — экспорт пар для разметки и обучение модели same-person matching.
- `auto_label_identity_pairs.py` — осторожная weak-разметка и генерация синтетических отрицательных пар.
- `COURSEWORK_STRUCTURE.md` — разделение работы между участниками.
- `COURSEWORK_REPORT.md` — итоговый текст отчета по курсовой.
- `COURSEWORK_REPORT.docx` — оформленная версия отчета для сдачи.
- `DEMO_GUIDE.md` — сценарий демонстрации проекта на защите.
- `SUBMISSION_CHECKLIST.md` — чеклист перед отправкой архива.
- `NLP_IMPROVEMENT_BRIEF.md` — описание AI/NLP-части.

## Проверка

Минимальные smoke-тесты ядра анализа:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Перед сдачей не добавляйте в архив `.env`, `*.session`, `.venv/`, `__pycache__/`, `*.db-journal` и runtime-базы.

## Разделение частей

OSINT-часть отвечает за сбор, хранение и обогащение открытых данных: Telegram, Sherlock, Snoop, Maigret, цифровой след, отчеты.

AI/NLP-часть отвечает за анализ собранных данных: семантический поиск, гибридное ранжирование, классификацию, обучение модели, метрики и объяснение результатов.
