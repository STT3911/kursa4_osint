# Локальная OSINT-система для анализа Telegram-профилей

Курсовая работа . Программа собирает открытые данные о пользователях Telegram,
ищет их аккаунты на других площадках и анализирует профили средствами NLP и
машинного обучения. Всё считается локально: профили хранятся в SQLite, модели
запускаются на машине пользователя, никакие данные наружу не отправляются.

**Тема:** Разработка локальной OSINT-системы для сбора открытых данных о
пользователях Telegram, поиска их внешних цифровых следов и интеллектуального
анализа профилей с помощью NLP/AI.

**Автор:** Turaev_S_23, группа СДП-КБ-231.

## Возможности

- Сбор профилей из Telegram-групп и по прямой ссылке (Telethon).
- Поиск аккаунтов на других сайтах через Sherlock, Snoop и Maigret.
- Подсчёт osint_score и уровня цифрового следа для каждого профиля.
- Семантический и гибридный поиск по собранным профилям
  (sentence-transformers + TF-IDF).
- Классификация профиля по роли (backend, frontend, дизайнер, devops,
  аналитик/безопасность) и оценка «один ли это человек» для найденных аккаунтов.
- Граф связей между профилями: общие группы, общие площадки, пересылки и ответы,
  плюс поиск подозрительных бот-сетей.
- Telegram-бот, который умеет показывать связи профиля прямо в мессенджере.
- Выгрузка отчётов в CSV и Markdown.

Интерфейсов три: десктопное окно на Tkinter, веб-страница на Streamlit и
Telegram-бот.

## Требования

- Python 3.10 или новее
- pip
- Windows, Linux или macOS

Для сбора данных понадобятся `api_id` и `api_hash` с https://my.telegram.org.
Для бота нужен токен от @BotFather.

## Как запустить

1. Склонировать репозиторий:

   ```
   git clone <ссылка-на-репозиторий>
   cd kursa4_osint
   ```

2. Создать виртуальное окружение и поставить зависимости.

   Windows:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

   Linux / macOS:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Создать файл `.env` из шаблона и вписать свои ключи:

   ```
   copy .env.example .env      # Windows
   cp .env.example .env        # Linux / macOS
   ```

   Обязательно заполнить `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`. Если нужен бот,
   добавить `OSINT_BOT_TOKEN` и список разрешённых Telegram-ID в
   `OSINT_BOT_ALLOWED_USERS`.

4. Запустить:

   ```
   python run.py
   ```

   `run.py` открывает десктопное приложение и, если задан токен, поднимает
   Telegram-бота. На Windows можно просто дважды кликнуть по `start.bat`,
   на Linux/macOS запустить `./start.sh`.

При первом запуске Telethon попросит подтвердить вход в Telegram (код из
приложения). После этого появится файл сессии `osint_session.session` — он в
репозиторий не добавляется.

### Другие способы запуска

- Только десктоп: `python app.py`
- Веб-интерфейс: `streamlit run streamlit_app.py`
- Только бот: `python osint_bot.py`
- Сбор из группы через консоль: `python parser.py --group <имя_группы> --limit 200`

## Структура проекта

| Файл / папка | Назначение |
|---|---|
| `app.py` | десктопный интерфейс (Tkinter) |
| `streamlit_app.py` | веб-интерфейс |
| `osint_bot.py` | Telegram-бот с анализом графа связей |
| `run.py` | общий запуск десктопа и бота |
| `telegram_service.py` | сбор профилей через Telethon |
| `sherlock_integration.py`, `snoop_integration.py`, `maigret_integration.py` | поиск аккаунтов на внешних площадках |
| `database.py` | работа с SQLite и экспорт отчётов |
| `nlp_search_engine.py` | семантический и лексический поиск |
| `ai_classifier.py` | классификация профилей |
| `identity_matcher.py` | оценка совпадения личности |
| `link_graph.py` | построение и анализ графа |
| `security_analyzer.py` | оценка угроз, OPSEC и аномалий |
| `train_classifier.py`, `train_identity_matcher.py` | обучение моделей |
| `tests/` | юнит-тесты |

## Тесты

```
python -m unittest discover -s tests
```

## Примечания

Проект учебный и работает только с открытыми данными. Файл `.env` с ключами,
файл сессии Telegram и собранные датасеты в репозиторий не попадают (см.
`.gitignore`).
