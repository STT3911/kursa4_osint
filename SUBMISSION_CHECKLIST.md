# Чеклист сдачи

## Готово

- [x] Исходный код desktop-приложения.
- [x] Локальная SQLite-база для демонстрации.
- [x] CSV-выгрузки: baseline, enriched и OSINT-report.
- [x] OSINT-обогащение через Sherlock, опционально Snoop и ручной Maigret.
- [x] NLP-поиск и гибридное ранжирование.
- [x] AI-классификация профилей.
- [x] Identity matching для найденных внешних аккаунтов.
- [x] README с установкой и запуском.
- [x] Итоговый текстовый отчет `COURSEWORK_REPORT.md`.
- [x] Сценарий защиты `DEMO_GUIDE.md`.
- [x] Smoke-тесты ядра анализа.
- [x] Секреты и session-файлы исключены из проекта.

## Перед отправкой преподавателю

- [ ] Вставить ФИО, группу, преподавателя и год на титульный лист DOCX.
- [ ] При необходимости заменить учебную тему на формулировку из методички.
- [ ] Проверить, что локальный `.env` не попадает в архив.
- [ ] Проверить, что `osint_session.session` не попадает в архив.
- [ ] Запустить smoke-тесты.
- [ ] Открыть `COURSEWORK_REPORT.docx` и быстро просмотреть страницы.
- [ ] Запустить приложение и пройти сценарий из `DEMO_GUIDE.md`.

## Рекомендуемый состав архива

- исходники `.py`;
- `requirements.txt`;
- `.env.example`;
- `README.md`;
- `COURSEWORK_REPORT.md`;
- `COURSEWORK_REPORT.docx`;
- `DEMO_GUIDE.md`;
- `SUBMISSION_CHECKLIST.md`;
- `THIRD_PARTY_NOTICES.md`;
- `models/identity_matcher.joblib`;
- `models/identity_matcher_report.json`;
- демонстрационные CSV/DB-файлы, если это разрешено требованиями кафедры.

## Не включать в архив

- `.env`;
- `*.session`;
- `__pycache__/`;
- `.venv/`;
- `*.db-journal`;
- runtime-базы;
- smoke-песочницы;
- backup-файлы.
