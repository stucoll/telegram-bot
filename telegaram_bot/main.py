import asyncio
import os
import logging
import time
import random
import json
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest
import os
from dotenv import load_dotenv

# Загружаем переменные из .env (для локального запуска)
load_dotenv()

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv("8772403466:AAGn0Aoz2NMd0XAWrMiRLCzzHdeZSlHptaI")
ADMIN_CHAT_ID = os.getenv("-5121236231", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8772403466:AAGn0Aoz2NMd0XAWrMiRLCzzHdeZSlHptaI"
ADMIN_CHAT_ID = "-5121236231" 
WARN_LIMIT = 3
INACTIVE_DAYS = 30
DATA_FILE = "bot_data.json"

SPAM_WINDOW = 120
SPAM_LIMIT = 5
SPAM_MUTE_DURATION = 600
spam_tracker = defaultdict(list)

REP_COOLDOWN = 60
rep_cooldowns = {}

WHOIS_ROLES = ["🎮 Геймер", "☕ Кофеман", "🌙 Сова", "📚 Книжный червь", "🎵 Меломан", "🍕 Пицца-любитель", "😴 Соня", "🚀 Мечтатель", "🎭 Актер", "💻 Кодер", "🎨 Художник", "🐾 Любитель котов", "🏋️ Спортсмен", "🌍 Путешественник", "👾 Гик", "🌟 Звезда чата"]

router = Router()

# ==================== ХРАНИЛИЩЕ (JSON) ====================
data = {"warnings": {}, "reputation": {}, "message_stats": {}, "user_joins": {}, "nicknames": {}}

def load_data():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for k in data:
                    if k in loaded: data[k] = loaded[k]
        except: pass
    save_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_warns(chat_id, user_id): return data["warnings"].get(f"{chat_id}_{user_id}", 0)
def add_warn(chat_id, user_id):
    k = f"{chat_id}_{user_id}"; data["warnings"][k] = data["warnings"].get(k, 0) + 1; save_data(); return data["warnings"][k]
def reset_warns(chat_id, user_id):
    k = f"{chat_id}_{user_id}"
    if k in data["warnings"]: del data["warnings"][k]; save_data()

def get_rep(chat_id, user_id): return data["reputation"].get(f"{chat_id}_{user_id}", 0)
def change_rep(chat_id, user_id, delta):
    k = f"{chat_id}_{user_id}"; data["reputation"][k] = data["reputation"].get(k, 0) + delta; save_data(); return data["reputation"][k]

def set_nickname(chat_id, user_id, nick): data["nicknames"][f"{chat_id}_{user_id}"] = nick.strip(); save_data()
def del_nickname(chat_id, user_id):
    k = f"{chat_id}_{user_id}"
    if k in data["nicknames"]: del data["nicknames"][k]; save_data()

def get_display_name(chat_id, user_id, fallback=""):
    k = f"{chat_id}_{user_id}"
    return data["nicknames"].get(k, fallback or "").strip() or (fallback or f"User {user_id}")

def increment_msg_count(chat_id, user_id):
    k = f"{chat_id}_{user_id}"; now = int(time.time())
    if k not in data["message_stats"]: data["message_stats"][k] = {"count": 0, "last_active": now}
    data["message_stats"][k]["count"] += 1; data["message_stats"][k]["last_active"] = now
    if k not in data["user_joins"]: data["user_joins"][k] = now
    save_data()

# ==================== ПРОВЕРКИ ====================
async def is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except: return False

async def has_restrict_rights(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator") and getattr(member, "can_restrict_members", False)
    except: return False

def parse_duration(duration_str: str) -> int:
    if not duration_str: return int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    units = {"m": 60, "h": 3600, "d": 86400}
    unit = duration_str[-1].lower()
    try:
        value = int(duration_str[:-1])
        return int((datetime.utcnow() + timedelta(seconds=units.get(unit, value))).timestamp())
    except: return int((datetime.utcnow() + timedelta(hours=1)).timestamp())

# ==================== АНТИСПАМ ====================
async def check_anti_spam(message: Message):
    if message.from_user.is_bot: return
    key = (message.chat.id, message.from_user.id)
    now = time.time()
    msg_text = message.text.strip() if message.text else None
    if not msg_text: return

    spam_tracker[key] = [m for m in spam_tracker[key] if now - m["ts"] < SPAM_WINDOW]
    identical_count = sum(1 for m in spam_tracker[key] if m["text"] == msg_text)

    if identical_count > SPAM_LIMIT:
        until = int(now + SPAM_MUTE_DURATION)
        perms = ChatPermissions(can_send_messages=False)
        try:
            await message.bot.restrict_chat_member(message.chat.id, message.from_user.id, perms, until_date=until)
            name = get_display_name(message.chat.id, message.from_user.id, message.from_user.full_name)
            await message.answer(f"🚫 <b>Антиспам!</b>\n{name} замучен на 10 мин.", parse_mode="HTML")
        except: pass
        spam_tracker[key] = []
    else:
        spam_tracker[key].append({"text": msg_text, "ts": now})

# ==================== ТОПЫ ====================
async def get_top_formatted(bot: Bot, chat_id: int, category: str, limit: int = 5) -> str:
    now = int(time.time())
    prefix = f"{chat_id}_"
    
    if category == "rep":
        items = [(int(k.split("_")[1]), v) for k, v in data["reputation"].items() if k.startswith(prefix)]
        title, fmt = "🏆 Топ репутации:", str
    elif category == "msg":
        items = [(int(k.split("_")[1]), v["count"]) for k, v in data["message_stats"].items() if k.startswith(prefix)]
        title, fmt = "📝 Топ сообщений:", lambda v: f"{v} соо."
    elif category == "days":
        items = [(int(k.split("_")[1]), now - v) for k, v in data["user_joins"].items() if k.startswith(prefix)]
        title, fmt = "📅 Топ по дням:", lambda v: f"{v // 86400} дн."
    else: return "❌ Ошибка"

    items.sort(key=lambda x: x[1], reverse=(category != "days"))
    items = items[:limit]
    if not items: return "📭 Нет данных"

    text = f"{title}\n"
    for i, (uid, val) in enumerate(items, 1):
        text += f"{i}. {get_display_name(chat_id, uid)}: {fmt(val)}\n"
    return text

# ==================== ОБРАБОТЧИКИ ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Бот для модерации. Используйте /help")

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>📋 Команды (Паттерн + добавляет / - удаляет):</b>\n\n"
        "<b>Админ:</b>\n"
        "<code>+бан / -бан</code> - забанить / разбанить\n"
        "<code>+мут [время] / -мут</code> - замутить / размутить\n"
        "<code>+варн / -варн</code> - выдать предупреждение / снять\n"
        "<code>+чат / -чат</code> - открыть чат / закрыть чат (молчанка)\n\n"
        "<b>Все:</b>\n"
        "<code>+ник имя / -ник</code> - установить ник / удалить ник\n"
        "<code>+реп / -реп</code> - дать репутацию / забрать (ответом)\n"
        "<code>!репорт причина</code> - жалоба на нарушение (ответом)\n"
        "<code>!топ [реп|соо|дней]</code> - топы участников\n"
        "<code>!кто я / !кто ты</code> - случайная роль\n"
        "<code>!неактив</code> - список неактивных\n"
        "<code>!админы</code> - призыв администрации\n"
        "<code>!внимание</code> - объявление для всех\n\n"
        "🛡️ Антиспам: 5+ одинаковых сообщений = мут 10 мин",
        parse_mode="HTML"
    )

# --- ЗАКРЫТИЕ/ОТКРЫТИЕ ЧАТА (ИСПРАВЛЕНО) ---
@router.message(Command("чат", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_chat(message: Message):
    if not await is_group_admin(message.bot, message.chat.id, message.from_user.id):
        return await message.answer("🔒 Только администраторы могут управлять чатом.")

    is_open = message.text.strip().startswith("+")
    try:
        if is_open:
            # 🔓 Полностью открываем чат - разрешаем ВСЕ типы сообщений
            await message.bot.set_chat_permissions(
                message.chat.id,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                )
            )
            await message.answer("🔓 <b>Чат открыт!</b>\nВсе пользователи снова могут писать.", parse_mode="HTML")
        else:
            # 🔒 Закрываем чат - запрещаем ВСЕ типы сообщений
            await message.bot.set_chat_permissions(
                message.chat.id,
                ChatPermissions(
                    can_send_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=True,
                    can_pin_messages=False
                )
            )
            await message.answer("🔒 <b>Чат закрыт!</b>\nОбычные пользователи не могут писать.", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# --- РЕПОРТ ---
@router.message(Command("репорт", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_report(message: Message):
    if not message.reply_to_message:
        return await message.answer("❌ Ответьте на сообщение нарушителя.")
    parts = message.text.strip().split(maxsplit=1)
    reason = parts[1] if len(parts) > 1 else None
    if not reason:
        return await message.answer("❌ Укажите причину! Пример: <code>!репорт спам</code>", parse_mode="HTML")
    violator, reporter = message.reply_to_message.from_user, message.from_user
    if violator.is_bot: return await message.answer("❌ Нельзя жаловаться на ботов.")
    v_name = get_display_name(message.chat.id, violator.id, violator.full_name)
    r_name = get_display_name(message.chat.id, reporter.id, reporter.full_name)
    admin_text = f"🚨 <b>Жалоба!</b>\n👤 Нарушитель: {v_name}\n📢 От: {r_name}\n📝 Причина: {reason}"
    await message.answer("✅ Жалоба отправлена администрации.")
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID != "":
        try:
            await message.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="HTML")
            await message.reply_to_message.forward(ADMIN_CHAT_ID)
        except Exception as e: logging.error(f"Ошибка репорта: {e}")

# --- НИК (+ устанавливает / - удаляет) ---
@router.message(Command("ник", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_nick(message: Message, command: CommandObject):
    is_add = message.text.strip().startswith("+")
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if is_add:
        nick = command.args.strip()
        if not nick: return await message.answer("❌ Укажите ник: <code>+ник Имя</code>", parse_mode="HTML")
        set_nickname(message.chat.id, target.id, nick)
        await message.answer(f"✅ Ник установлен: <b>{nick}</b>", parse_mode="HTML")
    else:
        del_nickname(message.chat.id, target.id)
        await message.answer("✅ Ник удален")

# --- БАН (+ банит / - разбанивает) ---
@router.message(Command("бан", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_ban(message: Message, command: CommandObject):
    if not await has_restrict_rights(message.bot, message.chat.id, message.from_user.id):
        return await message.answer("🔒 Только админы с правами")
    if not message.reply_to_message: return await message.answer("❌ Ответьте на сообщение")
    target = message.reply_to_message.from_user
    if target.is_bot: return await message.answer("❌ Нельзя банить ботов")
    if await is_group_admin(message.bot, message.chat.id, target.id): return await message.answer("⛔ Нельзя банить админов")
    try:
        if message.text.strip().startswith("+"):
            await message.bot.ban_chat_member(message.chat.id, target.id)
            await message.answer(f"🔨 <b>{get_display_name(message.chat.id, target.id, target.full_name)}</b> забанен", parse_mode="HTML")
        else:
            await message.bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
            await message.answer("✅ Разбанен")
    except Exception as e: await message.answer(f"❌ {e}")

# --- МУТ (+ мутит / - размучивает) ---
@router.message(Command("мут", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_mute(message: Message, command: CommandObject):
    if not await has_restrict_rights(message.bot, message.chat.id, message.from_user.id):
        return await message.answer("🔒 Только админы с правами")
    if not message.reply_to_message: return await message.answer("❌ Ответьте на сообщение")
    target = message.reply_to_message.from_user
    if target.is_bot: return await message.answer("❌ Нельзя мутить ботов")
    if await is_group_admin(message.bot, message.chat.id, target.id): return await message.answer("⛔ Нельзя мутить админов")
    if message.text.strip().startswith("+"):
        args = command.args.strip().split()
        until = parse_duration(args[0] if args else "1h")
        try:
            await message.bot.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False), until_date=until)
            await message.answer(f"🔇 <b>{get_display_name(message.chat.id, target.id, target.full_name)}</b> замучен", parse_mode="HTML")
        except Exception as e: await message.answer(f"❌ {e}")
    else:
        full = ChatPermissions(can_send_messages=True, can_send_polls=True, can_add_web_page_previews=True, can_send_other_messages=True, can_invite_users=True)
        await message.bot.restrict_chat_member(message.chat.id, target.id, full)
        await message.answer("🔊 Размучен")

# --- ВАРН (+ варнит / - снимает) ---
@router.message(Command("варн", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_warn(message: Message, command: CommandObject):
    if not await has_restrict_rights(message.bot, message.chat.id, message.from_user.id):
        return await message.answer("🔒 Только админы с правами")
    if not message.reply_to_message: return await message.answer("❌ Ответьте на сообщение")
    target = message.reply_to_message.from_user
    if target.is_bot: return await message.answer("❌ Нельзя варнить ботов")
    if await is_group_admin(message.bot, message.chat.id, target.id): return await message.answer("⛔ Нельзя варнить админов")
    name = get_display_name(message.chat.id, target.id, target.full_name)
    if message.text.strip().startswith("+"):
        count = add_warn(message.chat.id, target.id)
        if count >= WARN_LIMIT:
            await message.bot.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False))
            await message.answer(f"⚠️ {name}: {count}/{WARN_LIMIT}\n🔇 Авто-мут", parse_mode="HTML")
        else:
            await message.answer(f"⚠️ {name}: {count}/{WARN_LIMIT}", parse_mode="HTML")
    else:
        reset_warns(message.chat.id, target.id)
        await message.answer(f"✅ Варны сняты с {name}")

# --- РЕПУТАЦИЯ (+ дает / - забирает) ---
@router.message(Command("реп", prefix=["+", "-"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_rep(message: Message, command: CommandObject):
    if not message.reply_to_message: return await message.answer("❌ Ответьте на сообщение")
    target = message.reply_to_message.from_user
    if target.is_bot: return await message.answer("❌ Только людям")
    if target.id == message.from_user.id: return await message.answer("❌ Нельзя себе")
    now = time.time()
    for k in list(rep_cooldowns.keys()):
        if now - rep_cooldowns[k] >= REP_COOLDOWN: del rep_cooldowns[k]
    key = (message.chat.id, message.from_user.id)
    if key in rep_cooldowns:
        return await message.answer(f"⏳ Кулдаун: {int(REP_COOLDOWN - (now - rep_cooldowns[key]))} сек")
    rep_cooldowns[key] = now
    delta = 1 if message.text.strip().startswith("+") else -1
    new_rep = change_rep(message.chat.id, target.id, delta)
    await message.answer(f"{'👍 +1' if delta > 0 else '👎 -1'} {get_display_name(message.chat.id, target.id, target.full_name)}: {new_rep}")

# --- ТОПЫ ---
@router.message(Command("топ", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_top(message: Message):
    parts = message.text.split()
    arg = parts[1].lower() if len(parts) > 1 else "реп"
    mapping = {"реп": "rep", "соо": "msg", "дней": "days"}
    cat = mapping.get(arg, "rep")
    await message.answer(await get_top_formatted(message.bot, message.chat.id, cat))

# --- КТО Я / КТО ТЫ ---
@router.message(Command("кто", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_who(message: Message):
    text = message.text.lower()
    if "я" in text: target = message.from_user
    elif "ты" in text:
        if not message.reply_to_message: return await message.answer("❌ Ответьте на сообщение")
        target = message.reply_to_message.from_user
    else: return
    role = random.choice(WHOIS_ROLES)
    confidence = random.randint(65, 100)
    await message.answer(f"🔮 <b>{get_display_name(message.chat.id, target.id, target.full_name)}</b> — это {role}!\n📊 Уверенность: {confidence}%", parse_mode="HTML")

# --- НЕАКТИВ ---
@router.message(Command("неактив", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_inactive(message: Message):
    now = int(time.time())
    prefix = f"{message.chat.id}_"
    inactive = [(int(k.split("_")[1]), now - v["last_active"]) for k, v in data["message_stats"].items() if k.startswith(prefix) and (now - v["last_active"]) // 86400 >= INACTIVE_DAYS]
    inactive.sort(key=lambda x: x[1], reverse=True)
    if not inactive: return await message.answer(f"✅ Все активны за {INACTIVE_DAYS} дней!")
    text = f"💤 <b>Неактивы (>{INACTIVE_DAYS} дн.):</b>\n"
    for i, (uid, sec) in enumerate(inactive[:15], 1):
        text += f"{i}. {get_display_name(message.chat.id, uid)} — {sec // 86400} дн.\n"
    await message.answer(text, parse_mode="HTML")

# --- АДМИНЫ ---
@router.message(Command("админы", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_admins(message: Message):
    try:
        admins = await message.bot.get_chat_administrators(message.chat.id)
        mentions = [f'<a href="tg://user?id={a.user.id}">{a.user.full_name}</a>' for a in admins if not a.user.is_bot]
        if not mentions: return await message.answer("❌ Нет админов")
        await message.answer(" ".join(mentions) + "\n\n📢 Внимание!", parse_mode="HTML")
    except Exception as e: await message.answer(f"❌ {e}")

# --- ВНИМАНИЕ ---
@router.message(Command("внимание", prefix=["!"]), F.chat.type.in_(["group", "supergroup"]))
async def cmd_all(message: Message):
    await message.answer("📢 <b>ВНИМАНИЕ ВСЕМ!</b>\n\nОбратите внимание!", parse_mode="HTML")

# --- ОБРАБОТКА СООБЩЕНИЙ ---
@router.message(F.new_chat_members & F.chat.type.in_(["group", "supergroup"]))
async def on_join(message: Message):
    for user in message.new_chat_members:
        if not user.is_bot: increment_msg_count(message.chat.id, user.id)

@router.message(F.text & F.chat.type.in_(["group", "supergroup"]))
async def handle_text(message: Message):
    if not message.text.startswith("/") and not message.text.startswith("!") and not message.text.startswith("+") and not message.text.startswith("-"):
        increment_msg_count(message.chat.id, message.from_user.id)
        await check_anti_spam(message)

# ==================== ЗАПУСК ====================
async def main():
    load_data()
    if BOT_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН":
        logging.error("❌ ВСТАВЬТЕ ТОКЕН!")
        return
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    logging.info("🤖 Бот запущен...")
    try: await dp.start_polling(bot)
    except KeyboardInterrupt: logging.info("🛑 Остановка")
    finally: await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())