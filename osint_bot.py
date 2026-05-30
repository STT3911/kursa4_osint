from __future__ import annotations

import argparse
import asyncio
import functools
import html
import io
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

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

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

def _load_allowed_users() -> set[int]:
    raw = env_first("OSINT_BOT_ALLOWED_USERS", "OSINT_BOT_ADMINS")
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip().lstrip("@")
        if part.isdigit():
            ids.add(int(part))
    return ids

_ALLOWED_USERS: set[int] = _load_allowed_users()

def _user_is_allowed(update: "Update") -> bool:

    if not _ALLOWED_USERS:
        return True
    user = getattr(update, "effective_user", None)
    return bool(user and user.id in _ALLOWED_USERS)

def restricted(
    handler: "Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]",
) -> "Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]":

    @functools.wraps(handler)
    async def wrapper(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
        if not _user_is_allowed(update):
            user = getattr(update, "effective_user", None)
            log.warning(
                "Отклонён неавторизованный доступ: user_id=%s username=%s",
                getattr(user, "id", None),
                getattr(user, "username", None),
            )
            if getattr(update, "message", None):
                await update.message.reply_text(
                    " Доступ запрещён. Обратитесь к владельцу бота."
                )
            return
        await handler(update, context)

    return wrapper

def _valid_lookup(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))

def _e(value: Any) -> str:
    return html.escape(str(value or ""))

def _estimate_reg_date(user_id: int) -> str:
    from datetime import date
    CHECKPOINTS = [
        (100_000_000,  date(2014, 6, 1)),
        (500_000_000,  date(2019, 1, 1)),
        (1_000_000_000, date(2020, 2, 1)),
        (1_500_000_000, date(2020, 10, 1)),
        (2_000_000_000, date(2021, 5, 1)),
        (2_500_000_000, date(2021, 11, 1)),
        (3_000_000_000, date(2022, 2, 1)),
        (4_000_000_000, date(2022, 5, 1)),
        (5_000_000_000, date(2022, 7, 1)),
        (6_000_000_000, date(2022, 12, 1)),
        (7_000_000_000, date(2023, 7, 1)),
        (7_700_000_000, date(2024, 1, 1)),
        (8_500_000_000, date(2024, 6, 1)),
        (9_000_000_000, date(2024, 10, 1)),
    ]
    if user_id <= 0:
        return "неизвестно"
    for i in range(len(CHECKPOINTS) - 1):
        lo_id, lo_date = CHECKPOINTS[i]
        hi_id, hi_date = CHECKPOINTS[i + 1]
        if lo_id <= user_id < hi_id:
            frac = (user_id - lo_id) / (hi_id - lo_id)
            lo_days = (lo_date - date(2013, 1, 1)).days
            hi_days = (hi_date - date(2013, 1, 1)).days
            est_days = int(lo_days + frac * (hi_days - lo_days))
            from datetime import timedelta
            est = date(2013, 1, 1) + timedelta(days=est_days)
            return f"{est.month}.{est.year}"
    if user_id < CHECKPOINTS[0][0]:
        return "до 2014"
    return f">= {CHECKPOINTS[-1][1].year}"

_GRAPH_CACHE: dict[str, Any] = {}
_GRAPH_CACHE_TS: float = 0.0
_GRAPH_TTL = 60.0

def _invalidate_graph_cache() -> None:
    global _GRAPH_CACHE_TS
    _GRAPH_CACHE_TS = 0.0

async def _reply_long(message: Any, text: str, **kwargs: Any) -> None:
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
    session_file = Path("osint_session.session")
    if not session_file.exists():
        return "сессия Telethon не найдена — авторизуйся через десктопное приложение"
    try:
        from config import env_first, load_env_file
        load_env_file()
        api_id = env_first("TELEGRAM_API_ID", "TG_API_ID")
        api_hash = env_first("TELEGRAM_API_HASH", "TG_API_HASH")
        if not api_id or not api_hash:
            return "TELEGRAM_API_ID / TELEGRAM_API_HASH не заданы в .env"

        try:
            from telethon import TelegramClient
            from telethon.errors import FloodWaitError, ChatAdminRequiredError
            from telethon.tl.functions.messages import GetCommonChatsRequest
            from telethon.tl.types import PeerUser
        except ImportError:
            return "telethon не установлен"

        client = TelegramClient("osint_session", int(api_id), api_hash)
        await client.start()
        try:
            user = await client.get_entity(username)
            uid = user.id

            database.save_profile(
                user_id=uid,
                first_name=getattr(user, "first_name", "") or "",
                username=getattr(user, "username", "") or "",
                bio=getattr(user, "about", "") or "",
                photo_path="",
            )

            try:
                result = await client(GetCommonChatsRequest(user_id=user, max_id=0, limit=100))
                common_chats = result.chats
            except Exception as e:
                log.warning("GetCommonChatsRequest failed: %s", e)
                common_chats = []

            log.info("@%s: найдено %d общих групп", username, len(common_chats))

            if not common_chats:
                log.info("@%s: общих групп нет — сканирую собственные диалоги сессии", username)
                try:
                    from telethon.tl.types import Channel, Chat as TLChat
                    from telethon.errors import UserNotParticipantError
                    async for dialog in client.iter_dialogs(limit=50):
                        entity = dialog.entity
                        if not isinstance(entity, (Channel, TLChat)):
                            continue
                        try:
                            perms = await client.get_permissions(entity, user)
                            if perms is not None:
                                common_chats.append(entity)
                                log.info("Нашёл @%s в группе %s", username, dialog.name)
                        except UserNotParticipantError:
                            pass
                        except Exception:
                            pass
                    log.info("@%s: после сканирования диалогов — %d групп", username, len(common_chats))
                except Exception as e:
                    log.warning("Сканирование диалогов не удалось: %s", e)

            for chat in common_chats[:10]:
                chat_title = getattr(chat, "title", None) or str(chat.id)
                chat_uname = getattr(chat, "username", None)
                group_label = f"@{chat_uname}" if chat_uname else chat_title

                try:
                    async for member in client.iter_participants(chat, limit=500):
                        if getattr(member, "bot", False):
                            continue
                        database.save_profile(
                            user_id=member.id,
                            first_name=getattr(member, "first_name", "") or "",
                            username=getattr(member, "username", "") or "",
                            bio="",
                            photo_path="",
                        )
                        database.link_user_group(member.id, group_label)
                    log.info("Собрана группа %s", group_label)
                except FloodWaitError as e:
                    await asyncio.sleep(min(e.seconds, 30))
                except ChatAdminRequiredError:
                    log.warning("Нет прав участников в %s", group_label)
                except Exception as e:
                    log.warning("Не удалось собрать %s: %s", group_label, e)

                try:
                    async for msg in client.iter_messages(chat, from_user=user, limit=100):
                        if msg.fwd_from:
                            fwd_peer = getattr(msg.fwd_from, "from_id", None)
                            if isinstance(fwd_peer, PeerUser) and fwd_peer.user_id != uid:
                                database.save_interaction(
                                    from_user_id=uid,
                                    to_user_id=fwd_peer.user_id,
                                    interaction_type="forward",
                                    group_id=chat.id,
                                    group_name=group_label,
                                )
                        if msg.reply_to and msg.reply_to.reply_to_msg_id:
                            try:
                                orig = await client.get_messages(
                                    chat, ids=msg.reply_to.reply_to_msg_id
                                )
                                if orig and orig.sender_id and orig.sender_id != uid:
                                    database.save_interaction(
                                        from_user_id=uid,
                                        to_user_id=orig.sender_id,
                                        interaction_type="reply",
                                        group_id=chat.id,
                                        group_name=group_label,
                                    )
                            except Exception:
                                pass
                except Exception as e:
                    log.warning("Не удалось просканировать сообщения %s: %s", group_label, e)

        finally:
            await client.disconnect()

        _invalidate_graph_cache()
        return None
    except Exception as exc:
        log.warning("Live fetch failed for @%s: %s", username, exc)
        return str(exc)

def _load_graph_data() -> dict[str, Any]:
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
        try:
            interaction_rows = [dict(r) for r in conn.execute(
                "SELECT from_user_id, to_user_id, interaction_type FROM message_interactions"
            ).fetchall()]
        except Exception:
            interaction_rows = []

    G = build_link_graph(profiles, group_rows, account_rows, interaction_rows)
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

@restricted
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

@restricted
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

@restricted
async def cmd_whois(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /whois @username")
        return

    username = args[0].lstrip("@").strip()
    if not _valid_lookup(username):
        await update.message.reply_text(
            "Некорректный username. Допустимы латиница, цифры и подчёркивание (до 64 символов)."
        )
        return
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

    p = profiles.get(node_id, {})
    uname = _e(p.get("username") or username)
    reg_date = _estimate_reg_date(node_id)
    name_history = database.get_profile_names(node_id)
    neighbors = list(G.neighbors(node_id))

    with database.get_connection() as conn:
        _INTERNAL = {"direct_lookup", "direct lookup", ""}
        group_names = [
            r[0] for r in conn.execute(
                "SELECT group_name FROM user_groups WHERE user_id = ? ORDER BY parsed_at",
                (node_id,),
            ).fetchall()
            if r[0] not in _INTERNAL
        ]

    lines = [
        f" <b>{node_id}</b> | @{uname}",
        f" Месяц регистрации: {reg_date}",
        "",
    ]

    if name_history:
        lines.append(" <b>История имён:</b>")
        for i, name in enumerate(name_history, 1):
            lines.append(f"{i}. {_e(name)}")
        lines.append("")

    if neighbors:
        shown = neighbors[:20]
        lines.append(f" <b>Знакомые ({len(shown)} из {len(neighbors)}):</b>")
        for nb in shown:
            nb_p = profiles.get(nb, {})
            nb_name = _e((nb_p.get("first_name") or "").strip() or str(nb))
            nb_uname = (nb_p.get("username") or "").strip()
            if nb_uname:
                lines.append(f"- {nb_name} (https://t.me/{_e(nb_uname)}) [{nb}]")
            else:
                lines.append(f"- {nb_name} [{nb}]")
        lines.append("")

    lines.append(f" Количество групп: {len(group_names)}")

    if group_names:
        lines.append("")
        lines.append("Группы:")
        for gname in group_names:
            clean = gname.lstrip("@")
            lines.append(f"- {_e(clean)} {'@' + _e(clean) if not gname.startswith('@') else ''}")

    await _reply_long(update.message, "\n".join(lines), parse_mode="HTML")

@restricted
async def cmd_cluster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /cluster @username")
        return

    username = args[0].lstrip("@").strip()
    if not _valid_lookup(username):
        await update.message.reply_text(
            "Некорректный username. Допустимы латиница, цифры и подчёркивание (до 64 символов)."
        )
        return
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

@restricted
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

@restricted
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

@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text.startswith("@") or (text and not text.startswith("/")):
        context.args = [text.lstrip("@")]
        await cmd_whois(update, context)

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.from_user:
        return

    sender = msg.from_user
    chat = msg.chat
    group_id = chat.id
    group_name = chat.username or chat.title or str(group_id)

    database.save_profile(
        user_id=sender.id,
        first_name=sender.first_name or "",
        username=sender.username or "",
        bio="",
        photo_path="",
    )
    database.link_user_group(sender.id, group_name)
    _invalidate_graph_cache()

    if msg.forward_origin:
        try:
            fwd_user = getattr(msg.forward_origin, "sender_user", None)
            if fwd_user and fwd_user.id != sender.id:
                database.save_profile(
                    user_id=fwd_user.id,
                    first_name=fwd_user.first_name or "",
                    username=fwd_user.username or "",
                    bio="",
                    photo_path="",
                )
                database.save_interaction(
                    from_user_id=sender.id,
                    to_user_id=fwd_user.id,
                    interaction_type="forward",
                    group_id=group_id,
                    group_name=group_name,
                )
        except Exception:
            pass

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.id != sender.id:
            database.save_profile(
                user_id=target.id,
                first_name=target.first_name or "",
                username=target.username or "",
                bio="",
                photo_path="",
            )
            database.save_interaction(
                from_user_id=sender.id,
                to_user_id=target.id,
                interaction_type="reply",
                group_id=group_id,
                group_name=group_name,
            )

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, handle_group_message))
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

    if not _ALLOWED_USERS:
        log.warning(
            "OSINT_BOT_ALLOWED_USERS не задан — бот отвечает ВСЕМ пользователям. "
            "Укажи список Telegram ID в .env, чтобы ограничить доступ."
        )
    else:
        log.info("Доступ к командам разрешён только для: %s", sorted(_ALLOWED_USERS))

    log.info("Starting OSINT Graph Bot...")
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = build_app(args.token)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
