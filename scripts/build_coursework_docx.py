from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = BASE_DIR / "COURSEWORK_REPORT.docx"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    tc_pr.append(shading)


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Calibri"
    run.font.size = Pt(10)


def add_table(document: Document, headers: list[str], rows: list[list[str]]) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_cell_text(cell, header, bold=True)
        set_cell_shading(cell, "D9EAF7")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            set_cell_text(cells[index], value)
            cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    document.add_paragraph()


def add_bullets(document: Document, items: list[str]) -> None:
    for item in items:
        document.add_paragraph(item, style="List Bullet")


def configure_document(document: Document) -> None:
    section = document.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(11)
    styles["Normal"].paragraph_format.line_spacing = 1.15
    styles["Normal"].paragraph_format.space_after = Pt(6)

    for style_name, size, color in (
        ("Title", 20, RGBColor(31, 78, 121)),
        ("Heading 1", 15, RGBColor(31, 78, 121)),
        ("Heading 2", 13, RGBColor(46, 116, 181)),
    ):
        style = styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = color


def build() -> None:
    document = Document()
    configure_document(document)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("КУРСОВАЯ РАБОТА")
    run.bold = True
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor(31, 78, 121)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Локальная система кибербезопасности и искусственного интеллекта для OSINT-анализа Telegram-профилей"
    )
    run.font.size = Pt(14)

    document.add_paragraph()
    add_table(
        document,
        ["Поле", "Значение"],
        [
            ["Студент", "____________________________"],
            ["Группа", "____________________________"],
            ["Преподаватель", "____________________________"],
            ["Год", "2026"],
        ],
    )

    document.add_page_break()

    document.add_heading("Аннотация", level=1)
    document.add_paragraph(
        "В работе разработана локальная система, которая объединяет две части: кибербезопасность/OSINT "
        "и искусственный интеллект/NLP. Первая часть собирает открытые Telegram-данные, хранит их в SQLite "
        "и обогащает внешними цифровыми следами через Sherlock, Snoop и Maigret. Вторая часть выполняет "
        "семантический поиск, классификацию профилей и проверку принадлежности найденных аккаунтов тому же человеку."
    )

    document.add_heading("Цель и задачи", level=1)
    document.add_paragraph(
        "Цель работы - создать прикладную систему для локального сбора, хранения, OSINT-обогащения "
        "и AI/NLP-анализа открытых данных Telegram-профилей."
    )
    add_bullets(
        document,
        [
            "реализовать сбор открытых Telegram-профилей;",
            "организовать локальное хранение в SQLite;",
            "добавить Sherlock/Snoop/Maigret username-enrichment;",
            "рассчитать OSINT-балл и уровень цифрового следа;",
            "реализовать семантический и гибридный поиск;",
            "обучить baseline-классификатор профилей;",
            "обучить модель identity matching для внешних аккаунтов;",
            "подготовить интерфейс, демонстрацию и экспорт отчетов.",
        ],
    )

    document.add_heading("Разделение разработки", level=1)
    add_table(
        document,
        ["Часть", "Назначение", "Файлы"],
        [
            [
                "Кибербезопасность и OSINT",
                "Сбор, хранение, enrichment, оценка цифрового следа",
                "telegram_service.py, database.py, sherlock_integration.py, snoop_integration.py, maigret_integration.py",
            ],
            [
                "Искусственный интеллект и NLP",
                "Поиск, классификация, same-person scoring",
                "nlp_search_engine.py, ai_classifier.py, identity_matcher.py, train_classifier.py",
            ],
        ],
    )

    document.add_heading("Часть 1. Кибербезопасность и OSINT", level=1)
    document.add_paragraph(
        "OSINT-часть получает открытые поля Telegram-профилей, сохраняет связи пользователь-группа, "
        "ищет внешние аккаунты по username и формирует оценку цифрового следа."
    )
    add_bullets(
        document,
        [
            "сбор Telegram-профилей через Telethon;",
            "локальное хранение без внешнего сервера;",
            "очереди Sherlock и Snoop;",
            "ручная глубокая проверка Maigret;",
            "сохранение источника найденного аккаунта;",
            "расчет osint_score и exposure_level;",
            "экспорт CSV и Markdown-отчетов.",
        ],
    )

    document.add_heading("Часть 2. Искусственный интеллект и NLP", level=1)
    document.add_paragraph(
        "AI/NLP-часть анализирует собранные данные: ищет профили по смыслу, классифицирует направление "
        "профиля и оценивает вероятность того, что найденный внешний аккаунт принадлежит тому же человеку."
    )
    add_bullets(
        document,
        [
            "семантический поиск на sentence-transformers;",
            "гибридное ранжирование с учетом OSINT-балла;",
            "baseline-классификация профилей;",
            "модель identity matching на признаках username, URL, источника и риска коллизии;",
            "отчеты с метриками качества в models/*.json.",
        ],
    )

    document.add_heading("Артефакты", level=1)
    add_table(
        document,
        ["Тип", "Файлы"],
        [
            ["Данные", "osint_database.db, nlp_dataset.csv, nlp_dataset_enriched.csv, osint_report.csv"],
            ["Модели", "models/profile_classifier.joblib, models/identity_matcher.joblib"],
            ["Отчеты моделей", "models/profile_classifier_report.json, models/identity_matcher_report.json"],
            ["Документация", "README.md, CYBERSECURITY_PART.md, AI_PART.md, DEMO_GUIDE.md"],
        ],
    )

    document.add_heading("Безопасность и ограничения", level=1)
    add_bullets(
        document,
        [
            "реальные Telegram API-ключи не хранятся в проекте;",
            "session-файлы не передаются;",
            "совпадение username не доказывает личность;",
            "baseline-классификатор требует расширения ручной разметки;",
            "проект предназначен для учебного анализа открытых данных.",
        ],
    )

    document.add_heading("Проверка", level=1)
    document.add_paragraph(
        "Минимальная проверка выполняется командой: .\\.venv\\Scripts\\python.exe -m unittest discover -s tests. "
        "Демонстрация проводится через app.py и streamlit_app.py."
    )

    document.add_heading("Вывод", level=1)
    document.add_paragraph(
        "Проект доведен до состояния демонстрационной курсовой работы: реализована часть кибербезопасности/OSINT "
        "и часть искусственного интеллекта/NLP, подготовлены модели, данные, интерфейсы, тесты и документация."
    )

    for section in document.sections:
        footer = section.footer.paragraphs[0]
        footer.text = "OSINT + AI coursework"
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER

    document.save(OUTPUT_PATH)


if __name__ == "__main__":
    build()

