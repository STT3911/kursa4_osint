# Чеклист перед сдачей

## Код

- [x] Desktop-интерфейс `app.py`.
- [x] Веб-витрина `streamlit_app.py`.
- [x] SQLite-слой `database.py`.
- [x] Telegram-сбор.
- [x] Sherlock/Snoop/Maigret интеграции.
- [x] NLP-поиск.
- [x] AI-классификатор.
- [x] Identity matching.
- [x] Unit-тесты.

## Документация

- [x] `README.md`.
- [x] `COURSEWORK_REPORT.md`.
- [x] `COURSEWORK_REPORT.docx`.
- [x] `CYBERSECURITY_PART.md`.
- [x] `AI_PART.md`.
- [x] `DEMO_GUIDE.md`.
- [x] `HANDOFF_WITHOUT_GITHUB.md`.
- [x] `THIRD_PARTY_NOTICES.md`.

## Модели и данные

- [x] `models/profile_classifier.joblib`.
- [x] `models/profile_classifier_report.json`.
- [x] `models/identity_matcher.joblib`.
- [x] `models/identity_matcher_report.json`.
- [x] `osint_database.db`.
- [x] `nlp_dataset.csv`.
- [x] `nlp_dataset_enriched.csv`.
- [x] `osint_report.csv`.
- [x] `identity_pairs.csv`.

## Не класть в архив

- [ ] `.venv/`.
- [ ] `.git/`.
- [ ] `.env`.
- [ ] `*.session`.
- [ ] `__pycache__/`.
- [ ] `.smoke_*`.
- [ ] `.docx_render/`.
- [ ] `*.db-journal`.

## Проверка

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

