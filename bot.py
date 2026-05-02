# -*- coding: utf-8 -*-
import os
import base64
import json
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from pymongo import MongoClient

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

ADMIN_ID = 374697317

print("TOKEN:", TELEGRAM_TOKEN[:10] if TELEGRAM_TOKEN else "NOT FOUND")
print("API KEY:", ANTHROPIC_API_KEY[:10] if ANTHROPIC_API_KEY else "NOT FOUND")
print("MONGO:", "connected" if MONGO_URI else "NOT FOUND")

client = MongoClient(MONGO_URI)
db = client["calorie_bot"]
users_col = db["users"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Буфер для групових фото
media_group_buffer = {}


# ============================================================
# РОБОТА З БАЗОЮ ДАНИХ
# ============================================================

def get_user(user_id):
    uid = str(user_id)
    user = users_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "days": {}, "goal": 2000, "tara": 0}
        users_col.insert_one(user)
    return user

def save_user(user):
    users_col.replace_one({"_id": user["_id"]}, user, upsert=True)

def get_today_log(user_id):
    user = get_user(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in user["days"]:
        user["days"][today] = []
        save_user(user)
    return user, today


# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ============================================================

def is_photo_already_logged(user, today, file_unique_id):
    for item in user["days"].get(today, []):
        if item.get("file_unique_id") == file_unique_id:
            return True
    return False

def is_delete_command(text):
    text_lower = text.lower().strip()
    for keyword in ["видали", "видалити", "убери", "прибери", "скасуй", "відміни", "delete", "remove", "undo"]:
        if keyword in text_lower:
            return True
    return False

def is_view_command(text):
    text_lower = text.lower().strip()
    for keyword in ["мій день", "переглянути день", "покажи день", "що я їв", "підсумок"]:
        if keyword in text_lower:
            return True
    return False

def build_progress_bar(total, goal):
    pct = int((total / goal) * 100) if goal > 0 else 0
    filled = min(int((total / goal) * 15), 15) if goal > 0 else 0
    bar = "█" * filled + "░" * (15 - filled)
    if pct < 50:
        circle = "🟢"
    elif pct < 85:
        circle = "🟡"
    else:
        circle = "🔴"
    return f"{circle} {bar}", pct

async def download_photo(context, photo):
    file = await context.bot.get_file(photo.file_id)
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(file.file_path) as resp:
            image_data = await resp.read()
    return base64.standard_b64encode(image_data).decode("utf-8")


# ============================================================
# АНАЛІЗ ФОТО ЧЕРЕЗ CLAUDE
# ============================================================

async def process_photos(context, user_id, chat_id, photos_data, tara):
    user, today = get_today_log(user_id)

    content = []
    for img_b64 in photos_data:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
        })

    tara_text = (
        f"Вага тари (тарілки): {tara}г — відніми від показань терезів щоб отримати вагу їжі."
        if tara > 0 else
        "Тара не встановлена — використовуй повну вагу з терезів."
    )

    # 🔧 ФІКС: новий промпт який не дублює продукти між фото
    multi_note = (
        "ВАЖЛИВО: всі фото показують ОДИН І ТОЙ САМИЙ прийом їжі. "
        "НЕ дублюй продукти — якщо один продукт є на кількох фото, рахуй його ОДИН раз. "
        "Якщо один продукт зважено кілька разів на різних фото — бери вагу з ОСТАННЬОГО зважування."
    ) if len(photos_data) > 1 else ""

    content.append({
        "type": "text",
        "text": (
            f"Проаналізуй {'ці фото' if len(photos_data) > 1 else 'це фото'} їжі. {multi_note} "
            f"1) Визнач всі УНІКАЛЬНІ продукти (не повторюй один і той самий продукт двічі). "
            f"2) Знайди дисплей кухонних терезів якщо є — прочитай вагу в грамах. "
            f"3) {tara_text} "
            f"4) Порахуй калорії на основі реальної ваги кожного унікального продукту. "
            f"Поверни ТІЛЬКИ JSON масив унікальних продуктів. "
            f"Кожен елемент: {{\"name\": \"назва українською\", \"calories\": число, \"protein\": число, \"carbs\": число, \"fat\": число, \"weight_g\": число або null, \"scale_detected\": true або false}}. "
            f"Назви ТІЛЬКИ українською. Без зайвого тексту, тільки JSON."
        )
    })

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1500,
            messages=[{"role": "user", "content": content}]
        )

        raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            items = [items]

        if items:
            items[0]["file_unique_id"] = photos_data[0][:20]

        for item in items:
            user["days"][today].append(item)
        save_user(user)

        total_today = sum(item.get("calories", 0) for item in user["days"][today])
        goal = user.get("goal", 2000)
        bar, pct = build_progress_bar(total_today, goal)

        scale_items = [i for i in items if i.get("scale_detected")]
        tara_line = f"📊 Тара {tara}г віднята автоматично\n" if scale_items and tara > 0 else ""

        lines = [f"Розпізнав ({len(photos_data)} фото)!\n" if len(photos_data) > 1 else "Розпізнав!\n"]
        if tara_line:
            lines.append(tara_line)

        for item in items:
            weight_info = f" ({item['weight_g']}г)" if item.get("weight_g") else ""
            lines.append(f"• {item['name']}{weight_info} — {item.get('calories', '?')} ккал")

        meal_total = sum(i.get("calories", 0) for i in items)
        lines.append(f"\nЦей прийом: {meal_total} ккал")
        lines.append(f"{bar} {pct}%")
        lines.append(f"За день: {total_today} / {goal} ккал")
        lines.append(f"Залишилось: {goal - total_today} ккал")

        if tara == 0:
            lines.append("\n💡 Встанови вагу тарілки: /tara 417")

        keyboard = [
            [InlineKeyboardButton("Переглянути день", callback_data="day"),
             InlineKeyboardButton("Календар", callback_data="calendar")],
            [InlineKeyboardButton("+ Додати ще", callback_data="add_more")]
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Помилка фото: {str(e)}")


# ============================================================
# КОМАНДИ
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Мій день", callback_data="day"),
         InlineKeyboardButton("Календар", callback_data="calendar")],
        [InlineKeyboardButton("Скинути день", callback_data="reset"),
         InlineKeyboardButton("Змінити ціль", callback_data="set_goal")]
    ]
    await update.message.reply_text(
        "Привіт! Я твій трекер калорій!\n\n"
        "🍽 Надішли фото їжі — порахую калорії\n"
        "📎 Можна кілька фото одразу — порахую як один прийом\n\n"
        "/tara 417 - вага тарілки\n"
        "/day - підсумок за сьогодні\n"
        "/reset - скинути день\n"
        "/goal 1800 - ціль калорій",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Немає доступу.")
        return

    all_users = list(users_col.find({}))
    if not all_users:
        await update.message.reply_text("Користувачів немає.")
        return

    count = len(all_users)
    lines = ["Користувачів: " + str(count) + "\n"]

    for u in all_users:
        uid = u["_id"]
        days = u.get("days", {})
        total_days = len([d for d in days.values() if d])
        total_entries = sum(len(d) for d in days.values())
        goal = u.get("goal", 2000)
        last_day = max(days.keys()) if days else "немає"

        lines.append("👤 ID: " + str(uid))
        lines.append("   Днів з записами: " + str(total_days))
        lines.append("   Всього прийомів: " + str(total_entries))
        lines.append("   Ціль: " + str(goal) + " ккал")
        lines.append("   Останній запис: " + str(last_day) + "\n")

    await update.message.reply_text("\n".join(lines))


async def set_tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tara = int(context.args[0])
        user = get_user(update.effective_user.id)
        user["tara"] = tara
        save_user(user)
        await update.message.reply_text(f"Тара збережена: {tara}г ✅")
    except (IndexError, ValueError):
        await update.message.reply_text("Використання: /tara 417")


async def delete_last_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, today = get_today_log(user_id)
    log = user["days"][today]

    if not log:
        await update.message.reply_text("Сьогоднішній лог порожній — нічого видаляти.")
        return

    removed = log.pop()
    save_user(user)

    total = sum(item.get("calories", 0) for item in log)
    goal = user.get("goal", 2000)
    await update.message.reply_text(
        f"Видалено: {removed['name']} ({removed.get('calories', '?')} ккал)\n\n"
        f"За день: {total} / {goal} ккал\n"
        f"Залишилось: {goal - total} ккал"
    )


async def day_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, today = get_today_log(user_id)
    log = user["days"][today]

    if not log:
        await update.message.reply_text("Сьогодні ще нічого не записано!")
        return

    total_cal = sum(item.get("calories", 0) for item in log)
    total_protein = sum(item.get("protein", 0) for item in log)
    total_carbs = sum(item.get("carbs", 0) for item in log)
    total_fat = sum(item.get("fat", 0) for item in log)
    goal = user.get("goal", 2000)
    bar, pct = build_progress_bar(total_cal, goal)

    lines = ["Підсумок за сьогодні:\n"]
    for i, item in enumerate(log, 1):
        weight_str = f" ({item['weight_g']}г)" if item.get("weight_g") else ""
        lines.append(f"{i}. {item['name']}{weight_str} — {item.get('calories', '?')} ккал")

    lines.append(f"\n{bar} {pct}%")
    lines.append(f"Калорії: {total_cal} / {goal} ккал")
    lines.append(f"Залишилось: {goal - total_cal} ккал")
    lines.append(f"Б: {total_protein}г | В: {total_carbs}г | Ж: {total_fat}г")

    keyboard = [
        [InlineKeyboardButton("Переглянути день", callback_data="day"),
         InlineKeyboardButton("Календар", callback_data="calendar")],
        [InlineKeyboardButton("+ Додати ще", callback_data="add_more"),
         InlineKeyboardButton("✏️ Редагувати", callback_data="edit_menu")]
    ]
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user, today = get_today_log(user_id)
    user["days"][today] = []
    save_user(user)
    await update.message.reply_text("День скинуто! Починаємо з 0 ккал. 🔄")


async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        goal = int(context.args[0])
        user = get_user(update.effective_user.id)
        user["goal"] = goal
        save_user(user)
        await update.message.reply_text(f"Ціль встановлено: {goal} ккал на день ✅")
    except (IndexError, ValueError):
        await update.message.reply_text("Використання: /goal 1800")


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    days = user.get("days", {})

    if not days:
        await update.message.reply_text("Ще немає записів!")
        return

    lines = ["Календар харчування:\n"]
    for date in sorted(days.keys(), reverse=True)[:14]:
        log = days[date]
        total = sum(item.get("calories", 0) for item in log)
        lines.append(f"{date}: {total} ккал ({len(log)} прийомів)")

    await update.message.reply_text("\n".join(lines))


# ============================================================
# ОБРОБНИК ТЕКСТУ
# ============================================================

async def analyze_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if is_delete_command(text):
        await delete_last_entry(update, context)
        return

    if is_view_command(text):
        await day_summary(update, context)
        return

    user_id = update.effective_user.id
    user, today = get_today_log(user_id)

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            system=(
                "Ти експерт з харчування. Користувач описує що з'їв. "
                "Проаналізуй і поверни ТІЛЬКИ JSON масив страв. "
                "Кожен елемент: {\"name\": \"назва українською\", \"calories\": число, \"protein\": число, \"carbs\": число, \"fat\": число}. "
                "Назви ТІЛЬКИ українською мовою. Без зайвого тексту, тільки JSON."
            ),
            messages=[{"role": "user", "content": text}]
        )

        raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()

        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            keyboard = [
                [InlineKeyboardButton("Мій день", callback_data="day"),
                 InlineKeyboardButton("Календар", callback_data="calendar")],
                [InlineKeyboardButton("Скинути день", callback_data="reset"),
                 InlineKeyboardButton("+ Додати ще", callback_data="add_more")]
            ]
            await update.message.reply_text(
                "Не зрозумів 🤔\n\n"
                "Ось що я вмію:\n\n"
                "🍽 *Записати їжу:*\n"
                "• Надішли фото їжі\n"
                "• Або напиши: борщ 300г, куряча грудка з рисом\n\n"
                "📊 *Переглянути:*\n"
                "• /day — підсумок за сьогодні\n"
                "• /calendar — останні 14 днів\n\n"
                "🗑 *Видалити:*\n"
                "• Напиши: видали — видалить останній запис\n\n"
                "⚙️ *Налаштування:*\n"
                "• /goal 2000 — встановити ціль калорій\n"
                "• /tara 417 — вага тарілки\n"
                "• /reset — скинути день",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        if not isinstance(items, list):
            items = [items]

        for item in items:
            user["days"][today].append(item)
        save_user(user)

        total_today = sum(item.get("calories", 0) for item in user["days"][today])
        goal = user.get("goal", 2000)
        bar, pct = build_progress_bar(total_today, goal)

        lines = ["Записано!\n"]
        for item in items:
            lines.append(f"• {item['name']} — {item.get('calories', '?')} ккал")
        lines.append(f"\nЦей прийом: {sum(i.get('calories', 0) for i in items)} ккал")
        lines.append(f"{bar} {pct}%")
        lines.append(f"За день: {total_today} / {goal} ккал")
        lines.append(f"Залишилось: {goal - total_today} ккал")

        keyboard = [
            [InlineKeyboardButton("Переглянути день", callback_data="day"),
             InlineKeyboardButton("Календар", callback_data="calendar")],
            [InlineKeyboardButton("+ Додати ще", callback_data="add_more")]
        ]
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        await update.message.reply_text(f"Помилка: {str(e)}")


# ============================================================
# ОБРОБНИК ФОТО
# ============================================================

async def analyze_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user = get_user(user_id)
    tara = user.get("tara", 0)

    photo = update.message.photo[-1]
    media_group_id = update.message.media_group_id

    if not media_group_id:
        _, today = get_today_log(user_id)
        if is_photo_already_logged(user, today, photo.file_unique_id):
            total_today = sum(item.get("calories", 0) for item in user["days"][today])
            goal = user.get("goal", 2000)
            await update.message.reply_text(
                f"Це фото вже записано сьогодні!\n\n"
                f"За день: {total_today} / {goal} ккал\n\n"
                f"Якщо хочеш додати ще раз — напиши назву їжі текстом."
            )
            return
        img_b64 = await download_photo(context, photo)
        await process_photos(context, user_id, chat_id, [img_b64], tara)
        return

    if media_group_id not in media_group_buffer:
        media_group_buffer[media_group_id] = {
            "photos": [],
            "user_id": user_id,
            "chat_id": chat_id,
            "tara": tara,
            "task": None
        }

    img_b64 = await download_photo(context, photo)
    media_group_buffer[media_group_id]["photos"].append(img_b64)

    if media_group_buffer[media_group_id]["task"]:
        media_group_buffer[media_group_id]["task"].cancel()

    async def process_group():
        await asyncio.sleep(2)
        if media_group_id in media_group_buffer:
            data = media_group_buffer.pop(media_group_id)
            await process_photos(context, data["user_id"], data["chat_id"], data["photos"], data["tara"])

    task = asyncio.create_task(process_group())
    media_group_buffer[media_group_id]["task"] = task


# ============================================================
# ОБРОБНИК КНОПОК
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "day":
        user_id = query.from_user.id
        user, today = get_today_log(user_id)
        log = user["days"][today]

        if not log:
            await query.message.reply_text("Сьогодні ще нічого не записано!")
            return

        total_cal = sum(item.get("calories", 0) for item in log)
        total_protein = sum(item.get("protein", 0) for item in log)
        total_carbs = sum(item.get("carbs", 0) for item in log)
        total_fat = sum(item.get("fat", 0) for item in log)
        goal = user.get("goal", 2000)
        bar, pct = build_progress_bar(total_cal, goal)

        lines = ["Підсумок за сьогодні:\n"]
        for i, item in enumerate(log, 1):
            weight_str = f" ({item['weight_g']}г)" if item.get("weight_g") else ""
            lines.append(f"{i}. {item['name']}{weight_str} — {item.get('calories', '?')} ккал")

        lines.append(f"\n{bar} {pct}%")
        lines.append(f"Калорії: {total_cal} / {goal} ккал")
        lines.append(f"Залишилось: {goal - total_cal} ккал")
        lines.append(f"Б: {total_protein}г | В: {total_carbs}г | Ж: {total_fat}г")

        keyboard = [
            [InlineKeyboardButton("Переглянути день", callback_data="day"),
             InlineKeyboardButton("Календар", callback_data="calendar")],
            [InlineKeyboardButton("+ Додати ще", callback_data="add_more"),
             InlineKeyboardButton("✏️ Редагувати", callback_data="edit_menu")]
        ]
        await query.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "calendar":
        user_id = query.from_user.id
        user = get_user(user_id)
        days = user.get("days", {})

        if not days:
            await query.message.reply_text("Ще немає записів!")
            return

        lines = ["Календар харчування:\n"]
        for date in sorted(days.keys(), reverse=True)[:14]:
            log = days[date]
            total = sum(item.get("calories", 0) for item in log)
            lines.append(f"{date}: {total} ккал ({len(log)} прийомів)")

        await query.message.reply_text("\n".join(lines))

    # 🔧 ФІКС: reset тепер обробляється з підтвердженням
    elif query.data == "reset":
        keyboard = [
            [InlineKeyboardButton("✅ Так, скинути", callback_data="reset_confirm"),
             InlineKeyboardButton("❌ Скасувати", callback_data="reset_cancel")]
        ]
        await query.message.reply_text(
            "Ти впевнений що хочеш скинути весь день до 0?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "reset_confirm":
        user_id = query.from_user.id
        user, today = get_today_log(user_id)
        user["days"][today] = []
        save_user(user)
        await query.message.reply_text("День скинуто! Починаємо з 0 ккал. 🔄")

    elif query.data == "reset_cancel":
        await query.message.reply_text("Скасовано. День не змінено. ✅")

    elif query.data == "set_goal":
        await query.message.reply_text(
            "Напиши нову ціль калорій командою:\n/goal 2000"
        )

    elif query.data == "add_more":
        await query.message.reply_text("Надішли фото або напиши що ще з'їв!")

    elif query.data == "edit_menu":
        user_id = query.from_user.id
        user, today = get_today_log(user_id)
        log = user["days"][today]

        if not log:
            await query.message.reply_text("Сьогодні ще нічого не записано!")
            return

        keyboard = []
        for i, item in enumerate(log):
            name = item.get("name", "?")
            cal = item.get("calories", "?")
            keyboard.append([InlineKeyboardButton(
                f"❌ {i+1}. {name} — {cal} ккал",
                callback_data=f"del_{i}"
            )])
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="day")])
        await query.message.reply_text(
            "Натисни на запис щоб видалити його:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("del_"):
        idx = int(query.data.split("_")[1])
        user_id = query.from_user.id
        user, today = get_today_log(user_id)
        log = user["days"][today]

        if idx < len(log):
            removed = log.pop(idx)
            save_user(user)
            total = sum(item.get("calories", 0) for item in log)
            goal = user.get("goal", 2000)
            bar, pct = build_progress_bar(total, goal)
            await query.message.reply_text(
                f"Видалено: {removed['name']} ({removed.get('calories', '?')} ккал)\n\n"
                f"{bar} {pct}%\n"
                f"За день: {total} / {goal} ккал\n"
                f"Залишилось: {goal - total} ккал"
            )
        else:
            await query.message.reply_text("Запис не знайдено.")


# ============================================================
# ЗАПУСК
# ============================================================

def main():
    print("Bot starting...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("day", day_summary))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("goal", set_goal))
    app.add_handler(CommandHandler("tara", set_tara))
    app.add_handler(CommandHandler("calendar", show_calendar))
    app.add_handler(CommandHandler("users", show_users))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, analyze_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_text))

    print("Bot is running!")
    app.run_polling()


if __name__ == "__main__":
    main()