"""
OSINT Telegram Bot — поиск связей профилей через граф.

Запуск:
    .venv\\Scripts\\python.exe osint_bot.py --token YOUR_BOT_TOKEN

Переменная окружения (альтернатива флагу):
    OSINT_BOT_TOKEN=YOUR_BOT_TOKEN
"""
from __future__ import annotations

import argparse
import io
import logging
from typing import Any

import database
from config import env_first
from link_graph import (
    build_link_graph,
    compute_graph_metrics,
    detect_bot_networks,
    draw_link_graph,
)

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
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


# ---------------------------------------------------------------------------
# Helpers — загрузка данных и граф
# ---------------------------------------------------------------------------

def _load_graph_data() -> dict[str, Any]:
    """Загружает данные из БД и строит граф."""
    database.init_db()
    with database.get_connection() as conn:
        profiles = [dict(r) for r in conn.execute(
            "SELECT user_id, first_name, username, bio FROM profiles"
        ).fetchall()]
        group_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, group_name FROM user_groups"
        ).fetchall()]
        account_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, site_name FROM social_accounts"
        ).fetchall()]

    G = build_link_graph(profiles, group_rows, account_rows)
    metrics = compute_graph_metrics(G)
    bot_networks = detect_bot_networks(G, metrics)
    profile_map = {int(p["user_id"]): p for p in profiles}
    return {
        "G": G,
        "metrics": metrics,
        "bot_networks": bot_networks,
        "profiles": profile_map,
    }


def _find_node_by_username(G: Any, username: str) -> int | None:
    """Ищет узел по username (без @)."""
    username = username.lower().lstrip("@").strip()
    for node_id in G.nodes():
        node_username = (G.nodes[node_id].get("username") or "").lower()
        if node_username == username:
            return node_id
    return None


def _profile_line(G: Any, node_id: int, profiles: dict) -> str:
    label = G.nodes[node_id].get("label", str(node_id))
    p = profiles.get(node_id, {})
    first_name = (p.get("first_name") or "").strip()
    score = G.nodes[node_id].get("osint_score", 0)
    is_bot = "🤖 " if G.nodes[node_id].get("is_bot") else ""
    return f"{is_bot}{label} ({first_name}) OSINT={score}"


# ---------------------------------------------------------------------------
# Команды бота
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👁 *OSINT Graph Bot* — поиск связей профилей\n\n"
        "Команды:\n"
        "/whois @username — профиль и прямые связи\n"
        "/cluster @username — все участники кластера\n"
        "/bots — подозрительные бот-сети\n"
        "/top — топ центральных узлов\n"
        "/stats — общая статистика графа\n"
        "/graph — визуализация графа (PNG)\n"
        "/help — эта справка"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    m = data["metrics"]
    bn = data["bot_networks"]

    suspicious = sum(1 for c in m.get("clusters", []) if c.get("suspicious"))
    lines = [
        "📊 *Статистика графа*",
        f"Профилей: {m['nodes']}  Связей: {m['edges']}",
        f"Кластеров: {m['components']}  Крупнейший: {m['largest_component']}",
        f"Изолированных: {m['isolated_count']}",
        f"Подозрительных кластеров: {suspicious}",
        f"Бот-сетей: {len(bn)}",
    ]
    if m.get("bridge_nodes"):
        lines.append("Мосты: " + ", ".join(m["bridge_nodes"][:5]))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    top = data["metrics"].get("top_central", [])
    if not top:
        await update.message.reply_text("Граф пуст или недостаточно данных.")
        return

    lines = ["🏆 *Топ центральных профилей*", ""]
    for i, node in enumerate(top[:10], 1):
        lines.append(
            f"{i}. {node['label']}  "
            f"degree={node['degree_centrality']:.3f}  "
            f"between={node['betweenness']:.3f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
        await update.message.reply_text(f"Профиль @{username} не найден в базе данных.")
        return

    node = G.nodes[node_id]
    p = profiles.get(node_id, {})
    neighbors = list(G.neighbors(node_id))

    lines = [
        f"🔍 *@{username}*",
        f"Имя: {p.get('first_name') or '—'}",
        f"OSINT-балл: {node.get('osint_score', 0)}",
        f"Бот-паттерн: {'да 🤖' if node.get('is_bot') else 'нет'}",
        f"Прямых связей: {len(neighbors)}",
        "",
    ]

    if neighbors:
        lines.append("*Связанные профили:*")
        for nb in neighbors[:15]:
            edge = G[node_id][nb]
            edge_type = edge.get("edge_type", "group")
            weight = edge.get("weight", 1)
            groups = ", ".join(edge.get("groups", [])[:2])
            sites = ", ".join(edge.get("sites", [])[:2])
            via = f"группы: {groups}" if groups else ""
            via += ("; " if via and sites else "") + (f"сайты: {sites}" if sites else "")
            icon = "🔴" if "site" in edge_type else "⚪"
            lines.append(f"  {icon} {_profile_line(G, nb, profiles)}  [{via or edge_type}, w={weight:.0f}]")
        if len(neighbors) > 15:
            lines.append(f"  ... и ещё {len(neighbors) - 15}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
        await update.message.reply_text(f"Профиль @{username} не найден.")
        return

    # Найти кластер, содержащий этот узел
    cluster_info = None
    for cl in metrics.get("clusters", []):
        if node_id in cl["member_ids"]:
            cluster_info = cl
            break

    if cluster_info is None or cluster_info["size"] <= 1:
        await update.message.reply_text(
            f"@{username} изолирован — нет общих групп или доверенных сайтов с другими профилями."
        )
        return

    lines = [
        f"🕸 *Кластер профиля @{username}*",
        f"Участников: {cluster_info['size']}  "
        f"Связей: {cluster_info['edges']}  "
        f"Плотность: {cluster_info['density']}",
        f"Ботов в кластере: {cluster_info['bot_count']} ({cluster_info['bot_ratio']:.0%})",
        f"Подозрительный: {'⚠️ да' if cluster_info['suspicious'] else '✅ нет'}",
    ]
    if cluster_info["groups"]:
        lines.append("Общие группы: " + ", ".join(cluster_info["groups"][:5]))
    if cluster_info["sites"]:
        lines.append("Общие сайты: " + ", ".join(cluster_info["sites"][:5]))
    lines.append("")
    lines.append("*Участники:*")
    for member_id in cluster_info["member_ids"][:25]:
        marker = "➤ " if member_id == node_id else "   "
        lines.append(f"{marker}{_profile_line(G, member_id, profiles)}")
    if len(cluster_info["member_ids"]) > 25:
        lines.append(f"   ... и ещё {len(cluster_info['member_ids']) - 25}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_bots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = _load_graph_data()
    networks = data["bot_networks"]

    if not networks:
        await update.message.reply_text("✅ Подозрительных бот-сетей не обнаружено.")
        return

    lines = [f"🤖 *Обнаружено бот-сетей: {len(networks)}*", ""]
    for i, net in enumerate(networks[:5], 1):
        lines += [
            f"*Сеть #{i}* (кластер {net['cluster_id']})",
            f"Узлов: {net['size']}  Ботов: {net['bot_count']} ({net['bot_ratio']:.0%})",
            f"Плотность: {net['density']}",
            f"Вердикт: {net['verdict']}",
        ]
        if net["sample_bots"]:
            lines.append("Примеры: " + ", ".join(net["sample_bots"]))
        if net["groups"]:
            lines.append("Группы: " + ", ".join(net["groups"][:3]))
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_graph(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not MATPLOTLIB_OK:
        await update.message.reply_text("matplotlib не установлен — визуализация недоступна.")
        return

    await update.message.reply_text("⏳ Строю граф, подожди...")

    data = _load_graph_data()
    G = data["G"]
    metrics = data["metrics"]

    if not G or G.number_of_nodes() == 0:
        await update.message.reply_text("Граф пуст — нет данных для визуализации.")
        return

    # Строим риск-карту для цветов
    profile_risks: dict[int, str] = {}
    try:
        from security_analyzer import analyze_profile
        profiles_list = list(data["profiles"].values())
        for p in profiles_list:
            r = analyze_profile(p)
            profile_risks[int(p["user_id"])] = r.get("risk_level", "unknown")
    except Exception:
        pass

    fig = Figure(figsize=(10, 7), dpi=100)
    ax = fig.add_subplot(111)
    draw_link_graph(G, ax, max_nodes=80, profile_risks=profile_risks)

    m = metrics
    fig.suptitle(
        f"Узлов: {m['nodes']}  Рёбер: {m['edges']}  "
        f"Кластеров: {m['components']}  Бот-сетей: {len(data['bot_networks'])}",
        fontsize=9,
    )
    fig.tight_layout()

    canvas = FigureCanvasAgg(fig)
    buf = io.BytesIO()
    canvas.print_png(buf)
    buf.seek(0)

    await update.message.reply_photo(
        photo=buf,
        caption=(
            f"Граф связей: {m['nodes']} профилей, {m['edges']} связей\n"
            "🔴 высокий риск  🟠 средний  🔵 аналитик  🟢 низкий"
        ),
    )


# ---------------------------------------------------------------------------
# Текстовый fallback — поиск по username без команды
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text.startswith("@") or (text and not text.startswith("/")):
        context.args = [text.lstrip("@")]
        await cmd_whois(update, context)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

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
    app = build_app(args.token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
