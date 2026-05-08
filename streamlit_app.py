from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

import database
from maigret_integration import is_maigret_available, process_maigret_check
from nlp_search_engine import NLPSearchEngine
from sherlock_integration import is_sherlock_available, process_username_check
from telegram_service import TelegramCollector


PAGE_OPTIONS = [
    "Главная",
    "Сбор данных",
    "OSINT-анализ",
    "NLP-поиск",
    "Карточка профиля",
    "Экспорт и отчеты",
]


def configure_page() -> None:
    st.set_page_config(
        page_title="OSINT Dashboard",
        page_icon="OSINT",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
            :root {
                --bg: #080d12;
                --surface: #101820;
                --surface-alt: #14212b;
                --line: #263846;
                --text: #e7f2f3;
                --muted: #8fa9b2;
                --primary: #46f0a7;
                --accent: #47c7ff;
                --warning: #ffc857;
                --danger: #ff6b6b;
                --shadow: 0 16px 40px rgba(0, 0, 0, 0.28);
                --radius: 8px;
            }
            .stApp {
                background: var(--bg);
                color: var(--text);
            }
            .block-container {
                padding-top: 1.25rem;
                padding-bottom: 2rem;
                max-width: 1360px;
            }
            [data-testid="stSidebar"] {
                background: #0c131a;
                border-right: 1px solid var(--line);
            }
            [data-testid="stSidebar"] * {
                color: var(--text);
            }
            h1, h2, h3, h4, h5, h6, p, li, label, span, div {
                color: var(--text);
            }
            .stMarkdown, .stCaption, .stDataFrame, .stTable {
                color: var(--text);
            }
            .stAlert {
                background: #102331;
                border: 1px solid #24465c;
                color: var(--text);
            }
            .hero {
                padding: 1rem 1.1rem;
                border-radius: var(--radius);
                background: #0f171f;
                border: 1px solid var(--line);
                box-shadow: var(--shadow);
                margin-bottom: 1rem;
                position: relative;
            }
            .hero h1 {
                margin: 0;
                font-size: 1.55rem;
                letter-spacing: 0;
                font-family: Consolas, "Courier New", monospace;
                color: var(--primary);
            }
            .hero p {
                margin: 0.4rem 0 0 0;
                color: var(--muted);
                font-family: Consolas, "Courier New", monospace;
            }
            .hero::before {
                content: "LIVE LOCAL INSTANCE";
                position: absolute;
                right: 1rem;
                top: 1rem;
                color: #07110d;
                background: var(--primary);
                border-radius: 4px;
                padding: 0.18rem 0.45rem;
                font-size: 0.72rem;
                font-weight: 700;
            }
            .metric-card {
                background: var(--surface);
                border: 1px solid var(--line);
                box-shadow: var(--shadow);
                border-radius: var(--radius);
                padding: 0.9rem 1rem;
                min-height: 104px;
            }
            .metric-label {
                color: var(--muted);
                font-size: 0.78rem;
                text-transform: uppercase;
                letter-spacing: 0;
                font-family: Consolas, "Courier New", monospace;
            }
            .metric-value {
                margin-top: 0.28rem;
                font-size: 1.8rem;
                font-weight: 700;
                color: var(--primary);
                font-family: Consolas, "Courier New", monospace;
            }
            .metric-note {
                margin-top: 0.2rem;
                color: var(--muted);
                font-size: 0.86rem;
            }
            .section-card {
                background: var(--surface);
                border: 1px solid var(--line);
                box-shadow: var(--shadow);
                border-radius: var(--radius);
                padding: 0.9rem 1rem;
                margin-bottom: 1rem;
                font-family: Consolas, "Courier New", monospace;
            }
            .profile-card {
                background: var(--surface);
                border: 1px solid var(--line);
                box-shadow: var(--shadow);
                border-radius: var(--radius);
                padding: 1rem 1.1rem;
                margin-bottom: 0.85rem;
            }
            .badge {
                display: inline-block;
                padding: 0.22rem 0.55rem;
                border-radius: 4px;
                font-size: 0.78rem;
                font-weight: 600;
                margin-right: 0.35rem;
                margin-bottom: 0.35rem;
                font-family: Consolas, "Courier New", monospace;
            }
            .badge-exposure-high, .badge-confidence-probable, .badge-review-confirmed {
                background: rgba(70, 240, 167, 0.14);
                color: var(--primary);
                border: 1px solid rgba(70, 240, 167, 0.35);
            }
            .badge-exposure-medium, .badge-confidence-weak, .badge-review-pending {
                background: rgba(255, 200, 87, 0.14);
                color: var(--warning);
                border: 1px solid rgba(255, 200, 87, 0.35);
            }
            .badge-exposure-low, .badge-confidence-unverified, .badge-review-rejected {
                background: rgba(255, 107, 107, 0.12);
                color: var(--danger);
                border: 1px solid rgba(255, 107, 107, 0.35);
            }
            .tiny-note {
                color: var(--muted);
                font-size: 0.9rem;
            }
            div[data-testid="stButton"] > button,
            div[data-testid="stDownloadButton"] > button {
                background: #132531;
                color: var(--text);
                border: 1px solid #315064;
                border-radius: 6px;
                font-weight: 600;
            }
            div[data-testid="stButton"] > button:hover,
            div[data-testid="stDownloadButton"] > button:hover {
                border-color: var(--primary);
                color: var(--primary);
            }
            input, textarea, select {
                background: #0d151c !important;
                color: var(--text) !important;
                border-color: var(--line) !important;
            }
            [data-testid="stDataFrame"] {
                border: 1px solid var(--line);
                border-radius: var(--radius);
                overflow: hidden;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def invalidate_views() -> None:
    st.cache_data.clear()
    get_search_engine().invalidate()


def format_exposure(value: str) -> str:
    mapping = {"high": "высокий", "medium": "средний", "low": "низкий"}
    return mapping.get(value or "", value or "-")


def format_confidence(value: str) -> str:
    mapping = {"probable": "вероятно", "weak": "слабое совпадение", "unverified": "не подтверждено"}
    return mapping.get(value or "", value or "-")


def format_review(value: str) -> str:
    mapping = {"pending": "ожидает проверки", "confirmed": "подтверждено вручную", "rejected": "отклонено"}
    return mapping.get(value or "", value or "-")


def exposure_badge(value: str) -> str:
    label = format_exposure(value)
    return f"<span class='badge badge-exposure-{value}'>{label}</span>"


def confidence_badge(value: str) -> str:
    label = format_confidence(value)
    return f"<span class='badge badge-confidence-{value}'>{label}</span>"


def review_badge(value: str) -> str:
    label = format_review(value)
    return f"<span class='badge badge-review-{value}'>{label}</span>"


def dataframe_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def local_photo_path(photo_path: str) -> str | None:
    if not photo_path:
        return None
    absolute = (Path(__file__).resolve().parent / photo_path).resolve()
    if not absolute.exists():
        return None
    return str(absolute)


def build_osint_breakdown(profile: dict[str, Any]) -> list[str]:
    username_points = 15 if profile.get("username") else 0
    bio_points = 20 if profile.get("bio") else 0
    photo_points = 10 if profile.get("has_photo") else 0
    bio_length = int(profile.get("bio_length") or 0)
    if bio_length >= 120:
        bio_depth_points = 15
    elif bio_length >= 40:
        bio_depth_points = 10
    elif bio_length > 0:
        bio_depth_points = 5
    else:
        bio_depth_points = 0
    group_points = min(int(profile.get("group_count") or 0) * 10, 25)
    social_points = min(int(profile.get("site_count") or 0) * 15, 30)
    return [
        f"Username найден: +{username_points}",
        f"Bio заполнено: +{bio_points}",
        f"Информативность bio ({bio_length} символов): +{bio_depth_points}",
        f"Аватар сохранен: +{photo_points}",
        f"Связи с Telegram-группами ({profile.get('group_count', 0)}): +{group_points}",
        f"Внешние аккаунты Sherlock/Snoop/Maigret ({profile.get('site_count', 0)}): +{social_points}",
        f"Итог: {profile.get('osint_score', 0)}/100, уровень: {format_exposure(str(profile.get('exposure_level') or ''))}",
    ]


@st.cache_resource
def get_search_engine() -> NLPSearchEngine:
    return NLPSearchEngine()


@st.cache_data
def load_dashboard_stats() -> dict[str, Any]:
    database.init_db()
    return database.get_dashboard_stats()


@st.cache_data
def load_analytics_snapshot() -> dict[str, Any]:
    database.init_db()
    return database.get_analytics_snapshot()


@st.cache_data
def load_osint_snapshot() -> dict[str, Any]:
    database.init_db()
    return database.get_osint_analysis_snapshot()


@st.cache_data
def load_profile_index(limit: int = 5000) -> list[dict[str, Any]]:
    database.init_db()
    return database.list_profiles_summary(limit=limit)


@st.cache_data
def load_profile_card(user_id: int) -> dict[str, Any]:
    database.init_db()
    return database.get_profile_card(user_id)


@st.cache_data
def load_latest_sherlock_log(user_id: int) -> dict[str, Any] | None:
    database.init_db()
    return database.get_latest_sherlock_log(user_id)


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>&gt; OSINT://TELEGRAM-INTEL</h1>
            <p>local console · Telegram profiles · Sherlock/Snoop/Maigret enrichment · AI/NLP analysis</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_console_figure(fig, height: int = 340, showlegend: bool | None = None):
    layout_args: dict[str, Any] = {
        "height": height,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "#0d151c",
        "font": {"color": "#e7f2f3", "family": "Consolas, Courier New, monospace"},
        "margin": dict(l=10, r=10, t=10, b=10),
        "xaxis": {
            "gridcolor": "#263846",
            "zerolinecolor": "#263846",
            "linecolor": "#263846",
            "tickfont": {"color": "#c4d5da"},
            "title_font": {"color": "#e7f2f3"},
        },
        "yaxis": {
            "gridcolor": "#263846",
            "zerolinecolor": "#263846",
            "linecolor": "#263846",
            "tickfont": {"color": "#c4d5da"},
            "title_font": {"color": "#e7f2f3"},
        },
        "legend": {"font": {"color": "#c4d5da"}},
    }
    if showlegend is not None:
        layout_args["showlegend"] = showlegend
    fig.update_layout(**layout_args)
    return fig


def open_profile(user_id: int) -> None:
    st.session_state["selected_profile_id"] = int(user_id)
    st.session_state["pending_nav_page"] = "Карточка профиля"


def show_enrichment_result(result: dict[str, Any]) -> None:
    status = result.get("status")
    message = str(result.get("message") or "Проверка завершена.")
    if status == "done":
        st.success(message)
    elif status == "skipped":
        st.warning(message)
    else:
        st.error(message)


def show_enrichment_flash() -> None:
    flash = st.session_state.pop("enrichment_flash", None)
    if isinstance(flash, dict):
        show_enrichment_result(flash)


def run_maigret_enrichment(user_id: int, username: str) -> None:
    with st.spinner("Выполняется Maigret-обогащение..."):
        result = process_maigret_check(user_id, username)
        invalidate_views()
        st.session_state["enrichment_flash"] = result


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## Навигация")
        if "nav_page" not in st.session_state:
            st.session_state["nav_page"] = "Главная"
        pending_nav_page = st.session_state.pop("pending_nav_page", None)
        if pending_nav_page in PAGE_OPTIONS:
            st.session_state["nav_page"] = pending_nav_page
        selected_page = st.radio(
            "Раздел",
            PAGE_OPTIONS,
            index=PAGE_OPTIONS.index(st.session_state["nav_page"]),
            key="nav_page",
        )
        st.markdown("---")
        st.caption("Интерфейс Streamlit используется как основная витрина для защиты курсовой.")
        return selected_page


def render_main_page() -> None:
    stats = load_dashboard_stats()
    analytics = load_analytics_snapshot()
    osint_snapshot = load_osint_snapshot()
    totals = analytics["totals"]

    cols = st.columns(4)
    with cols[0]:
        render_metric_card("Профили", str(totals.get("profiles", 0)), "Всего профилей в базе")
    with cols[1]:
        render_metric_card("Bio", str(totals.get("with_bio", 0)), "Профили с описанием")
    with cols[2]:
        completed_tools = (
            int(stats.get("completed_checks", 0) or 0)
            + int(stats.get("completed_snoop_checks", 0) or 0)
            + int(stats.get("completed_maigret_checks", 0) or 0)
        )
        render_metric_card("Enrichment", str(completed_tools), "Проверок завершено")
    with cols[3]:
        render_metric_card("Внешние аккаунты", str(stats.get("social_accounts", 0)), "Связей с площадками")

    sherlock_status = "доступен" if is_sherlock_available() else "не установлен"
    maigret_status = "доступен" if is_maigret_available() else "не установлен"
    st.markdown(
        "<div class='section-card'>"
        f"<strong>Состояние инструментов:</strong> Sherlock: {sherlock_status}; Maigret: {maigret_status}"
        "</div>",
        unsafe_allow_html=True,
    )

    chart_cols = st.columns(3)
    with chart_cols[0]:
        df = dataframe_from_rows(analytics["top_groups"])
        st.markdown("### Топ Telegram-групп")
        if not df.empty:
            fig = px.bar(
                df.head(8),
                x="count_value",
                y="group_name",
                orientation="h",
                color="count_value",
                color_continuous_scale=["#14212b", "#46f0a7"],
                labels={"count_value": "профили", "group_name": "группа"},
            )
            style_console_figure(fig)
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Нет данных по группам.")
    with chart_cols[1]:
        levels = analytics["exposure_levels"]
        df = pd.DataFrame({"Уровень": [format_exposure(k) for k in levels], "Количество": list(levels.values())})
        st.markdown("### Уровни цифрового следа")
        fig = px.bar(
            df,
            x="Уровень",
            y="Количество",
            color="Уровень",
            color_discrete_sequence=["#46f0a7", "#ffc857", "#ff6b6b"],
        )
        style_console_figure(fig, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with chart_cols[2]:
        df = dataframe_from_rows(analytics.get("confidence_levels", []))
        st.markdown("### Достоверность аккаунтов")
        if not df.empty:
            df["label"] = df["label"].map(format_confidence)
            fig = px.pie(
                df,
                names="label",
                values="count_value",
                hole=0.55,
                color="label",
                color_discrete_sequence=["#46f0a7", "#ffc857", "#ff6b6b"],
                labels={"label": "уровень", "count_value": "аккаунты"},
            )
            style_console_figure(fig, showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Сначала выполните Sherlock-проверки.")

    st.markdown("### Топ профилей по OSINT-оценке")
    for row in osint_snapshot["top_profiles"][:5]:
        username = f"@{row['username']}" if row.get("username") else "[скрыт]"
        with st.container():
            st.markdown("<div class='profile-card'>", unsafe_allow_html=True)
            meta_cols = st.columns([5, 2])
            with meta_cols[0]:
                st.markdown(f"**{row.get('first_name') or 'Пользователь'}**  \n{username}")
                st.markdown(
                    exposure_badge(str(row.get("exposure_level") or ""))
                    + confidence_badge("probable" if int(row.get("probable_accounts_count") or 0) else "unverified"),
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"OSINT: {row.get('osint_score', 0)} | групп: {row.get('group_count', 0)} | внешних аккаунтов: {row.get('site_count', 0)}"
                )
            with meta_cols[1]:
                if st.button("Открыть профиль", key=f"home-open-{row['user_id']}"):
                    open_profile(int(row["user_id"]))
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)


def render_collection_page() -> None:
    st.markdown("## Сбор данных из Telegram")
    st.caption("Интерфейс использует существующий backend и после сбора сразу запускает обработку очереди Sherlock.")

    with st.form("collect_form"):
        col1, col2 = st.columns(2)
        with col1:
            api_id = st.text_input("API ID", value=os.getenv("TELEGRAM_API_ID", ""))
            session_name = st.text_input("Session", value=os.getenv("TELEGRAM_SESSION", "osint_session"))
            group_name = st.text_input("Группа", value="rabota_chaty1")
        with col2:
            api_hash = st.text_input("API Hash", value=os.getenv("TELEGRAM_API_HASH", ""), type="password")
            limit_new_users = st.number_input("Лимит новых профилей", min_value=1, max_value=5000, value=100, step=10)
        submit = st.form_submit_button("Запустить сбор")

    log_placeholder = st.empty()
    progress_placeholder = st.empty()

    if submit:
        collector = TelegramCollector(api_id=api_id, api_hash=api_hash, session_name=session_name)
        logs: list[str] = []

        def callback(event: dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            if event_type == "log":
                logs.append(str(event.get("message") or ""))
            elif event_type == "error":
                logs.append(f"ОШИБКА: {event.get('message')}")
            elif event_type == "completed":
                stats = event.get("stats") or {}
                logs.append(
                    "Сбор завершен: "
                    f"новых={stats.get('new_profiles', 0)} "
                    f"существующих={stats.get('existing_profiles', 0)} "
                    f"в очереди Sherlock={stats.get('queued_usernames', 0)}"
                )
            current_stats = database.get_dashboard_stats()
            progress_placeholder.info(
                "Профилей: {profiles} | в очереди Sherlock: {queued} | проверок завершено: {done}".format(
                    profiles=current_stats.get("profiles", 0),
                    queued=current_stats.get("queued_checks", 0),
                    done=current_stats.get("completed_checks", 0),
                )
            )
            log_placeholder.code("\n".join(logs[-50:]), language="text")

        with st.spinner("Сбор данных и обработка очереди Sherlock..."):
            try:
                asyncio.run(
                    collector.collect_group(
                        group_name=group_name.strip().lstrip("@"),
                        limit_new_users=int(limit_new_users),
                        event_callback=callback,
                    )
                )
                pending = database.list_pending_username_checks(limit=1000)
                for index, item in enumerate(pending, start=1):
                    result = process_username_check(int(item["user_id"]), str(item["username"]))
                    logs.append(f"[{index}/{len(pending)}] {result['message']}")
                    current_stats = database.get_dashboard_stats()
                    progress_placeholder.info(
                        f"Обработка Sherlock: {index}/{len(pending)} | найдено аккаунтов: {current_stats.get('social_accounts', 0)}"
                    )
                    log_placeholder.code("\n".join(logs[-50:]), language="text")
                invalidate_views()
                st.success("Сбор и обработка завершены.")
            except Exception as exc:
                st.error(f"Не удалось завершить сбор данных: {exc}")

    stats = load_dashboard_stats()
    cols = st.columns(4)
    cols[0].metric("Профилей", stats.get("profiles", 0))
    cols[1].metric("В очереди Sherlock", stats.get("queued_checks", 0))
    cols[2].metric("В очереди Maigret", stats.get("queued_maigret_checks", 0))
    cols[3].metric("Внешних аккаунтов", stats.get("social_accounts", 0))


def render_osint_page() -> None:
    st.markdown("## OSINT-анализ")
    show_enrichment_flash()
    snapshot = load_osint_snapshot()
    profiles = load_profile_index(limit=5000)

    col1, col2 = st.columns(2)
    with col1:
        exposure_filter = st.selectbox("Уровень цифрового следа", ["all", "high", "medium", "low"], format_func=lambda x: "любой" if x == "all" else format_exposure(x))
    with col2:
        min_sites = st.slider("Минимум внешних аккаунтов", min_value=0, max_value=20, value=0)

    filtered_profiles = []
    for row in profiles:
        if exposure_filter != "all" and row.get("exposure_level") != exposure_filter:
            continue
        if int(row.get("site_count") or 0) < min_sites:
            continue
        filtered_profiles.append(row)

    st.markdown("### Рейтинг профилей")
    rating_rows = []
    for row in filtered_profiles[:30]:
        rating_rows.append(
            {
                "user_id": row["user_id"],
                "Имя": row.get("first_name") or "",
                "Username": f"@{row['username']}" if row.get("username") else "[скрыт]",
                "OSINT": row.get("osint_score", 0),
                "Уровень": format_exposure(str(row.get("exposure_level") or "")),
                "Группы": row.get("group_count", 0),
                "Сайты": row.get("site_count", 0),
                "Макс. confidence": row.get("max_confidence_score", 0),
            }
        )
    st.dataframe(pd.DataFrame(rating_rows), use_container_width=True, hide_index=True)

    if filtered_profiles:
        chosen_user_id = st.selectbox(
            "Открыть профиль из рейтинга",
            [int(item["user_id"]) for item in filtered_profiles[:100]],
            format_func=lambda uid: next(
                (
                    f"{row.get('first_name') or 'Пользователь'} (@{row.get('username') or 'скрыт'})"
                    for row in filtered_profiles
                    if int(row["user_id"]) == uid
                ),
                str(uid),
            ),
        )
        chosen_profile = next(
            (row for row in filtered_profiles if int(row["user_id"]) == int(chosen_user_id)),
            {},
        )
        action_cols = st.columns(2)
        if action_cols[0].button("Перейти в карточку профиля", key="osint-open-profile", use_container_width=True):
            open_profile(int(chosen_user_id))
            st.rerun()
        username = str(chosen_profile.get("username") or "").strip()
        maigret_disabled = not username or not is_maigret_available()
        if action_cols[1].button(
            "Обогатить через Maigret",
            key="osint-maigret-enrich",
            use_container_width=True,
            disabled=maigret_disabled,
            help="Запускает Maigret по username и сохраняет найденные внешние аккаунты в карточку профиля.",
        ):
            run_maigret_enrichment(int(chosen_user_id), username)
            st.rerun()
        if not username:
            st.caption("Maigret недоступен для выбранного профиля: нет username.")
        elif not is_maigret_available():
            st.caption("Maigret не установлен в текущем окружении.")

    table_cols = st.columns(2)
    with table_cols[0]:
        st.markdown("### Telegram-группы")
        st.dataframe(pd.DataFrame(snapshot["group_stats"]), use_container_width=True, hide_index=True)
    with table_cols[1]:
        st.markdown("### Пересечения групп")
        overlap_rows = snapshot["group_overlaps"]
        if overlap_rows:
            st.dataframe(pd.DataFrame(overlap_rows), use_container_width=True, hide_index=True)
        else:
            st.info("На текущем датасете пересечения групп не обнаружены.")


def run_search(mode_key: str, query: str, min_osint: int, exposure_filter: str, username_only: bool) -> tuple[list[dict[str, Any]], str]:
    engine = get_search_engine()
    if mode_key == "hybrid":
        raw_results = engine.search_hybrid(query, top_k=100)
    else:
        raw_results = engine.search(query, top_k=100)

    filtered_results = []
    for row in raw_results:
        if int(row.get("osint_score") or 0) < min_osint:
            continue
        if exposure_filter != "all" and row.get("exposure_level") != exposure_filter:
            continue
        if username_only and not row.get("username"):
            continue
        filtered_results.append(row)

    if not filtered_results:
        summary = f"Запрос: {query} | режим: {'Гибридный' if mode_key == 'hybrid' else 'Семантический'} | после фильтров: 0"
    else:
        top = filtered_results[0]
        summary = (
            f"Запрос: {query} | режим: {'Гибридный' if mode_key == 'hybrid' else 'Семантический'} | "
            f"кандидатов: {len(raw_results)} | после фильтров: {len(filtered_results)} | "
            f"лучший профиль: @{top.get('username') or 'скрыт'} | "
            f"NLP={top.get('score', 0):.2f}, гибрид={top.get('hybrid_score', 0):.2f}, "
            f"OSINT={top.get('osint_score', 0)}, совпадения={top.get('matched_terms') or '-'}"
        )
    return filtered_results, summary


def render_search_page() -> None:
    st.markdown("## NLP-поиск")

    query = st.text_input("Поисковый запрос", value=st.session_state.get("search_query", ""))
    cols = st.columns([1.2, 1, 1, 1])
    with cols[0]:
        mode_label = st.radio("Режим поиска", ["Семантический", "Гибридный"], horizontal=True)
    with cols[1]:
        min_osint = st.slider("Мин. OSINT-балл", min_value=0, max_value=100, value=0, step=5)
    with cols[2]:
        exposure_filter = st.selectbox("Уровень следа", ["all", "high", "medium", "low"], format_func=lambda x: "любой" if x == "all" else format_exposure(x))
    with cols[3]:
        username_only = st.checkbox("Только с username", value=False)

    action_cols = st.columns(2)
    if action_cols[0].button("Искать", use_container_width=True):
        mode_key = "hybrid" if mode_label == "Гибридный" else "semantic"
        results, summary = run_search(mode_key, query, min_osint, exposure_filter, username_only)
        st.session_state["search_query"] = query
        st.session_state["search_results"] = results
        st.session_state["search_summary"] = summary
        st.session_state["search_compare"] = ""
        st.rerun()

    if action_cols[1].button("Сравнить режимы", use_container_width=True):
        engine = get_search_engine()
        comparison = engine.compare_search_modes(query, top_k=15)
        base_results, _ = run_search("semantic", query, min_osint, exposure_filter, username_only)
        hybrid_results, summary = run_search("hybrid", query, min_osint, exposure_filter, username_only)
        st.session_state["search_query"] = query
        st.session_state["search_results"] = hybrid_results
        st.session_state["search_summary"] = summary
        st.session_state["search_compare"] = (
            f"Сравнение режимов | движок={comparison['backend']} | "
            f"базовая выдача={len(base_results)} | гибридная выдача={len(hybrid_results)} | "
            f"общих профилей={comparison['overlap_count']} | новых в гибриде={comparison['changed_count']}"
        )
        st.rerun()

    if st.session_state.get("search_summary"):
        st.info(st.session_state["search_summary"])
    if st.session_state.get("search_compare"):
        st.caption(st.session_state["search_compare"])

    results = st.session_state.get("search_results", [])
    if results:
        export_rows = pd.DataFrame(results[:25])
        st.download_button(
            "Скачать текущую выдачу в CSV",
            data=export_rows.to_csv(sep=";", index=False).encode("utf-8-sig"),
            file_name="streamlit_search_results.csv",
            mime="text/csv",
        )

    for result in results[:15]:
        username = f"@{result['username']}" if result.get("username") else "[скрыт]"
        st.markdown("<div class='profile-card'>", unsafe_allow_html=True)
        upper = st.columns([5, 2])
        with upper[0]:
            st.markdown(f"**{result.get('first_name') or 'Пользователь'}**  \n{username}")
            st.markdown(
                exposure_badge(str(result.get("exposure_level") or ""))
                + confidence_badge("probable" if int(result.get("max_confidence_score") or 0) >= 70 else "weak" if int(result.get("max_confidence_score") or 0) >= 40 else "unverified"),
                unsafe_allow_html=True,
            )
            st.caption(
                f"NLP={result.get('score', 0):.2f} | hybrid={result.get('hybrid_score', 0):.2f} | "
                f"OSINT={result.get('osint_score', 0)} | groups={result.get('group_count', 0)} | sites={result.get('site_count', 0)}"
            )
        with upper[1]:
            if st.button("Карточка профиля", key=f"search-open-{result['user_id']}"):
                open_profile(int(result["user_id"]))
                st.rerun()
        st.write(result.get("bio") or "Bio отсутствует.")
        if result.get("matched_terms"):
            st.caption(f"Совпавшие термины: {result['matched_terms']}")
        if result.get("site_list"):
            st.caption(f"Площадки: {result['site_list']}")
        st.markdown("</div>", unsafe_allow_html=True)


def render_profile_page() -> None:
    st.markdown("## Карточка профиля")
    show_enrichment_flash()
    profiles = load_profile_index(limit=5000)
    if not profiles:
        st.warning("В базе пока нет профилей.")
        return

    default_user_id = int(st.session_state.get("selected_profile_id") or profiles[0]["user_id"])
    profile_map = {int(row["user_id"]): row for row in profiles}
    if default_user_id not in profile_map:
        default_user_id = int(profiles[0]["user_id"])

    selected_user_id = st.selectbox(
        "Выберите профиль",
        [int(row["user_id"]) for row in profiles[:1000]],
        index=[int(row["user_id"]) for row in profiles[:1000]].index(default_user_id),
        format_func=lambda uid: (
            f"{profile_map[uid].get('first_name') or 'Пользователь'} "
            f"(@{profile_map[uid].get('username') or 'скрыт'}) | OSINT {profile_map[uid].get('osint_score', 0)}"
        ),
    )
    st.session_state["selected_profile_id"] = int(selected_user_id)

    data = load_profile_card(int(selected_user_id))
    profile = data["profile"]
    latest_log = load_latest_sherlock_log(int(selected_user_id))

    top_cols = st.columns([1.1, 2.2])
    with top_cols[0]:
        image_path = local_photo_path(str(profile.get("photo_path") or ""))
        if image_path:
            st.image(image_path, use_container_width=True)
        else:
            st.info("Аватар недоступен")
    with top_cols[1]:
        username = f"@{profile['username']}" if profile.get("username") else "[скрыт]"
        st.markdown(f"### {profile.get('first_name') or 'Пользователь'}")
        st.markdown(f"**Username:** {username}")
        st.markdown(exposure_badge(str(profile.get("exposure_level") or "")), unsafe_allow_html=True)
        st.caption(
            f"OSINT-балл: {profile.get('osint_score', 0)} | групп: {profile.get('group_count', 0)} | "
            f"внешних аккаунтов: {profile.get('site_count', 0)} | max confidence: {profile.get('max_confidence_score', 0)}"
        )
        st.write(profile.get("bio") or "Bio отсутствует.")
        if profile.get("username"):
            action_cols = st.columns(2)
            if action_cols[0].button(
                "Запустить Sherlock",
                key=f"profile-sherlock-{selected_user_id}",
                use_container_width=True,
            ):
                with st.spinner("Выполняется Sherlock-проверка..."):
                    result = process_username_check(int(selected_user_id), str(profile["username"]))
                    invalidate_views()
                    st.session_state["enrichment_flash"] = result
                    st.rerun()
            maigret_available = is_maigret_available()
            if action_cols[1].button(
                "Обогатить через Maigret",
                key=f"profile-maigret-{selected_user_id}",
                use_container_width=True,
                disabled=not maigret_available,
                help="Глубокая проверка username через Maigret с сохранением результатов в таблицу внешних аккаунтов.",
            ):
                run_maigret_enrichment(int(selected_user_id), str(profile["username"]))
                st.rerun()
            if not maigret_available:
                st.caption("Maigret не установлен в текущем окружении, поэтому кнопка обогащения отключена.")
        else:
            st.warning("У этого профиля нет username, поэтому внешние проверки не запускаются.")

    groups_text = ", ".join(item["group_name"] for item in data["groups"]) or "Нет групп"
    st.markdown("### Telegram-присутствие")
    st.write(f"Чаты: {groups_text}")
    st.write(f"Статус Sherlock: {profile.get('sherlock_status') or 'не выполнялась'}")
    st.write(f"Статус Snoop: {profile.get('snoop_status') or 'не выполнялась'}")
    st.write(f"Статус Maigret: {profile.get('maigret_status') or 'не выполнялась'}")
    if profile.get("sherlock_run_note"):
        st.caption(f"Примечание запуска: {profile['sherlock_run_note']}")

    st.markdown("### Разбор OSINT-оценки")
    for line in build_osint_breakdown(profile):
        st.write(f"- {line}")

    st.markdown("### Найденные внешние аккаунты")
    if not data["social_accounts"]:
        st.info("Внешние аккаунты пока не найдены.")
    for account in data["social_accounts"]:
        st.markdown("<div class='profile-card'>", unsafe_allow_html=True)
        st.markdown(f"**{account['site_name']}**  \n{account['profile_url']}")
        st.markdown(
            confidence_badge(str(account.get("confidence_level") or ""))
            + review_badge(str(account.get("review_status") or "")),
            unsafe_allow_html=True,
        )
        st.caption(
            f"Confidence score: {account.get('confidence_score', 0)} | Источник: {account.get('source', '')} | Проверено: {account.get('checked_at', '')}"
        )
        if account.get("match_reasons"):
            st.write(f"Причины совпадения: {account['match_reasons']}")
        if account.get("review_note"):
            st.caption(f"Комментарий модерации: {account['review_note']}")

        review_cols = st.columns(3)
        if review_cols[0].button("Подтвердить", key=f"review-confirm-{account['id']}"):
            database.update_social_account_review(int(account["id"]), "confirmed", "Подтверждено вручную в Streamlit")
            invalidate_views()
            st.rerun()
        if review_cols[1].button("Отклонить", key=f"review-reject-{account['id']}"):
            database.update_social_account_review(int(account["id"]), "rejected", "Отклонено вручную в Streamlit")
            invalidate_views()
            st.rerun()
        if review_cols[2].button("Сбросить в ожидание", key=f"review-reset-{account['id']}"):
            database.update_social_account_review(int(account["id"]), "pending", "")
            invalidate_views()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Последний лог Sherlock")
    if latest_log and latest_log.get("log_path"):
        with st.expander("Открыть лог"):
            st.caption(
                f"Статус: {latest_log.get('status')} | partial={bool(latest_log.get('is_partial'))} | найдено={latest_log.get('found_count', 0)}"
            )
            st.code(database.read_sherlock_log(str(latest_log["log_path"])) or "Лог пуст.", language="text")
    else:
        st.info("Лог Sherlock для этого профиля пока отсутствует.")


def render_exports_page() -> None:
    st.markdown("## Экспорт и отчеты")
    selected_user_id = st.session_state.get("selected_profile_id")
    left, right = st.columns(2)

    with left:
        st.markdown("### CSV-экспорты")
        baseline_path = database.export_baseline_csv()
        st.download_button("Скачать baseline CSV", data=baseline_path.read_bytes(), file_name=baseline_path.name, mime="text/csv")

        enriched_path = database.export_enriched_csv()
        st.download_button("Скачать enriched CSV", data=enriched_path.read_bytes(), file_name=enriched_path.name, mime="text/csv")

        osint_report_path = database.export_osint_report_csv()
        st.download_button("Скачать OSINT-report CSV", data=osint_report_path.read_bytes(), file_name=osint_report_path.name, mime="text/csv")

    with right:
        st.markdown("### Markdown-отчеты")
        summary_path = database.export_coursework_report_markdown()
        st.download_button(
            "Скачать сводку по курсовой",
            data=summary_path.read_bytes(),
            file_name=summary_path.name,
            mime="text/markdown",
        )

        if selected_user_id:
            profile_path = database.export_profile_report_markdown(int(selected_user_id))
            st.download_button(
                "Скачать отчет по выбранному профилю",
                data=profile_path.read_bytes(),
                file_name=profile_path.name,
                mime="text/markdown",
            )
        else:
            st.info("Выбери профиль, чтобы скачать персональный отчет.")


def main() -> None:
    database.init_db()
    configure_page()
    render_hero()
    selected_page = render_sidebar()

    if selected_page == "Главная":
        render_main_page()
    elif selected_page == "Сбор данных":
        render_collection_page()
    elif selected_page == "OSINT-анализ":
        render_osint_page()
    elif selected_page == "NLP-поиск":
        render_search_page()
    elif selected_page == "Карточка профиля":
        render_profile_page()
    elif selected_page == "Экспорт и отчеты":
        render_exports_page()


if __name__ == "__main__":
    main()
