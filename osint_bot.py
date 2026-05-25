"""
OSINT Telegram Bot — поиск связей профилей через граф.

Запуск:
    .venv\\Scripts\\python.exe osint_bot.py --token YOUR_BOT_TOKEN

Переменная окружения (альтернатива флагу):
    OSINT_BOT_TOKEN=YOUR_BOT_TOKEN
"""
from __future__ import annotations

import argparse
import asyncio
import html
import io
import logging
import time
from pathlib import Path
from typing import Any

import database
from config import env_first
from link_graph import (
    build_link_graph,
    compute_graph_metrics,
    detect_bot_networks,
    draw_link_graph,
    draw_interactive_graph,
)

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_OK = True
except ImportError:
    TELEGRAM_OK = False

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("osint_bot")

def _e(value: Any) -> str:
    """Экранирует строку для HTML-режима Telegram."""
    return html.escape(str(value or ""))

_GRAPH_CACHE: dict[str, Any] = {}
_GRAPH_CACHE_TS: float = 0.0
_GRAPH_TTL = 60.0

def _invalidate_graph_cache() -> None:
    global _GRAPH_CACHE_TS
    _GRAPH_CACHE_TS = 0.0

async def _reply_long(message: Any, text: str, **kwargs: Any) -> None:
    """Отправляет длинное сообщение, разбивая по 4000 символов."""
    MAX = 4000
    if len(text) <= MAX:
        await message.reply_text(text, **kwargs)
        return
    lines = text.split("\n")
    part: list[str] = []
    part_len = 0
    for line in lines:
        if part_len + len(line) + 1 > MAX and part:
            await message.reply_text("\n".join(part), **kwargs)
            part = []
            part_len = 0
        part.append(line)
        part_len += len(line) + 1
    if part:
        await message.reply_text("\n".join(part), **kwargs)

async def _fetch_profile_live(username: str) -> str | None:
    """Забирает профиль из Telegram и сохраняет в БД.
    Возвращает сообщение о статусе или None при ошибке.
    """
    session_file = Path("osint_session.session")
    if not session_file.exists():
        return "сессия Telethon не найдена — авторизуйся через десктопное приложение"
    try:
        from telegram_service import TelegramCollector
        collector = TelegramCollector(api_id="", api_hash="")
        await collector.collect_profile(username)
        _invalidate_graph_cache()
        return None
    except Exception as exc:
        log.warning("Live fetch failed for @%s: %s", username, exc)
        return str(exc)

def _load_graph_data() -> dict[str, Any]:
    """Загружает данные из БД и строит граф (кэш 60 с)."""
    global _GRAPH_CACHE, _GRAPH_CACHE_TS
    if _GRAPH_CACHE and (time.monotonic() - _GRAPH_CACHE_TS) < _GRAPH_TTL:
        return _GRAPH_CACHE

    database.init_db()
    with database.get_connection() as conn:
        profiles = [dict(r) for r in conn.execute(
            "SELECT user_id, first_name, username, bio FROM profiles"
        ).fetchall()]
        group_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, group_name FROM user_groups"
        ).fetchall()]
        account_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, site_name, profile_url FROM social_accounts"
        ).fetchall()]

    G = build_link_graph(profiles, group_rows, account_rows)
    metrics = compute_graph_metrics(G)
    bot_networks = detect_bot_networks(G, metrics)
    profile_map = {int(p["user_id"]): p for p in profiles}
    _GRAPH_CACHE = {
        "G": G,
        "metrics": metrics,
        "bot_networks": bot_networks,
        "profiles": profile_map,
    }
    _GRAPH_CACHE_TS = time.monotonic()
    return _GRAPH_CACHE

def _find_node_by_username(G: Any, username: str) -> int | None:
    """Ищет узел по username (без @)."""
    username = username.lower().lstrip("@").strip()
    for node_id in G.nodes():
        node_username = (G.nodes[node_id].get("username") or "").lower()
        if node_username == username:
            return node_id
    return None

def _profile_line(G: Any, node_id: int, profiles: dict) -> str:
    label = _e(G.nodes[node_id].get("label", str(node_id)))
    p = profiles.get(node_id, {})
    first_name = _e((p.get("first_name") or "").strip())
    score = G.nodes[node_id].get("osint_score", 0)
    is_bot = " " if G.nodes[node_id].get("is_bot") else ""
    return f"{is_bot}{label} ({first_name}) OSINT={score}"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        " <b>OSINT Graph Bot</b> — поиск связей профилей\n\n"
        "Команды:\n"
        "/whois @username — профиль и прямые связи\n"
        "/cluster @username — все участники кластера\n"
        "/bots — подозрительные бот-сети\n"
        "/top — топ центральных узлов\n"
        "/stats — общая статистика графа\n"
        "/graph — визуализация графа (PNG)\n"
        "/help — эта справка"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    m = data["metrics"]
    bn = data["bot_networks"]

    suspicious = sum(1 for c in m.get("clusters", []) if c.get("suspicious"))
    lines = [
        " <b>Статистика графа</b>",
        f"Профилей: {m['nodes']}  Связей: {m['edges']}",
        f"Кластеров: {m['components']}  Крупнейший: {m['largest_component']}",
        f"Изолированных: {m['isolated_count']}",
        f"Подозрительных кластеров: {suspicious}",
        f"Бот-сетей: {len(bn)}",
    ]
    if m.get("bridge_nodes"):
        lines.append("Мосты: " + ", ".join(_e(b) for b in m["bridge_nodes"][:5]))
    await _reply_long(update.message, "\n".join(lines), parse_mode="HTML")

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    top = data["metrics"].get("top_central", [])
    if not top:
        await update.message.reply_text("Граф пуст или недостаточно данных.")
        return

    lines = [" <b>Топ центральных профилей</b>", ""]
    for i, node in enumerate(top[:10], 1):
        lines.append(
            f"{i}. {_e(node['label'])}  "
            f"degree={node['degree_centrality']:.3f}  "
            f"between={node['betweenness']:.3f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_whois(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /whois @username")
        return

    username = args[0].lstrip("@").strip()
    data = _load_graph_data()
    G = data["G"]
    profiles = data["profiles"]

    node_id = _find_node_by_username(G, username)

    if node_id is None:
        await update.message.reply_text(
            f" @{_e(username)} не в базе — запрашиваю Telegram...",
            parse_mode="HTML",
        )
        err = await _fetch_profile_live(username)
        if err:
            await update.message.reply_text(
                f" Не удалось получить профиль: {_e(err)}", parse_mode="HTML"
            )
            return
        data = _load_graph_data()
        G = data["G"]
        profiles = data["profiles"]
        node_id = _find_node_by_username(G, username)

    if node_id is None:
        await update.message.reply_text(f"Профиль @{_e(username)} не найден в Telegram.")
        return

    node = G.nodes[node_id]
    p = profiles.get(node_id, {})
    neighbors = list(G.neighbors(node_id))

    lines = [
        f" <b>@{_e(username)}</b>",
        f"Имя: {_e(p.get('first_name') or '—')}",
        f"OSINT-балл: {node.get('osint_score', 0)}",
        f"Бот-паттерн: {'да ' if node.get('is_bot') else 'нет'}",
        f"Прямых связей: {len(neighbors)}",
        "",
    ]

    if neighbors:
        lines.append("<b>Связанные профили:</b>")
        for nb in neighbors[:15]:
            edge = G[node_id][nb]
            edge_type = edge.get("edge_type", "group")
            weight = edge.get("weight", 1)
            groups = ", ".join(_e(g) for g in edge.get("groups", [])[:2])
            sites = ", ".join(_e(s) for s in edge.get("sites", [])[:2])
            via = f"группы: {groups}" if groups else ""
            via += ("; " if via and sites else "") + (f"сайты: {sites}" if sites else "")
            icon = "" if "site" in edge_type else ""
            lines.append(
                f"  {icon} {_profile_line(G, nb, profiles)}"
                f"  [{via or _e(edge_type)}, w={weight:.0f}]"
            )
        if len(neighbors) > 15:
            lines.append(f"  ... и ещё {len(neighbors) - 15}")

    await _reply_long(update.message, "\n".join(lines), parse_mode="HTML")

async def cmd_cluster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /cluster @username")
        return

    username = args[0].lstrip("@").strip()
    data = _load_graph_data()
    G = data["G"]
    profiles = data["profiles"]
    metrics = data["metrics"]

    node_id = _find_node_by_username(G, username)
    if node_id is None:
        await update.message.reply_text(f"Профиль @{_e(username)} не найден.")
        return

    cluster_info = None
    for cl in metrics.get("clusters", []):
        if node_id in cl["member_ids"]:
            cluster_info = cl
            break

    if cluster_info is None or cluster_info["size"] <= 1:
        await update.message.reply_text(
            f"@{_e(username)} изолирован — нет общих групп или доверенных сайтов с другими профилями."
        )
        return

    lines = [
        f" <b>Кластер профиля @{_e(username)}</b>",
        f"Участников: {cluster_info['size']}  "
        f"Связей: {cluster_info['edges']}  "
        f"Плотность: {cluster_info['density']}",
        f"Ботов в кластере: {cluster_info['bot_count']} ({cluster_info['bot_ratio']:.0%})",
        f"Подозрительный: {' да' if cluster_info['suspicious'] else ' нет'}",
    ]
    if cluster_info["groups"]:
        lines.append("Общие группы: " + ", ".join(_e(g) for g in cluster_info["groups"][:5]))
    if cluster_info["sites"]:
        lines.append("Общие сайты: " + ", ".join(_e(s) for s in cluster_info["sites"][:5]))
    lines.append("")
    lines.append("<b>Участники:</b>")
    for member_id in cluster_info["member_ids"][:25]:
        marker = " " if member_id == node_id else "   "
        lines.append(f"{marker}{_profile_line(G, member_id, profiles)}")
    if len(cluster_info["member_ids"]) > 25:
        lines.append(f"   ... и ещё {len(cluster_info['member_ids']) - 25}")

    await _reply_long(update.message, "\n".join(lines), parse_mode="HTML")

async def cmd_bots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    networks = data["bot_networks"]

    if not networks:
        await update.message.reply_text(" Подозрительных бот-сетей не обнаружено.")
        return

    lines = [f" <b>Обнаружено бот-сетей: {len(networks)}</b>", ""]
    for i, net in enumerate(networks[:5], 1):
        lines += [
            f"<b>Сеть #{i}</b> (кластер {net['cluster_id']})",
            f"Узлов: {net['size']}  Ботов: {net['bot_count']} ({net['bot_ratio']:.0%})",
            f"Плотность: {net['density']}",
            f"Вердикт: {_e(net['verdict'])}",
        ]
        if net["sample_bots"]:
            lines.append("Примеры: " + ", ".join(_e(b) for b in net["sample_bots"]))
        if net["groups"]:
            lines.append("Группы: " + ", ".join(_e(g) for g in net["groups"][:3]))
        lines.append("")

    await _reply_long(update.message, "\n".join(lines), parse_mode="HTML")

async def cmd_graph(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Строю граф, подожди...")

    data = _load_graph_data()
    G = data["G"]
    metrics = data["metrics"]

    if not G or G.number_of_nodes() == 0:
        await update.message.reply_text("Граф пуст — нет данных для визуализации.")
        return

    profile_risks: dict[int, str] = {}
    try:
        from security_analyzer import analyze_profile
        for p in data["profiles"].values():
            r = analyze_profile(p)
            profile_risks[int(p["user_id"])] = r.get("risk_level", "unknown")
    except Exception:
        pass

    m = metrics

    try:
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        tmp.close()
        draw_interactive_graph(G, tmp.name, max_nodes=200, profile_risks=profile_risks)
        caption = (
            f"Интерактивный граф: {m['nodes']} профилей, {m['edges']} связей\n"
            f"Кластеров: {m['components']}  Крупнейший: {m['largest_component']}\n"
            "Открой HTML в браузере — узлы можно перетаскивать, зумить, наводить курсор"
        )
        with open(tmp.name, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="osint_graph.html",
                caption=caption,
            )
        os.unlink(tmp.name)
        return
    except Exception as exc:
        log.warning("Interactive graph failed: %s — falling back to PNG", exc)

    if not MATPLOTLIB_OK:
        await update.message.reply_text("matplotlib не установлен — визуализация недоступна.")
        return

    fig = Figure(figsize=(10, 7), dpi=100)
    ax = fig.add_subplot(111)
    draw_link_graph(G, ax, max_nodes=80, profile_risks=profile_risks)
    fig.suptitle(
        f"Узлов: {m['nodes']}  Рёбер: {m['edges']}  Кластеров: {m['components']}",
        fontsize=9,
    )
    fig.tight_layout()
    canvas = FigureCanvasAgg(fig)
    buf = io.BytesIO()
    canvas.print_png(buf)
    buf.seek(0)
    await update.message.reply_photo(
        photo=buf,
        caption=f"Граф связей: {m['nodes']} профилей, {m['edges']} связей",
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text.startswith("@") or (text and not text.startswith("/")):
        context.args = [text.lstrip("@")]
        await cmd_whois(update, context)

def build_app(token: str) -> "Application":
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("whois", cmd_whois))
    app.add_handler(CommandHandler("cluster", cmd_cluster))
    app.add_handler(CommandHandler("bots", cmd_bots))
    app.add_handler(CommandHandler("graph", cmd_graph))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app

def main() -> None:
    if not TELEGRAM_OK:
        raise SystemExit("python-telegram-bot не установлен. Запусти: pip install python-telegram-bot==21.*")

    parser = argparse.ArgumentParser(description="OSINT Graph Telegram Bot")
    parser.add_argument("--token", default=env_first("OSINT_BOT_TOKEN"), help="Telegram Bot Token")
    parser.add_argument("--db", default="", help="Путь к SQLite БД (опционально)")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit(
            "Укажи токен бота: --token YOUR_TOKEN  или  OSINT_BOT_TOKEN=YOUR_TOKEN"
        )

    if args.db:
        import database as db_module
        from pathlib import Path
        db_module.DB_PATH = Path(args.db)

    log.info("Starting OSINT Graph Bot...")
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = build_app(args.token)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
