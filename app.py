from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import database
from config import env_first, load_env_file
from ai_classifier import ProfileClassifier, load_training_report
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from nlp_search_engine import NLPSearchEngine
from link_graph import draw_link_graph, get_link_analysis
from maigret_integration import is_maigret_available, process_maigret_check
from security_analyzer import export_security_report, get_security_snapshot
from sherlock_integration import is_sherlock_available, process_username_check
from snoop_integration import is_snoop_available, process_snoop_check
from telegram_service import TelegramCollector

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - runtime dependency guard
    Image = None
    ImageTk = None


class OSINTApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        load_env_file()
        self.title("OSINT Desktop")
        self.geometry("1200x760")
        self.minsize(1024, 700)

        database.init_db()
        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.sherlock_queue: queue.Queue[dict] = queue.Queue()
        self.snoop_queue: queue.Queue[dict] = queue.Queue()
        self.maigret_queue: queue.Queue[dict] = queue.Queue()
        self.shutdown_event = threading.Event()
        self.search_engine = NLPSearchEngine()
        self.profile_classifier = ProfileClassifier()
        self.result_cache: dict[str, dict] = {}
        self.current_avatar = None
        self.current_profile_id: int | None = None
        self.current_profile_username = ""
        self.collection_thread: threading.Thread | None = None
        self.osint_profile_cache: dict[str, dict] = {}

        self.api_id_var = tk.StringVar(value=env_first("TELEGRAM_API_ID", "TG_API_ID"))
        self.api_hash_var = tk.StringVar(value=env_first("TELEGRAM_API_HASH", "TG_API_HASH"))
        self.session_var = tk.StringVar(value=env_first("TELEGRAM_SESSION") or "osint_session")
        self.group_var = tk.StringVar(value="rabota_chaty1")
        self.profile_lookup_var = tk.StringVar(value="")
        self.limit_var = tk.StringVar(value="100")
        self.search_var = tk.StringVar()
        self.search_mode_var = tk.StringVar(value="Семантический")
        self.min_osint_var = tk.StringVar(value="0")
        self.exposure_filter_var = tk.StringVar(value="any")
        self.username_only_var = tk.BooleanVar(value=False)

        self.profiles_count_var = tk.StringVar()
        self.queued_count_var = tk.StringVar()
        self.completed_count_var = tk.StringVar()
        self.social_count_var = tk.StringVar()
        self.sherlock_status_var = tk.StringVar(
            value=self._build_tools_status()
        )
        self.analytics_summary_var = tk.StringVar(value="")
        self.search_summary_var = tk.StringVar(value="")
        self.search_compare_var = tk.StringVar(value="")
        self.osint_summary_var = tk.StringVar(value="")
        self.profile_osint_var = tk.StringVar(value="")
        self.profile_match_var = tk.StringVar(value="")
        self.profile_ai_var = tk.StringVar(value="")
        self.last_search_results: list[dict] = []
        self.last_search_query = ""
        self.last_search_terms: list[str] = []
        self.security_summary_var = tk.StringVar(value="")
        self.link_graph_data: dict | None = None

        self._build_ui()
        self._start_sherlock_worker()
        self._start_snoop_worker()
        self._start_maigret_worker()
        self._resume_pending_checks()
        self.refresh_dashboard()
        self.after(200, self._drain_event_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.collect_tab = ttk.Frame(notebook, padding=12)
        self.osint_tab = ttk.Frame(notebook, padding=12)
        self.search_tab = ttk.Frame(notebook, padding=12)
        self.analytics_tab = ttk.Frame(notebook, padding=12)
        self.profile_tab = ttk.Frame(notebook, padding=12)
        self.security_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.collect_tab, text="Сбор данных")
        notebook.add(self.osint_tab, text="OSINT-анализ")
        notebook.add(self.search_tab, text="NLP-поиск")
        notebook.add(self.analytics_tab, text="Аналитика")
        notebook.add(self.profile_tab, text="Карточка профиля")
        notebook.add(self.security_tab, text="Кибербезопасность")
        self.notebook = notebook

        self._build_collect_tab()
        self._build_osint_tab()
        self._build_search_tab()
        self._build_analytics_tab()
        self._build_profile_tab()
        self._build_security_tab()

    def _build_collect_tab(self) -> None:
        form = ttk.LabelFrame(self.collect_tab, text="Настройки Telegram", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        fields = [
            ("API ID", self.api_id_var, 0, 0),
            ("API Hash", self.api_hash_var, 0, 2),
            ("Session", self.session_var, 1, 0),
            ("Группа", self.group_var, 1, 2),
            ("Лимит новых профилей", self.limit_var, 2, 0),
            ("Telegram profile", self.profile_lookup_var, 2, 2),
        ]
        for label, variable, row, col in fields:
            ttk.Label(form, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=6)
            entry = ttk.Entry(form, textvariable=variable)
            if "Hash" in label:
                entry.configure(show="*")
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 20), pady=6)

        button_row = ttk.Frame(self.collect_tab)
        button_row.pack(fill="x", pady=(12, 8))
        ttk.Button(button_row, text="Запустить сбор", command=self.start_collection).pack(side="left")
        ttk.Button(button_row, text="Проверить профиль", command=self.start_profile_lookup).pack(side="left", padx=8)
        ttk.Button(button_row, text="Экспорт baseline CSV", command=self.export_baseline).pack(side="left", padx=8)
        ttk.Button(button_row, text="Экспорт enriched CSV", command=self.export_enriched).pack(side="left", padx=8)
        ttk.Button(button_row, text="Экспорт OSINT-отчёта", command=self.export_osint_report).pack(side="left", padx=8)
        ttk.Button(button_row, text="Сводка", command=self.export_summary).pack(side="left", padx=8)

        stats_frame = ttk.LabelFrame(self.collect_tab, text="Статистика", padding=12)
        stats_frame.pack(fill="x", pady=(0, 8))
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(3, weight=1)

        ttk.Label(stats_frame, text="Профилей в БД").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(stats_frame, textvariable=self.profiles_count_var).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(stats_frame, text="В очереди Sherlock").grid(row=0, column=2, sticky="w", padx=(24, 8), pady=4)
        ttk.Label(stats_frame, textvariable=self.queued_count_var).grid(row=0, column=3, sticky="w", pady=4)
        ttk.Label(stats_frame, text="Проверок завершено").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Label(stats_frame, textvariable=self.completed_count_var).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(stats_frame, text="Найдено внешних аккаунтов").grid(row=1, column=2, sticky="w", padx=(24, 8), pady=4)
        ttk.Label(stats_frame, textvariable=self.social_count_var).grid(row=1, column=3, sticky="w", pady=4)
        ttk.Label(stats_frame, textvariable=self.sherlock_status_var).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.log_box = ScrolledText(self.collect_tab, height=22, wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _build_osint_tab(self) -> None:
        header = ttk.Frame(self.osint_tab)
        header.pack(fill="x", pady=(0, 8))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, textvariable=self.osint_summary_var, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Обновить OSINT-анализ", command=self.refresh_osint_analysis).grid(
            row=0, column=1, sticky="e"
        )

        paned = ttk.PanedWindow(self.osint_tab, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        ttk.Label(left, text="Топ профилей по цифровому следу").pack(anchor="w")
        profile_columns = ("osint_score", "exposure_level", "first_name", "username", "group_count", "bio_length")
        self.osint_profiles_tree = ttk.Treeview(left, columns=profile_columns, show="headings", height=13)
        for column, title, width in [
            ("osint_score", "OSINT", 70),
            ("exposure_level", "Уровень", 90),
            ("first_name", "Имя", 160),
            ("username", "Username", 150),
            ("group_count", "Groups", 70),
            ("bio_length", "Bio len", 70),
        ]:
            self.osint_profiles_tree.heading(column, text=title)
            self.osint_profiles_tree.column(column, width=width, anchor="w")
        self.osint_profiles_tree.pack(fill="both", expand=True, pady=(4, 10))
        self.osint_profiles_tree.bind("<Double-1>", self.open_selected_osint_profile)

        actions = ttk.Frame(left)
        actions.pack(fill="x")
        ttk.Button(actions, text="Открыть карточку", command=self.open_selected_osint_profile).pack(side="left")
        ttk.Button(actions, text="Сформировать отчёт профиля", command=self.export_selected_profile_report).pack(
            side="left", padx=8
        )

        ttk.Label(right, text="Группы и покрытие").pack(anchor="w")
        group_columns = ("group_name", "user_count", "with_username", "with_bio", "with_photo")
        self.osint_groups_tree = ttk.Treeview(right, columns=group_columns, show="headings", height=10)
        for column, title, width in [
            ("group_name", "Группа", 180),
            ("user_count", "Users", 70),
            ("with_username", "Username", 80),
            ("with_bio", "Bio", 60),
            ("with_photo", "Photo", 60),
        ]:
            self.osint_groups_tree.heading(column, text=title)
            self.osint_groups_tree.column(column, width=width, anchor="w")
        self.osint_groups_tree.pack(fill="both", expand=True, pady=(4, 10))

        ttk.Label(right, text="Пересечения групп").pack(anchor="w")
        self.osint_overlap_box = ScrolledText(right, height=9, wrap="word")
        self.osint_overlap_box.pack(fill="both", expand=True, pady=(4, 0))
        self.osint_overlap_box.configure(state="disabled")

        self.refresh_osint_analysis()

    def _build_search_tab(self) -> None:
        controls = ttk.Frame(self.search_tab)
        controls.pack(fill="x", pady=(0, 8))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Запрос").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Искать", command=self.start_search).grid(row=0, column=2, padx=8)
        ttk.Button(controls, text="Обновить индекс", command=self.refresh_search_index).grid(row=0, column=3)
        ttk.Button(controls, text="Сравнить режимы", command=self.compare_search_modes).grid(row=0, column=4, padx=8)
        ttk.Button(controls, text="Экспорт поиска в CSV", command=self.export_search_results).grid(row=0, column=5)

        filters = ttk.Frame(self.search_tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Режим").pack(side="left")
        ttk.Combobox(
            filters,
            textvariable=self.search_mode_var,
            values=("Семантический", "Гибридный"),
            width=14,
            state="readonly",
        ).pack(side="left", padx=(6, 16))
        ttk.Label(filters, text="Мин. OSINT-балл").pack(side="left")
        ttk.Spinbox(filters, from_=0, to=100, increment=5, textvariable=self.min_osint_var, width=6).pack(
            side="left", padx=(6, 16)
        )
        ttk.Label(filters, text="Уровень следа").pack(side="left")
        ttk.Combobox(
            filters,
            textvariable=self.exposure_filter_var,
            values=("any", "low", "medium", "high"),
            width=10,
            state="readonly",
        ).pack(side="left", padx=(6, 16))
        ttk.Checkbutton(filters, text="Только с username", variable=self.username_only_var).pack(side="left")

        ttk.Label(self.search_tab, textvariable=self.search_summary_var, justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Label(self.search_tab, textvariable=self.search_compare_var, justify="left").pack(anchor="w", pady=(0, 8))

        columns = (
            "score",
            "hybrid_score",
            "osint_score",
            "exposure_level",
            "first_name",
            "username",
            "ai_label",
            "ai_confidence",
            "matched_terms",
            "group_name",
            "site_list",
        )
        self.results_tree = ttk.Treeview(
            self.search_tab,
            columns=columns,
            show="headings",
            height=22,
        )
        headings = {
            "score": "Score",
            "hybrid_score": "Гибрид",
            "osint_score": "OSINT",
            "exposure_level": "Уровень",
            "first_name": "Имя",
            "username": "Username",
            "ai_label": "AI-класс",
            "ai_confidence": "AI conf",
            "matched_terms": "Совпавшие термины",
            "group_name": "Чаты",
            "site_list": "Сайты",
        }
        widths = {
            "score": 80,
            "hybrid_score": 80,
            "osint_score": 80,
            "exposure_level": 90,
            "first_name": 180,
            "username": 150,
            "ai_label": 130,
            "ai_confidence": 80,
            "matched_terms": 220,
            "group_name": 250,
            "site_list": 260,
        }
        for column in columns:
            self.results_tree.heading(column, text=headings[column])
            self.results_tree.column(column, width=widths[column], anchor="w")
        self.results_tree.pack(fill="both", expand=True)
        self.results_tree.bind("<Double-1>", self.open_selected_profile)

    def _build_analytics_tab(self) -> None:
        header = ttk.Frame(self.analytics_tab)
        header.pack(fill="x", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            textvariable=self.analytics_summary_var,
            justify="left",
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Обновить графики", command=self.refresh_analytics).grid(
            row=0, column=1, sticky="e"
        )

        self.analytics_canvas_frame = ttk.Frame(self.analytics_tab)
        self.analytics_canvas_frame.pack(fill="both", expand=True)
        self.analytics_canvas = None
        self.refresh_analytics()

    def _build_profile_tab(self) -> None:
        top_frame = ttk.Frame(self.profile_tab)
        top_frame.pack(fill="x")
        top_frame.columnconfigure(1, weight=1)

        self.avatar_label = ttk.Label(top_frame, text="Аватар недоступен", width=32, anchor="center")
        self.avatar_label.grid(row=0, column=0, rowspan=6, sticky="nw", padx=(0, 16))

        self.profile_name_var = tk.StringVar(value="Профиль не выбран")
        self.profile_username_var = tk.StringVar(value="")
        self.profile_groups_var = tk.StringVar(value="")
        self.profile_status_var = tk.StringVar(value="")
        self.profile_sites_var = tk.StringVar(value="")
        self.profile_avatar_path_var = tk.StringVar(value="")

        ttk.Label(top_frame, textvariable=self.profile_name_var, font=("Segoe UI", 16, "bold")).grid(
            row=0, column=1, sticky="w", pady=(0, 6)
        )
        ttk.Label(top_frame, textvariable=self.profile_username_var).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(top_frame, textvariable=self.profile_groups_var, wraplength=760, justify="left").grid(
            row=2, column=1, sticky="w", pady=2
        )
        ttk.Label(top_frame, textvariable=self.profile_status_var, wraplength=760, justify="left").grid(
            row=3, column=1, sticky="w", pady=2
        )
        ttk.Label(top_frame, textvariable=self.profile_sites_var, wraplength=760, justify="left").grid(
            row=4, column=1, sticky="w", pady=2
        )
        ttk.Label(top_frame, textvariable=self.profile_avatar_path_var, wraplength=760, justify="left").grid(
            row=5, column=1, sticky="w", pady=2
        )
        ttk.Label(top_frame, textvariable=self.profile_osint_var, wraplength=760, justify="left").grid(
            row=6, column=1, sticky="w", pady=(8, 2)
        )
        ttk.Label(top_frame, textvariable=self.profile_match_var, wraplength=760, justify="left").grid(
            row=7, column=1, sticky="w", pady=2
        )
        ttk.Label(top_frame, textvariable=self.profile_ai_var, wraplength=760, justify="left").grid(
            row=8, column=1, sticky="w", pady=2
        )
        ttk.Button(top_frame, text="Запустить Sherlock для профиля", command=self.run_sherlock_for_current_profile).grid(
            row=9, column=1, sticky="w", pady=(8, 0)
        )
        ttk.Button(top_frame, text="Запустить Snoop для профиля", command=self.run_snoop_for_current_profile).grid(
            row=9, column=1, sticky="w", padx=(220, 0), pady=(8, 0)
        )
        ttk.Button(top_frame, text="Запустить Maigret для профиля", command=self.run_maigret_for_current_profile).grid(
            row=9, column=1, sticky="w", padx=(440, 0), pady=(8, 0)
        )

        ttk.Label(self.profile_tab, text="Bio").pack(anchor="w", pady=(16, 4))
        self.bio_box = ScrolledText(self.profile_tab, height=8, wrap="word")
        self.bio_box.pack(fill="x")
        self.bio_box.configure(state="disabled")

        ttk.Label(self.profile_tab, text="OSINT-факторы").pack(anchor="w", pady=(16, 4))
        self.osint_breakdown_box = ScrolledText(self.profile_tab, height=7, wrap="word")
        self.osint_breakdown_box.pack(fill="x")
        self.osint_breakdown_box.configure(state="disabled")

        ttk.Label(self.profile_tab, text="Внешние аккаунты").pack(anchor="w", pady=(16, 4))
        self.social_box = ScrolledText(self.profile_tab, height=12, wrap="word")
        self.social_box.pack(fill="both", expand=True)
        self.social_box.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    @staticmethod
    def _build_tools_status() -> str:
        sherlock_state = "available" if is_sherlock_available() else "not installed"
        snoop_state = "available" if is_snoop_available() else "not installed"
        maigret_state = "available" if is_maigret_available() else "not installed"
        return f"Sherlock: {sherlock_state} | Snoop: {snoop_state} | Maigret: {maigret_state}"

    def refresh_dashboard(self) -> None:
        stats = database.get_dashboard_stats()
        self.profiles_count_var.set(str(stats["profiles"]))
        self.queued_count_var.set(
            f"Sherlock {stats['queued_checks']} | Snoop {stats.get('queued_snoop_checks', 0)} | Maigret {stats.get('queued_maigret_checks', 0)}"
        )
        self.completed_count_var.set(
            f"Sherlock {stats['completed_checks']} | Snoop {stats.get('completed_snoop_checks', 0)} | Maigret {stats.get('completed_maigret_checks', 0)}"
        )
        self.social_count_var.set(str(stats["social_accounts"]))
        self.sherlock_status_var.set(self._build_tools_status())
        self.refresh_osint_analysis()
        self.refresh_analytics()
        self.refresh_security()

    def refresh_osint_analysis(self) -> None:
        snapshot = database.get_osint_analysis_snapshot()
        top_profiles = snapshot["top_profiles"]
        group_stats = snapshot["group_stats"]
        multi_group_users = snapshot["multi_group_users"]
        group_overlaps = snapshot["group_overlaps"]

        self.osint_summary_var.set(
            "Топ профилей: {profiles} | групп в анализе: {groups} | "
            "пользователей в нескольких группах: {multi} | пересечений групп: {overlaps}".format(
                profiles=len(top_profiles),
                groups=len(group_stats),
                multi=len(multi_group_users),
                overlaps=len(group_overlaps),
            )
        )

        self.osint_profile_cache.clear()
        for item_id in self.osint_profiles_tree.get_children():
            self.osint_profiles_tree.delete(item_id)
        for index, profile in enumerate(top_profiles):
            item_id = f"osint-profile-{index}"
            self.osint_profile_cache[item_id] = profile
            username = f"@{profile['username']}" if profile["username"] else "[скрыт]"
            self.osint_profiles_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    profile["osint_score"],
                    self._format_exposure(profile["exposure_level"]),
                    profile["first_name"],
                    username,
                    profile["group_count"],
                    profile["bio_length"],
                ),
            )

        for item_id in self.osint_groups_tree.get_children():
            self.osint_groups_tree.delete(item_id)
        for row in group_stats:
            self.osint_groups_tree.insert(
                "",
                "end",
                values=(
                    row["group_name"],
                    row["user_count"],
                    row["with_username"],
                    row["with_bio"],
                    row["with_photo"],
                ),
            )

        overlap_lines = []
        if group_overlaps:
            overlap_lines.extend(
                f"{row['group_a']} <-> {row['group_b']}: общих пользователей {row['shared_users']}"
                for row in group_overlaps
            )
        else:
            overlap_lines.append(
                "На текущем датасете пересечений между группами не найдено: каждый пользователь привязан к одной группе."
            )
        if multi_group_users:
            overlap_lines.append("")
            overlap_lines.append("Пользователи в нескольких группах:")
            overlap_lines.extend(
                f"@{row['username'] or 'скрыт'}: групп {row['group_count']} ({row['groups']})"
                for row in multi_group_users[:10]
            )

        self.osint_overlap_box.configure(state="normal")
        self.osint_overlap_box.delete("1.0", "end")
        self.osint_overlap_box.insert("1.0", "\n".join(overlap_lines))
        self.osint_overlap_box.configure(state="disabled")

    def _get_selected_osint_profile(self) -> dict | None:
        selected = self.osint_profiles_tree.selection()
        if not selected:
            return None
        return self.osint_profile_cache.get(selected[0])

    def open_selected_osint_profile(self, _event: object = None) -> None:
        profile = self._get_selected_osint_profile()
        if profile is None:
            return
        self.last_search_terms = []
        self.last_search_query = ""
        self.show_profile_card(int(profile["user_id"]))
        self.notebook.select(self.profile_tab)

    def export_selected_profile_report(self) -> None:
        profile = self._get_selected_osint_profile()
        if profile is None:
            messagebox.showinfo("Профиль не выбран", "Выберите профиль в OSINT-рейтинге.")
            return
        path = database.export_profile_report_markdown(int(profile["user_id"]))
        self._append_log(f"OSINT-отчет по профилю сохранен: {path}")

    def refresh_analytics(self) -> None:
        snapshot = database.get_analytics_snapshot()
        totals = snapshot["totals"]
        profiles = totals.get("profiles") or 0
        with_bio = totals.get("with_bio") or 0
        with_username = totals.get("with_username") or 0
        with_photo = totals.get("with_photo") or 0

        bio_pct = (with_bio / profiles * 100) if profiles else 0
        username_pct = (with_username / profiles * 100) if profiles else 0
        photo_pct = (with_photo / profiles * 100) if profiles else 0
        training_report = load_training_report()
        ai_text = "AI model: rules fallback"
        if training_report:
            ai_text = (
                f"AI model: trained classifier | accuracy={training_report.get('accuracy', 0):.2f} | "
                f"classes={len(training_report.get('classes', []))}"
            )
        self.analytics_summary_var.set(
            "Профилей: {profiles} | С bio: {bio} ({bio_pct:.1f}%) | "
            "С username: {username} ({username_pct:.1f}%) | С фото: {photo} ({photo_pct:.1f}%) | {ai_text}".format(
                profiles=profiles,
                bio=with_bio,
                bio_pct=bio_pct,
                username=with_username,
                username_pct=username_pct,
                photo=with_photo,
                photo_pct=photo_pct,
                ai_text=ai_text,
            )
        )

        for widget in self.analytics_canvas_frame.winfo_children():
            widget.destroy()

        figure = Figure(figsize=(10.8, 6.6), dpi=100)
        figure.patch.set_facecolor("#f5f7f7")
        axes = [
            figure.add_subplot(2, 2, 1),
            figure.add_subplot(2, 2, 2),
            figure.add_subplot(2, 2, 3),
            figure.add_subplot(2, 2, 4),
        ]

        self._draw_top_groups_chart(axes[0], snapshot["top_groups"])
        self._draw_bucket_chart(axes[1], snapshot["bio_buckets"], "Длина Bio", "#227c9d")
        self._draw_bucket_chart(axes[2], snapshot["score_buckets"], "Распределение OSINT-баллов", "#17a398")
        self._draw_status_chart(axes[3], snapshot)

        figure.tight_layout(pad=2.2)
        self.analytics_canvas = FigureCanvasTkAgg(figure, master=self.analytics_canvas_frame)
        self.analytics_canvas.draw()
        self.analytics_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _draw_top_groups_chart(self, axis, rows: list[dict]) -> None:
        labels = [row["group_name"] for row in rows[:8]]
        values = [row["count_value"] for row in rows[:8]]
        axis.set_title("Топ Telegram-групп")
        if not labels:
            axis.text(0.5, 0.5, "Нет данных", ha="center", va="center")
            axis.set_axis_off()
            return
        axis.barh(labels[::-1], values[::-1], color="#2f6f4e")
        axis.tick_params(axis="y", labelsize=8)
        axis.grid(axis="x", alpha=0.25)

    def _draw_bucket_chart(self, axis, buckets: dict[str, int], title: str, color: str) -> None:
        labels = list(buckets.keys())
        values = list(buckets.values())
        axis.set_title(title)
        axis.bar(labels, values, color=color)
        axis.grid(axis="y", alpha=0.25)
        axis.tick_params(axis="x", labelsize=8)

    def _draw_status_chart(self, axis, snapshot: dict) -> None:
        levels = snapshot["exposure_levels"]
        labels = ["low", "medium", "high"]
        values = [levels.get(label, 0) for label in labels]
        axis.set_title("Уровень цифрового следа")
        axis.bar(labels, values, color=["#8ab17d", "#f4a261", "#e76f51"])
        axis.grid(axis="y", alpha=0.25)

    def _resume_pending_checks(self) -> None:
        for item in database.list_pending_username_checks(limit=1000):
            self.sherlock_queue.put(item)
        for item in database.list_pending_enrichment_checks("snoop", limit=1000):
            self.snoop_queue.put(item)
        for item in database.list_pending_enrichment_checks("maigret", limit=1000):
            self.maigret_queue.put(item)
        stats = database.get_dashboard_stats()
        if stats["queued_checks"]:
            self._append_log(f"Возобновлено проверок Sherlock: {stats['queued_checks']}.")
        if stats.get("queued_snoop_checks", 0):
            self._append_log(f"Возобновлено проверок Snoop: {stats['queued_snoop_checks']}.")
        if stats.get("queued_maigret_checks", 0):
            self._append_log(f"Возобновлено проверок Maigret: {stats['queued_maigret_checks']}.")

    def _start_sherlock_worker(self) -> None:
        worker = threading.Thread(target=self._sherlock_worker_loop, daemon=True)
        worker.start()
        self.sherlock_worker = worker

    def _start_snoop_worker(self) -> None:
        worker = threading.Thread(target=self._snoop_worker_loop, daemon=True)
        worker.start()
        self.snoop_worker = worker

    def _start_maigret_worker(self) -> None:
        worker = threading.Thread(target=self._maigret_worker_loop, daemon=True)
        worker.start()
        self.maigret_worker = worker

    def _sherlock_worker_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                item = self.sherlock_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break

            user_id = int(item["user_id"])
            username = str(item["username"])
            self.event_queue.put({"type": "log", "message": f"Запущен Sherlock для @{username}"})
            result = process_username_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put(
                {
                    "type": "log",
                    "message": result["message"],
                }
            )
            self.event_queue.put({"type": "progress", "stats": database.get_dashboard_stats()})
            self.sherlock_queue.task_done()

    def _snoop_worker_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                item = self.snoop_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break

            user_id = int(item["user_id"])
            username = str(item["username"])
            self.event_queue.put({"type": "log", "message": f"Запущен Snoop для @{username}"})
            result = process_snoop_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put({"type": "log", "message": result["message"]})
            self.event_queue.put({"type": "progress", "stats": database.get_dashboard_stats()})
            self.snoop_queue.task_done()

    def _maigret_worker_loop(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                item = self.maigret_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            user_id = int(item["user_id"])
            username = str(item["username"])
            self.event_queue.put({"type": "log", "message": f"Запущен Maigret для @{username}"})
            result = process_maigret_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put({"type": "log", "message": result["message"]})
            self.event_queue.put({"type": "progress", "stats": database.get_dashboard_stats()})
            self.maigret_queue.task_done()

    def start_collection(self) -> None:
        if self.collection_thread and self.collection_thread.is_alive():
            messagebox.showinfo("Сбор уже запущен", "Дождитесь завершения текущего процесса.")
            return

        try:
            limit = int(self.limit_var.get().strip())
        except ValueError:
            messagebox.showerror("Некорректный лимит", "Лимит должен быть числом.")
            return

        collector = TelegramCollector(
            api_id=self.api_id_var.get().strip(),
            api_hash=self.api_hash_var.get().strip(),
            session_name=self.session_var.get().strip(),
        )

        def runner() -> None:
            try:
                asyncio.run(
                    collector.collect_group(
                        group_name=self.group_var.get().strip().lstrip("@"),
                        limit_new_users=limit,
                        event_callback=self.event_queue.put,
                    )
                )
                self.search_engine.invalidate()
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": str(exc)})

        self.collection_thread = threading.Thread(target=runner, daemon=True)
        self.collection_thread.start()
        self._append_log("Фоновый поток сбора данных запущен.")

    def start_profile_lookup(self) -> None:
        target = self.profile_lookup_var.get().strip()
        if not target:
            messagebox.showinfo("Нет профиля", "Введите @username, ссылку t.me/... или Telegram user id.")
            return

        collector = TelegramCollector(
            api_id=self.api_id_var.get().strip(),
            api_hash=self.api_hash_var.get().strip(),
            session_name=self.session_var.get().strip(),
        )

        def runner() -> None:
            try:
                asyncio.run(
                    collector.collect_profile(
                        target=target,
                        group_name="direct_lookup",
                        event_callback=self.event_queue.put,
                    )
                )
                self.search_engine.invalidate()
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": str(exc)})

        threading.Thread(target=runner, daemon=True).start()
        self._append_log(f"Запущена realtime-проверка профиля: {target}")

    def export_baseline(self) -> None:
        path = database.export_baseline_csv()
        self._append_log(f"Базовый датасет сохранен: {path}")
        self.search_engine.invalidate()

    def export_enriched(self) -> None:
        path = database.export_enriched_csv()
        self._append_log(f"Расширенный датасет сохранен: {path}")

    def export_osint_report(self) -> None:
        path = database.export_osint_report_csv()
        self._append_log(f"OSINT-отчет сохранен: {path}")

    def export_summary(self) -> None:
        path = database.export_summary_report_markdown()
        self._append_log(f"Сводка сохранена: {path}")

    def refresh_search_index(self) -> None:
        self.profile_classifier = ProfileClassifier()
        self.search_engine = NLPSearchEngine()
        self.search_engine.invalidate()
        self._append_log("Поисковый индекс и AI-классификатор обновлены.")

    @staticmethod
    def _format_exposure(value: str) -> str:
        mapping = {
            "low": "низкий",
            "medium": "средний",
            "high": "высокий",
            "any": "любой",
        }
        return mapping.get(value, value or "-")

    @staticmethod
    def _format_backend(value: str) -> str:
        mapping = {
            "semantic": "семантический",
            "lexical": "лексический",
        }
        return mapping.get(value, value or "-")

    def _get_search_mode_key(self) -> tuple[str, str]:
        label = self.search_mode_var.get().strip() or "Семантический"
        mapping = {
            "Семантический": "semantic",
            "Гибридный": "hybrid",
        }
        return mapping.get(label, "semantic"), label

    def _get_search_filters(self) -> tuple[int, str, bool]:
        try:
            min_osint = int(self.min_osint_var.get().strip() or "0")
        except ValueError:
            min_osint = 0
        return min_osint, self.exposure_filter_var.get(), self.username_only_var.get()

    def start_search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            return
        mode, mode_label = self._get_search_mode_key()
        min_osint, exposure, username_only = self._get_search_filters()

        def runner() -> None:
            try:
                if mode == "hybrid":
                    results = self.search_engine.search_hybrid(query, top_k=100)
                else:
                    results = self.search_engine.search(query, top_k=100)
                filtered_results = self._filter_search_results(results, min_osint, exposure, username_only)
                self.event_queue.put(
                    {
                        "type": "search_summary",
                        "message": self._build_search_summary(query, mode_label, results, filtered_results),
                    }
                )
                self.event_queue.put({"type": "search_results", "results": filtered_results[:15], "query": query})
                self.event_queue.put({"type": "search_compare", "message": ""})
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": str(exc)})

        threading.Thread(target=runner, daemon=True).start()

    def compare_search_modes(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            return
        min_osint, exposure, username_only = self._get_search_filters()

        def runner() -> None:
            try:
                comparison = self.search_engine.compare_search_modes(query, top_k=15)
                baseline = self._filter_search_results(comparison["baseline"], min_osint, exposure, username_only)
                hybrid = self._filter_search_results(comparison["hybrid"], min_osint, exposure, username_only)
                compare_message = (
                    f"Сравнение режимов | движок={self._format_backend(comparison['backend'])} | "
                    f"базовая выдача={len(baseline)} | гибридная выдача={len(hybrid)} | "
                    f"общих профилей={comparison['overlap_count']} | новых в гибриде={comparison['changed_count']}"
                )
                self.event_queue.put({"type": "search_compare", "message": compare_message})
                self.event_queue.put(
                    {
                        "type": "search_summary",
                        "message": self._build_search_summary(query, "Гибридный", comparison["hybrid"], hybrid),
                    }
                )
                self.event_queue.put({"type": "search_results", "results": hybrid[:15], "query": query})
            except Exception as exc:
                self.event_queue.put({"type": "error", "message": str(exc)})

        threading.Thread(target=runner, daemon=True).start()

    def export_search_results(self) -> None:
        if not self.last_search_results:
            messagebox.showinfo("Нет результатов", "Сначала выполните поиск, чтобы экспортировать результаты.")
            return

        safe_query = (self.last_search_query or "search").replace(" ", "_")
        safe_query = "".join(ch for ch in safe_query if ch.isalnum() or ch in {"_", "-"}).strip("_") or "search"
        path = Path(__file__).resolve().parent / f"search_results_{safe_query}.csv"
        exported_path = self.search_engine.export_results_csv(self.last_search_results, path)
        self._append_log(f"Результаты поиска сохранены: {exported_path}")

    def _filter_search_results(
        self,
        results: list[dict],
        min_osint: int,
        exposure: str,
        username_only: bool,
    ) -> list[dict]:
        filtered = []
        for row in results:
            if int(row.get("osint_score") or 0) < min_osint:
                continue
            if exposure != "any" and row.get("exposure_level") != exposure:
                continue
            if username_only and not row.get("username"):
                continue
            filtered.append(row)
        return filtered

    def _build_search_summary(
        self,
        query: str,
        mode: str,
        raw_results: list[dict],
        filtered_results: list[dict],
    ) -> str:
        top = filtered_results[0] if filtered_results else None
        if top is None:
            return f"Запрос: {query} | режим: {mode} | кандидатов: {len(raw_results)} | после фильтров: 0"
        return (
            f"Запрос: {query} | режим: {mode} | кандидатов: {len(raw_results)} | после фильтров: {len(filtered_results)} | "
            f"лучший профиль: @{top.get('username') or 'скрыт'} | "
            f"NLP={top.get('score', 0):.2f}, гибрид={top.get('hybrid_score', 0):.2f}, "
            f"OSINT={top.get('osint_score', 0)}, AI={top.get('ai_label', 'other')} "
            f"({float(top.get('ai_confidence') or 0):.2f}), совпадения={top.get('matched_terms') or '-'}"
        )

    def _show_search_results(self, results: list[dict], query: str = "") -> None:
        self.last_search_results = list(results)
        self.last_search_query = query
        self.last_search_terms = []
        if results:
            terms_text = str(results[0].get("query_terms") or "")
            self.last_search_terms = [term.strip() for term in terms_text.split(",") if term.strip()]
        self.result_cache.clear()
        for item_id in self.results_tree.get_children():
            self.results_tree.delete(item_id)

        for index, result in enumerate(results):
            key = f"result-{index}"
            self.result_cache[key] = result
            username = f"@{result['username']}" if result["username"] else "[скрыт]"
            self.results_tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    f"{result['score']:.2f}",
                    f"{float(result.get('hybrid_score') or 0):.2f}",
                    result["osint_score"],
                    self._format_exposure(result["exposure_level"]),
                    result["first_name"],
                    username,
                    result.get("ai_label", "other"),
                    f"{float(result.get('ai_confidence') or 0):.2f}",
                    result.get("matched_terms", ""),
                    result["group_name"],
                    result["site_list"],
                ),
            )
        if results:
            self._append_log(f"Поиск вернул результатов: {len(results)}.")
        else:
            self._append_log("Поиск не дал результатов.")

    def open_selected_profile(self, _event: object = None) -> None:
        selected = self.results_tree.selection()
        if not selected:
            return
        item = self.result_cache.get(selected[0])
        if item is None:
            return
        matched_terms = str(item.get("matched_terms") or "")
        self.last_search_terms = [term.strip() for term in matched_terms.split(",") if term.strip()]
        self.show_profile_card(int(item["user_id"]))
        self.notebook.select(self.profile_tab)

    def show_profile_card(self, user_id: int) -> None:
        data = database.get_profile_card(user_id)
        profile = data["profile"]
        self.current_profile_id = int(profile["user_id"])
        self.current_profile_username = profile["username"] or ""

        username = f"@{profile['username']}" if profile["username"] else "[скрыт]"
        self.profile_name_var.set(profile["first_name"] or f"Пользователь {profile['user_id']}")
        self.profile_username_var.set(f"Имя пользователя: {username}")
        groups_text = ", ".join(group["group_name"] for group in data["groups"]) or "Нет групп"
        self.profile_groups_var.set(f"Чаты: {groups_text}")

        status = profile["sherlock_status"] or "не выполнялась"
        error_text = profile["sherlock_error_text"] or "нет"
        snoop_status = profile.get("snoop_status") or "не выполнялась"
        snoop_error_text = profile.get("snoop_error_text") or "нет"
        self.profile_status_var.set(
            f"Sherlock: {status}; найдено={profile['sherlock_found_count']}; ошибка={error_text} | "
            f"Snoop: {snoop_status}; найдено={profile.get('snoop_found_count', 0)}; ошибка={snoop_error_text}"
        )
        self.profile_sites_var.set(f"Сайты: {profile['site_list'] or 'нет данных'}")
        self.profile_avatar_path_var.set(f"Аватар: {profile['photo_path'] or 'недоступен'}")
        self.profile_osint_var.set(
            "OSINT-балл: {score}/100 | уровень: {level} | групп: {groups} | длина bio: {bio_length}".format(
                score=profile["osint_score"],
                level=self._format_exposure(profile["exposure_level"]),
                groups=profile["group_count"],
                bio_length=profile["bio_length"],
            )
        )
        matched_terms = []
        for term in self.last_search_terms:
            if term.lower() in (profile["bio"] or "").lower():
                matched_terms.append(term)
        self.profile_match_var.set(
            "Объяснение релевантности: совпавшие термины = {terms}".format(
                terms=", ".join(matched_terms) if matched_terms else "прямых лексических совпадений нет"
            )
        )
        classification = self.profile_classifier.classify(profile)
        self.profile_ai_var.set(f"AI-классификация: {classification['explanation']}")

        self.bio_box.configure(state="normal")
        self.bio_box.delete("1.0", "end")
        self.bio_box.insert("1.0", profile["bio"] or "")
        self._highlight_bio_terms(self.bio_box, self.last_search_terms)
        self.bio_box.configure(state="disabled")

        self.osint_breakdown_box.configure(state="normal")
        self.osint_breakdown_box.delete("1.0", "end")
        self.osint_breakdown_box.insert("1.0", self._build_osint_breakdown(profile))
        self.osint_breakdown_box.configure(state="disabled")

        social_lines = []
        for account in data["social_accounts"]:
            social_lines.append(
                "{site}: {url} ({source}, {checked_at}) | same-person {score}% | {verdict} | {reason}".format(
                    site=account["site_name"],
                    url=account["profile_url"],
                    source=account["source"],
                    checked_at=account["checked_at"],
                    score=account.get("same_person_percent", 0),
                    verdict=account.get("identity_verdict", "not_scored"),
                    reason=account.get("identity_explanation", "no identity score"),
                )
            )
        self.social_box.configure(state="normal")
        self.social_box.delete("1.0", "end")
        self.social_box.insert("1.0", "\n".join(social_lines) if social_lines else "Внешние аккаунты не найдены.")
        self.social_box.configure(state="disabled")

        self._update_avatar(profile["photo_path"])

    def _highlight_bio_terms(self, widget: ScrolledText, terms: list[str]) -> None:
        widget.tag_remove("query_match", "1.0", "end")
        widget.tag_configure("query_match", background="#fff0a6", foreground="#1f1f1f")
        content = widget.get("1.0", "end-1c")
        content_lower = content.lower()
        for term in terms:
            needle = term.strip().lower()
            if not needle or len(needle) < 2:
                continue
            start_index = 0
            while True:
                position = content_lower.find(needle, start_index)
                if position == -1:
                    break
                end_position = position + len(needle)
                widget.tag_add("query_match", f"1.0+{position}c", f"1.0+{end_position}c")
                start_index = end_position

    def _build_osint_breakdown(self, profile: dict) -> str:
        username_points = 15 if profile["username"] else 0
        bio_points = 20 if profile["bio"] else 0
        photo_points = 10 if profile["has_photo"] else 0
        if profile["bio_length"] >= 120:
            bio_depth_points = 15
        elif profile["bio_length"] >= 40:
            bio_depth_points = 10
        elif profile["bio_length"] > 0:
            bio_depth_points = 5
        else:
            bio_depth_points = 0
        group_points = min(int(profile["group_count"]) * 10, 25)
        social_points = min(int(profile["site_count"]) * 15, 30)
        return "\n".join(
            [
                f"Username найден: +{username_points}",
                f"Bio заполнено: +{bio_points}",
                f"Информативность bio ({profile['bio_length']} символов): +{bio_depth_points}",
                f"Аватар сохранён: +{photo_points}",
                f"Связи с Telegram-группами ({profile['group_count']}): +{group_points}",
                f"Внешние аккаунты OSINT-инструментов ({profile['site_count']}): +{social_points}",
                f"Итог: {profile['osint_score']}/100, уровень: {profile['exposure_level']}",
            ]
        )

    def run_sherlock_for_current_profile(self) -> None:
        if self.current_profile_id is None:
            messagebox.showinfo("Профиль не выбран", "Сначала откройте карточку профиля из результатов поиска.")
            return
        if not self.current_profile_username:
            messagebox.showinfo("Нет username", "У выбранного профиля нет username для проверки через Sherlock.")
            return

        user_id = self.current_profile_id
        username = self.current_profile_username
        self._append_log(f"Запущена ручная проверка Sherlock для @{username}.")

        def runner() -> None:
            result = process_username_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put(
                {
                    "type": "manual_sherlock_done",
                    "user_id": user_id,
                    "message": result["message"],
                }
            )

        threading.Thread(target=runner, daemon=True).start()

    def run_snoop_for_current_profile(self) -> None:
        if self.current_profile_id is None:
            messagebox.showinfo("Профиль не выбран", "Сначала откройте карточку профиля из результатов поиска.")
            return
        if not self.current_profile_username:
            messagebox.showinfo("Нет username", "У выбранного профиля нет username для проверки через Snoop.")
            return

        user_id = self.current_profile_id
        username = self.current_profile_username
        self._append_log(f"Запущена ручная проверка Snoop для @{username}.")

        def runner() -> None:
            result = process_snoop_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put(
                {
                    "type": "manual_enrichment_done",
                    "user_id": user_id,
                    "message": result["message"],
                }
            )

        threading.Thread(target=runner, daemon=True).start()

    def run_maigret_for_current_profile(self) -> None:
        if self.current_profile_id is None:
            messagebox.showinfo("Профиль не выбран", "Сначала откройте карточку профиля.")
            return
        if not self.current_profile_username:
            messagebox.showinfo("Нет username", "У выбранного профиля нет username для проверки через Maigret.")
            return
        user_id = self.current_profile_id
        username = self.current_profile_username
        self._append_log(f"Запущена ручная проверка Maigret для @{username}.")

        def runner() -> None:
            result = process_maigret_check(user_id=user_id, username=username)
            self.search_engine.invalidate()
            self.event_queue.put({
                "type": "manual_enrichment_done",
                "user_id": user_id,
                "message": result["message"],
            })

        threading.Thread(target=runner, daemon=True).start()

    def _update_avatar(self, photo_path: str) -> None:
        if not photo_path:
            self.avatar_label.configure(image="", text="Аватар недоступен")
            self.current_avatar = None
            return

        base_dir = Path(__file__).resolve().parent
        absolute_path = (base_dir / photo_path).resolve()
        try:
            absolute_path.relative_to(base_dir)
        except ValueError:
            self.avatar_label.configure(image="", text="Аватар недоступен")
            self.current_avatar = None
            return

        if not absolute_path.exists() or Image is None or ImageTk is None:
            self.avatar_label.configure(image="", text="Аватар недоступен")
            self.current_avatar = None
            return

        image = Image.open(absolute_path)
        image.thumbnail((220, 220))
        self.current_avatar = ImageTk.PhotoImage(image)
        self.avatar_label.configure(image=self.current_avatar, text="")

    def _drain_event_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("type")
            if event_type == "log":
                self._append_log(str(event.get("message", "")))
            elif event_type == "progress":
                self.refresh_dashboard()
            elif event_type == "username_pending":
                self.sherlock_queue.put(
                    {"user_id": event["user_id"], "username": event["username"]}
                )
                self.refresh_dashboard()
            elif event_type == "enrichment_pending":
                tool = event.get("tool_name", "")
                if tool == "snoop":
                    self.snoop_queue.put(
                        {"user_id": event["user_id"], "username": event["username"], "tool_name": "snoop"}
                    )
                elif tool == "maigret":
                    self.maigret_queue.put(
                        {"user_id": event["user_id"], "username": event["username"], "tool_name": "maigret"}
                    )
                self.refresh_dashboard()
            elif event_type == "completed":
                stats = event["stats"]
                self._append_log(
                    "Сбор завершен: "
                    f"новых={stats['new_profiles']} уже_были={stats['existing_profiles']} "
                    f"в_очереди={stats['queued_usernames']} пропущено={stats['skipped_usernames']}"
                )
                self.refresh_dashboard()
                self.search_engine.invalidate()
            elif event_type == "profile_collected":
                user_id = int(event["user_id"])
                username = event.get("username") or "hidden"
                self._append_log(f"Realtime-профиль сохранен: @{username} (user_id={user_id}).")
                self.refresh_dashboard()
                self.search_engine.invalidate()
                self.show_profile_card(user_id)
                self.notebook.select(self.profile_tab)
            elif event_type == "search_results":
                self._show_search_results(event["results"], str(event.get("query", "")))
            elif event_type == "search_summary":
                self.search_summary_var.set(str(event.get("message", "")))
            elif event_type == "search_compare":
                self.search_compare_var.set(str(event.get("message", "")))
            elif event_type == "manual_sherlock_done":
                self._append_log(str(event.get("message", "")))
                self.refresh_dashboard()
                self.show_profile_card(int(event["user_id"]))
            elif event_type == "manual_enrichment_done":
                self._append_log(str(event.get("message", "")))
                self.refresh_dashboard()
                self.show_profile_card(int(event["user_id"]))
            elif event_type == "error":
                self._append_log(f"ОШИБКА: {event.get('message', '')}")
                self.refresh_dashboard()

            self.event_queue.task_done()

        self.after(200, self._drain_event_queue)

    def _build_security_tab(self) -> None:
        header = ttk.Frame(self.security_tab)
        header.pack(fill="x", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.security_summary_var, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Обновить анализ", command=self.refresh_security).grid(row=0, column=1, sticky="e")
        ttk.Button(header, text="Экспорт отчёта", command=self.export_security_report).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )
        ttk.Button(header, text="Показать граф связей", command=self.show_link_graph).grid(
            row=0, column=3, sticky="e", padx=(8, 0)
        )

        paned = ttk.PanedWindow(self.security_tab, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        ttk.Label(left, text="Профили с угрозами (высокий / средний риск)").pack(anchor="w")
        threat_columns = ("risk_level", "opsec_score", "first_name", "username", "threat_count", "osint_score")
        self.threat_tree = ttk.Treeview(left, columns=threat_columns, show="headings", height=12)
        for col, title, width in [
            ("risk_level", "Риск", 80),
            ("opsec_score", "OPSEC", 70),
            ("first_name", "Имя", 160),
            ("username", "Username", 150),
            ("threat_count", "Индикаторы", 90),
            ("osint_score", "OSINT", 70),
        ]:
            self.threat_tree.heading(col, text=title)
            self.threat_tree.column(col, width=width, anchor="w")
        self.threat_tree.pack(fill="both", expand=True, pady=(4, 8))
        self.threat_tree.tag_configure("high", background="#ffd5d5")
        self.threat_tree.tag_configure("medium", background="#fff3cc")
        self.threat_tree.tag_configure("analyst", background="#d5eaff")

        ttk.Label(left, text="Аномалии в наборе данных").pack(anchor="w", pady=(8, 0))
        self.anomaly_box = ScrolledText(left, height=8, wrap="word")
        self.anomaly_box.pack(fill="both", expand=True)
        self.anomaly_box.configure(state="disabled")

        ttk.Label(right, text="Распределение уровней риска").pack(anchor="w")
        self.risk_dist_box = ScrolledText(right, height=8, wrap="word")
        self.risk_dist_box.pack(fill="x", pady=(4, 8))
        self.risk_dist_box.configure(state="disabled")

        ttk.Label(right, text="Распределение OPSEC-баллов").pack(anchor="w")
        self.opsec_dist_box = ScrolledText(right, height=7, wrap="word")
        self.opsec_dist_box.pack(fill="x", pady=(4, 8))
        self.opsec_dist_box.configure(state="disabled")

        ttk.Label(right, text="Анализ графа связей").pack(anchor="w", pady=(8, 0))
        self.link_stats_box = ScrolledText(right, height=7, wrap="word")
        self.link_stats_box.pack(fill="x", pady=(4, 8))
        self.link_stats_box.configure(state="disabled")

        ttk.Label(right, text="Методология оценки угроз").pack(anchor="w", pady=(8, 0))
        methodology = (
            "Уровни риска:\n"
            "  high   — эксплойты, malware, darkweb, C2\n"
            "  medium — pentest, hacking, phishing, recon\n"
            "  analyst — bug bounty, SOC, threat intelligence\n"
            "  low    — угроз не обнаружено\n\n"
            "OPSEC-балл (0–100):\n"
            "  Высокий балл = минимальный след + privacy-инструменты.\n"
            "  Низкий балл = много аккаунтов + PII в bio.\n\n"
            "Аномалии:\n"
            "  Клоны/боты, аномальное количество аккаунтов,\n"
            "  раскрытые персональные данные."
        )
        method_box = ScrolledText(right, height=10, wrap="word")
        method_box.pack(fill="both", expand=True, pady=(4, 0))
        method_box.insert("1.0", methodology)
        method_box.configure(state="disabled")

        self.refresh_security()

    def refresh_security(self) -> None:
        try:
            profiles = database.get_search_dataset()
            if not profiles:
                with database.get_connection() as conn:
                    rows = conn.execute(
                        "SELECT user_id, first_name, username, bio, photo_path FROM profiles"
                    ).fetchall()
                profiles = [dict(r) for r in rows]
        except Exception:
            profiles = []

        snapshot = get_security_snapshot(profiles)

        self.security_summary_var.set(
            "Профилей: {total} | высокий риск: {high} | средний риск: {medium} | "
            "аналитики: {analyst} | аномалий: {anomalies} | PII-раскрытий: {pii}".format(
                total=snapshot["total"],
                high=snapshot["risk_distribution"].get("high", 0),
                medium=snapshot["risk_distribution"].get("medium", 0),
                analyst=snapshot["risk_distribution"].get("analyst", 0),
                anomalies=len(snapshot["anomalies"]),
                pii=snapshot["pii_exposed_count"],
            )
        )

        for item_id in self.threat_tree.get_children():
            self.threat_tree.delete(item_id)
        for t in snapshot["top_threats"]:
            username = f"@{t['username']}" if t["username"] != "[скрыт]" else "[скрыт]"
            tag = t["risk_level"] if t["risk_level"] in ("high", "medium", "analyst") else ""
            self.threat_tree.insert(
                "",
                "end",
                values=(
                    t["risk_level"],
                    t["opsec_score"],
                    t.get("first_name") or "",
                    username,
                    t["threat_count"],
                    t["osint_score"],
                ),
                tags=(tag,),
            )

        anomaly_lines = []
        for a in snapshot["anomalies"]:
            username = f"@{a['username']}" if a["username"] != "[скрыт]" else "[скрыт]"
            anomaly_lines.append(f"{username} (риск={a['risk_level']}, OPSEC={a['opsec_score']}):")
            for reason in a["anomaly_reasons"]:
                anomaly_lines.append(f"  • {reason}")
            anomaly_lines.append("")
        self.anomaly_box.configure(state="normal")
        self.anomaly_box.delete("1.0", "end")
        self.anomaly_box.insert("1.0", "\n".join(anomaly_lines) if anomaly_lines else "Аномалий не обнаружено.")
        self.anomaly_box.configure(state="disabled")

        risk_lines = []
        for level, count in sorted(snapshot["risk_distribution"].items()):
            bar = "█" * min(count, 40)
            risk_lines.append(f"{level:12s} {count:4d}  {bar}")
        self.risk_dist_box.configure(state="normal")
        self.risk_dist_box.delete("1.0", "end")
        self.risk_dist_box.insert("1.0", "\n".join(risk_lines) if risk_lines else "Нет данных.")
        self.risk_dist_box.configure(state="disabled")

        opsec_lines = []
        for bucket, count in snapshot["opsec_distribution"].items():
            bar = "█" * min(count, 40)
            opsec_lines.append(f"{bucket:22s} {count:4d}  {bar}")
        self.opsec_dist_box.configure(state="normal")
        self.opsec_dist_box.delete("1.0", "end")
        self.opsec_dist_box.insert("1.0", "\n".join(opsec_lines) if opsec_lines else "Нет данных.")
        self.opsec_dist_box.configure(state="disabled")

        try:
            self.link_graph_data = get_link_analysis()
        except Exception:
            self.link_graph_data = None
        self._refresh_link_stats()

    def _refresh_link_stats(self) -> None:
        data = self.link_graph_data
        if not data or not data.get("available"):
            text = "Граф недоступен: нет профилей или networkx не установлен."
        else:
            metrics = data["metrics"]
            bot_networks = data["bot_networks"]
            lines = [
                f"Узлов: {metrics['nodes']}  Рёбер: {metrics['edges']}",
                f"Компонент: {metrics['components']}  "
                f"Крупнейший: {metrics['largest_component']}  "
                f"Изолированных: {metrics['isolated_count']}",
            ]
            if metrics.get("bridge_nodes"):
                lines.append("Мосты: " + ", ".join(metrics["bridge_nodes"][:5]))
            if metrics.get("top_central"):
                top = metrics["top_central"][:3]
                lines.append(
                    "Центральные узлы: "
                    + ", ".join(f"{n['label']} (deg={n['degree_centrality']:.2f})" for n in top)
                )
            suspicious_count = sum(1 for c in metrics.get("clusters", []) if c.get("suspicious"))
            lines.append(f"Подозрительных кластеров: {suspicious_count}")
            if bot_networks:
                lines.append(f"Бот-сетей обнаружено: {len(bot_networks)}")
                for bn in bot_networks[:3]:
                    lines.append(
                        f"  Кластер {bn['cluster_id']}: {bn['size']} узлов, "
                        f"бот-доля={bn['bot_ratio']:.0%} — {bn['verdict']}"
                    )
            else:
                lines.append("Бот-сетей не обнаружено.")
            text = "\n".join(lines)
        self.link_stats_box.configure(state="normal")
        self.link_stats_box.delete("1.0", "end")
        self.link_stats_box.insert("1.0", text)
        self.link_stats_box.configure(state="disabled")

    def show_link_graph(self) -> None:
        data = self.link_graph_data
        if not data or not data.get("networkx_available"):
            messagebox.showinfo(
                "networkx недоступен",
                "Установите networkx для визуализации графа:\n  pip install networkx",
            )
            return
        if not data.get("available"):
            messagebox.showinfo("Граф пуст", "Нет профилей для построения графа.")
            return

        G = data["graph"]
        metrics = data.get("metrics", {})

        profile_risks: dict[int, str] = {}
        try:
            profiles = database.get_search_dataset() or []
            from security_analyzer import analyze_profile
            for p in profiles:
                result = analyze_profile(p)
                profile_risks[int(p["user_id"])] = result.get("risk_level", "unknown")
        except Exception:
            pass

        win = tk.Toplevel(self)
        win.title("Граф связей профилей")
        win.geometry("960x700")

        info_var = tk.StringVar(value=(
            f"Узлов: {metrics.get('nodes', 0)}  "
            f"Рёбер: {metrics.get('edges', 0)}  "
            f"Компонент: {metrics.get('components', 0)}  "
            f"Бот-сетей: {len(data.get('bot_networks', []))}"
        ))
        ttk.Label(win, textvariable=info_var, justify="left").pack(anchor="w", padx=10, pady=(8, 4))

        fig = Figure(figsize=(9.2, 6.2), dpi=100)
        ax = fig.add_subplot(111)
        draw_link_graph(G, ax, max_nodes=80, profile_risks=profile_risks)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def export_security_report(self) -> None:
        try:
            profiles = database.get_search_dataset()
            if not profiles:
                with database.get_connection() as conn:
                    rows = conn.execute(
                        "SELECT user_id, first_name, username, bio, photo_path FROM profiles"
                    ).fetchall()
                profiles = [dict(r) for r in rows]
        except Exception as exc:
            messagebox.showerror("Ошибка экспорта", str(exc))
            return
        path = export_security_report(profiles)
        self._append_log(f"Security-отчёт сохранён: {path}")

    def _on_close(self) -> None:
        self.shutdown_event.set()
        self.sherlock_queue.put(None)
        self.snoop_queue.put(None)
        self.maigret_queue.put(None)
        self.destroy()


def main() -> int:
    app = OSINTApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
