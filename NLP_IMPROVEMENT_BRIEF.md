# AI/NLP-модуль проекта

## Цель

AI/NLP-часть не заменяет OSINT-сбор. Ее задача — анализировать уже собранные открытые данные: искать релевантные профили по смыслу, классифицировать их, ранжировать по гибридному баллу и объяснять результат.

## Семантический поиск

Файл `nlp_search_engine.py` использует модель `paraphrase-multilingual-MiniLM-L12-v2`.

Режимы:

- семантический поиск — сравнение запроса с bio профилей по эмбеддингам;
- лексический fallback — TF-IDF-подобный поиск, если модель недоступна;
- гибридный поиск — комбинирует NLP-оценку, OSINT-балл и совпадения терминов.

Гибридная формула:

```text
hybrid_score = semantic_score * 0.70 + osint_boost * 0.20 + match_bonus * 0.10
```

## AI-классификация

Файл `ai_classifier.py` определяет направление профиля:

- `backend`
- `frontend`
- `designer`
- `devops`
- `analyst_security`
- `other`

Если обученная модель отсутствует, используется fallback на правилах: ключевые слова в bio, username, группах и найденных Sherlock-сайтах.

Если модель обучена, используется классификатор `LogisticRegression` поверх sentence-transformer эмбеддингов.

## Обучение модели

Запуск:

```powershell
py -3.12 train_classifier.py
```

Если embedding-модель еще не скачана:

```powershell
py -3.12 train_classifier.py --download-model
```

Скрипт:

1. Загружает профили из SQLite.
2. Формирует обучающий текст из bio, username, групп и OSINT-признаков.
3. Создает weak labels по ключевым словам и найденным внешним аккаунтам.
4. Кодирует тексты через `sentence-transformers`.
5. Обучает `LogisticRegression`.
6. Сохраняет модель в `models/profile_classifier.joblib`.
7. Сохраняет отчет в `models/profile_classifier_report.json`.

## Метрики

В отчет входят:

- accuracy;
- precision, recall, F1 по классам;
- confusion matrix;
- распределение классов;
- примеры обучающих профилей.

## Объяснение результатов

В интерфейсе и поисковой выдаче показываются:

- AI-класс профиля;
- confidence;
- источник результата: `trained` или `rules`;
- совпавшие термины;
- OSINT-признаки, которые повлияли на оценку.

## Почему AI-часть не является слишком простой

Модуль включает не только подключение готовой модели, но и полный ML-пайплайн:

- подготовка датасета;
- слабая разметка профилей;
- обучение классификатора;
- сохранение модели;
- расчет метрик;
- fallback при отсутствии модели;
- интеграция результата в интерфейс и гибридное ранжирование.

## Identity matching / account verification

Дополнительно реализован модуль проверки найденных аккаунтов: `identity_matcher.py`.
Он решает задачу User Identity Linkage: Telegram-профиль и найденный Sherlock/Snoop URL сравниваются как пара, после чего система выдает вероятность, что это один и тот же человек.

Признаки модели:

- сходство Telegram username и username из найденного URL;
- точное совпадение username;
- риск коллизии коротких или общих ников;
- тип сайта и надежность источника `sherlock`/`snoop`;
- пересечение слов из Telegram bio с URL/названием сайта;
- качество URL и похожесть имени, если внешние метаданные есть в датасете.

Workflow обучения:

```powershell
py -3.12 train_identity_matcher.py --export-candidates identity_pairs.csv
```

После этого аналитик вручную размечает колонку `label`: `1` — тот же человек, `0` — другой человек.

```powershell
py -3.12 train_identity_matcher.py --labels identity_pairs.csv
```

Результаты сохраняются в `models/identity_matcher.joblib` и `models/identity_matcher_report.json`.
Если модель еще не обучена, используется explainable scoring без падения приложения.
