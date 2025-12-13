import os
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, \
    ConversationHandler

# ============================================
# SOZLAMALAR
# ============================================
BOT_TOKEN = "BOT_TOKEN"
SUPER_ADMIN = 6664108424
ADMINS = [6664108424]
GROUP_CHAT_ID = -1003424440596  # Guruh ID'si (get_group_id.py bilan oling)

# FAYL QABUL QILISH REJIMLARI (birini tanlang)
MODE = "HASHTAG"  # Variantlar: "HASHTAG", "REPLY", "CAPTION_ONLY"

# Hashteg sozlamalari (MODE = "HASHTAG" bo'lsa)
VALID_HASHTAGS = ['#homework', '#uyishi', '#vazifa', '#hw']

# Conversation states
WAITING_FOR_FEEDBACK = 1


# ============================================
# BAZA
# ============================================
def init_db():
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            lesson_number INTEGER,
            file_id TEXT,
            filename TEXT,
            status INTEGER DEFAULT 0,
            comment TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER PRIMARY KEY,
            score INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            points INTEGER,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    ''')

    for admin_id in ADMINS:
        cur.execute('INSERT OR IGNORE INTO admins VALUES (?)', (admin_id,))

    conn.commit()
    conn.close()


# ============================================
# YORDAMCHI FUNKSIYALAR
# ============================================
def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
    result = cur.fetchone()
    conn.close()
    return result is not None


def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN


def add_or_update_user(user_id: int, full_name: str, username: str):
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (user_id, full_name, username) 
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            full_name = excluded.full_name,
            username = excluded.username
    ''', (user_id, full_name, username))
    conn.commit()
    conn.close()


def has_valid_hashtag(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return any(hashtag in text_lower for hashtag in VALID_HASHTAGS)


def extract_lesson_number(text: str) -> int:
    if not text:
        return None

    patterns = [
        r'dars[_\s-]*(\d+)',
        r'(?:hw|homework)[_\s-]*(\d+)',
        r'(?:lesson)[_\s-]*(\d+)',
        r'(\d+)[_\s-]*(?:dars|chi)',
        r'#\w*\s*(\d+)',
        r'(?:^|\s)(\d{1,3})(?:\s|$|\.)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            num = int(match.group(1))
            if 1 <= num <= 100:
                return num
    return None


def add_score(user_id: int, points: int, reason: str = ""):
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()

    cur.execute('''
        INSERT INTO scores (user_id, score) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET score = score + ?
    ''', (user_id, points, points))

    cur.execute('''
        INSERT INTO score_history (user_id, points, reason)
        VALUES (?, ?, ?)
    ''', (user_id, points, reason))

    conn.commit()
    conn.close()


def is_first_submission(lesson_number: int) -> bool:
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM homework WHERE lesson_number = ?', (lesson_number,))
    count = cur.fetchone()[0]
    conn.close()
    return count == 0


# ============================================
# KOMANDALAR
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user.id, user.full_name, user.username or "")

    mode_info = {
        "HASHTAG": f"Caption'ga hashteg qo'shing: {', '.join(VALID_HASHTAGS)}",
        "REPLY": "Botning xabariga reply qiling",
        "CAPTION_ONLY": "Caption'da dars raqamini yozing"
    }

    if is_admin(user.id):
        admin_text = "🎓 **Python Uyga Vazifa Bot — Admin Panel**\n\n"
        admin_text += "📋 **Mavjud komandalar:**\n"
        admin_text += "/check <dars> — Tekshirish\n"
        admin_text += "/notdone <dars> — Topshirmaganlar\n"
        admin_text += "/top — Umumiy reyting\n"
        admin_text += "/topweek — Haftalik reyting\n"
        admin_text += "/topmonth — Oylik reyting\n"
        admin_text += "/addadmin <id> — Yangi admin\n"
        admin_text += "/myid — ID'ingizni ko'rish\n"

        if is_super_admin(user.id):
            admin_text += "\n🔥 **Super Admin:**\n"
            admin_text += "/addpoints <id> <ball> — Ball qo'shish\n"
            admin_text += "/removepoints <id> <ball> — Ball ayirish\n"
            admin_text += "/setpoints <id> <ball> — Ballni o'rnatish\n"

        await update.message.reply_text(admin_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"👋 Assalomu alaykum **{user.first_name}**!\n\n"
            f"📘 Python uyga vazifa botiga xush kelibsiz!\n\n"
            f"📤 **Uy vazifa yuborish:**\n"
            f"{mode_info[MODE]}\n\n"
            f"📋 **Komandalar:**\n"
            f"/my — Natijalarim\n"
            f"/top — Reyting\n"
            f"/help — Yordam",
            parse_mode='Markdown'
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode_examples = {
        "HASHTAG": "**Hashteg bilan:**\n`#homework 25`\n`#uyishi dars 12`",
        "REPLY": "**Reply qilish:**\nBotning xabariga javob bering",
        "CAPTION_ONLY": "**Caption:**\n`dars 25`\n`homework 12`"
    }

    await update.message.reply_text(
        f"📖 **Qanday ishlatish:**\n\n"
        f"{mode_examples[MODE]}\n\n"
        f"📋 **Komandalar:**\n"
        f"/my — Natijalarim\n"
        f"/top — Reyting\n"
        f"/help — Yordam",
        parse_mode='Markdown'
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_info = ""
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_info = f"\n🆔 Guruh ID: `{update.effective_chat.id}`"

    await update.message.reply_text(
        f"🆔 **Sizning ID:** `{update.effective_user.id}`{chat_info}",
        parse_mode='Markdown'
    )


async def my_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT lesson_number, status, comment, timestamp
        FROM homework 
        WHERE user_id = ? 
        ORDER BY lesson_number DESC
    ''', (user_id,))
    results = cur.fetchall()

    cur.execute('SELECT score FROM scores WHERE user_id = ?', (user_id,))
    score_result = cur.fetchone()
    score = score_result[0] if score_result else 0
    conn.close()

    if not results:
        await update.message.reply_text("📭 Hali uy vazifa topshirilmagan.")
        return

    message = f"📊 **Sizning natijalaringiz:**\n\n⭐ Jami ball: **{score}**\n\n"

    for lesson, status, comment, timestamp in results:
        status_emoji = {0: '⏳', 1: '✅', 2: '✏️'}
        status_text = {0: 'Tekshirilmoqda', 1: 'Yaxshi', 2: 'Kamchilik'}
        message += f"**{lesson}-dars** – {status_text[status]} {status_emoji[status]}\n"

    await update.message.reply_text(message, parse_mode='Markdown')


async def top_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT u.full_name, s.score 
        FROM scores s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.score > 0
        ORDER BY s.score DESC
        LIMIT 10
    ''')
    results = cur.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("📊 Hali reyting mavjud emas.")
        return

    message = "🏆 **Eng faol o'quvchilar:**\n\n"
    for idx, (name, score) in enumerate(results, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(idx, '  ')
        message += f"{medal} **{idx}.** {name} – {score} ball\n"

    await update.message.reply_text(message, parse_mode='Markdown')


async def top_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    week_ago = datetime.now() - timedelta(days=7)

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT u.full_name, SUM(sh.points) as total
        FROM score_history sh
        JOIN users u ON sh.user_id = u.user_id
        WHERE sh.timestamp >= ?
        GROUP BY sh.user_id
        ORDER BY total DESC
        LIMIT 10
    ''', (week_ago,))
    results = cur.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("📊 Bu hafta hali ball yo'q.")
        return

    message = "🔥 **Haftalik reyting (oxirgi 7 kun):**\n\n"
    for idx, (name, score) in enumerate(results, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(idx, '  ')
        message += f"{medal} **{idx}.** {name} – {int(score)} ball\n"

    await update.message.reply_text(message, parse_mode='Markdown')


async def top_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month_ago = datetime.now() - timedelta(days=30)

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT u.full_name, SUM(sh.points) as total
        FROM score_history sh
        JOIN users u ON sh.user_id = u.user_id
        WHERE sh.timestamp >= ?
        GROUP BY sh.user_id
        ORDER BY total DESC
        LIMIT 10
    ''', (month_ago,))
    results = cur.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("📊 Bu oy hali ball yo'q.")
        return

    message = "📅 **Oylik reyting (oxirgi 30 kun):**\n\n"
    for idx, (name, score) in enumerate(results, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(idx, '  ')
        message += f"{medal} **{idx}.** {name} – {int(score)} ball\n"

    await update.message.reply_text(message, parse_mode='Markdown')


async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komanda faqat adminlar uchun!")
        return

    if not context.args:
        await update.message.reply_text("❌ Foydalanish: /addadmin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        conn = sqlite3.connect('homework.db')
        cur = conn.cursor()
        cur.execute('INSERT OR IGNORE INTO admins VALUES (?)', (new_admin_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Admin qo'shildi: {new_admin_id}")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID formati!")


# ============================================
# MANUAL BALL BOSHQARUVI (SUPER ADMIN)
# ============================================
async def add_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komanda faqat super admin uchun!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Foydalanish: /addpoints <user_id> <ball>")
        return

    try:
        user_id = int(context.args[0])
        points = int(context.args[1])

        conn = sqlite3.connect('homework.db')
        cur = conn.cursor()
        cur.execute('SELECT full_name FROM users WHERE user_id = ?', (user_id,))
        result = cur.fetchone()
        conn.close()

        if not result:
            await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi!")
            return

        full_name = result[0]
        add_score(user_id, points, f"Admin tomonidan qo'shildi")

        await update.message.reply_text(f"✅ {full_name} ga +{points} ball qo'shildi!")

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎁 Sizga **+{points} ball** qo'shildi!\nSabab: Admin tomonidan",
                parse_mode='Markdown'
            )
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format!")


async def remove_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komanda faqat super admin uchun!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Foydalanish: /removepoints <user_id> <ball>")
        return

    try:
        user_id = int(context.args[0])
        points = int(context.args[1])

        conn = sqlite3.connect('homework.db')
        cur = conn.cursor()
        cur.execute('SELECT full_name FROM users WHERE user_id = ?', (user_id,))
        result = cur.fetchone()
        conn.close()

        if not result:
            await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi!")
            return

        full_name = result[0]
        add_score(user_id, -points, f"Admin tomonidan ayirildi")

        await update.message.reply_text(f"✅ {full_name} dan -{points} ball ayirildi!")

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Sizdan **-{points} ball** ayirildi.",
                parse_mode='Markdown'
            )
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format!")


async def set_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu komanda faqat super admin uchun!")
        return

    if len(context.args) < 2:
        await update.message.reply_text("❌ Foydalanish: /setpoints <user_id> <ball>")
        return

    try:
        user_id = int(context.args[0])
        points = int(context.args[1])

        conn = sqlite3.connect('homework.db')
        cur = conn.cursor()
        cur.execute('SELECT full_name FROM users WHERE user_id = ?', (user_id,))
        result = cur.fetchone()

        if not result:
            await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi!")
            conn.close()
            return

        full_name = result[0]

        cur.execute('SELECT score FROM scores WHERE user_id = ?', (user_id,))
        old_score = cur.fetchone()
        old_score = old_score[0] if old_score else 0

        cur.execute('''
            INSERT INTO scores (user_id, score) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET score = ?
        ''', (user_id, points, points))

        cur.execute('''
            INSERT INTO score_history (user_id, points, reason)
            VALUES (?, ?, ?)
        ''', (user_id, points - old_score, f"Admin ball o'rnatdi: {old_score} → {points}"))

        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ {full_name} ning balli o'rnatildi!\n"
            f"Avvalgi: {old_score} → Yangi: {points}"
        )

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📊 Sizning ballingiz **{points}** ga o'rnatildi.",
                parse_mode='Markdown'
            )
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format!")


# ============================================
# FAYL QABUL QILISH
# ============================================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        return

    user = update.effective_user
    message = update.message

    add_or_update_user(user.id, user.full_name, user.username or "")

    if not message.document:
        return

    file = message.document
    filename = file.file_name
    file_id = file.file_id

    if not (filename.endswith('.py') or filename.endswith('.txt')):
        return

    caption = message.caption or ""

    if MODE == "HASHTAG":
        if not has_valid_hashtag(caption):
            return
    elif MODE == "REPLY":
        if not message.reply_to_message or message.reply_to_message.from_user.id != context.bot.id:
            return

    combined_text = f"{caption} {filename}"
    lesson_number = extract_lesson_number(combined_text)

    if lesson_number is None:
        await message.reply_text("❌ Dars raqami topilmadi!\nCaption yoki fayl nomida raqam ko'rsating.")
        return

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT id FROM homework 
        WHERE user_id = ? AND lesson_number = ?
    ''', (user.id, lesson_number))
    existing = cur.fetchone()

    if existing:
        cur.execute('''
            UPDATE homework 
            SET file_id = ?, filename = ?, status = 0, comment = NULL, timestamp = CURRENT_TIMESTAMP
            WHERE user_id = ? AND lesson_number = ?
        ''', (file_id, filename, user.id, lesson_number))
        conn.commit()
        conn.close()

        await message.reply_text(
            f"━━━━━━━━━━━━━━━\n"
            f"♻️ **{lesson_number}-DARS (Qayta)**\n"
            f"👤 {user.full_name}\n"
            f"📄 `{filename}`\n"
            f"⏳ Tekshirilmoqda\n"
            f"━━━━━━━━━━━━━━━",
            parse_mode='Markdown'
        )
    else:
        cur.execute('''
            INSERT INTO homework (user_id, lesson_number, file_id, filename, status)
            VALUES (?, ?, ?, ?, 0)
        ''', (user.id, lesson_number, file_id, filename))
        conn.commit()

        first = is_first_submission(lesson_number)
        conn.close()

        if first:
            add_score(user.id, 3, f"{lesson_number}-dars (birinchi)")
            bonus_text = "🌟 Birinchi! **+3 ball**"
        else:
            add_score(user.id, 1, f"{lesson_number}-dars")
            bonus_text = "**+1 ball**"

        await message.reply_text(
            f"━━━━━━━━━━━━━━━\n"
            f"📘 **{lesson_number}-DARS**\n"
            f"👤 {user.full_name}\n"
            f"📄 `{filename}`\n"
            f"⏳ Tekshirilmoqda\n"
            f"{bonus_text}\n"
            f"━━━━━━━━━━━━━━━",
            parse_mode='Markdown'
        )


# ============================================
# TEKSHIRISH
# ============================================
async def check_homework(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Faqat adminlar uchun!")
        return

    if not context.args:
        await update.message.reply_text("❌ Foydalanish: /check <dars_raqami>\nMisol: /check 15")
        return

    try:
        lesson_number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Raqam kiriting! Misol: /check 15")
        return

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT h.id, h.user_id, u.full_name, h.filename, h.status
        FROM homework h
        JOIN users u ON h.user_id = u.user_id
        WHERE h.lesson_number = ?
        ORDER BY h.timestamp
    ''', (lesson_number,))
    submissions = cur.fetchall()
    conn.close()

    if not submissions:
        await update.message.reply_text(f"📭 {lesson_number}-dars uchun topshiriqlar yo'q.")
        return

    # Agar guruhda yozilgan bo'lsa, DM'ga yo'naltirish
    if update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            f"📋 {lesson_number}-dars uchun {len(submissions)} ta topshiriq bor.\n\n"
            f"✉️ Tekshirish uchun menga shaxsiy xabar yozing:\n"
            f"/check {lesson_number}",
            parse_mode='Markdown'
        )
        # DMga ham yuboramiz
        try:
            message = f"📘 **{lesson_number}-dars topshirganlar:**\n\n"
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=message,
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("⚠️ Avval botni ishga tushiring: /start")
            return

    # Tekshirish ro'yxati
    for idx, (hw_id, user_id, full_name, filename, status) in enumerate(submissions, 1):
        status_emoji = {0: '⏳', 1: '✅', 2: '✏️'}[status]

        keyboard = [
            [
                InlineKeyboardButton("🟦 Ko'rish", callback_data=f"view_{hw_id}"),
                InlineKeyboardButton("✅ Yaxshi", callback_data=f"approve_{hw_id}"),
                InlineKeyboardButton("✏️ Kamchilik", callback_data=f"reject_{hw_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"{idx}) **{full_name}** {status_emoji}\n└ `{filename}`",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except:
            await update.message.reply_text("⚠️ Avval botga /start yozing!")
            return


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, hw_id = query.data.split('_')
    hw_id = int(hw_id)

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        SELECT user_id, lesson_number, file_id, filename
        FROM homework WHERE id = ?
    ''', (hw_id,))
    result = cur.fetchone()

    if not result:
        await query.edit_message_text("❌ Topilmadi!")
        conn.close()
        return

    user_id, lesson_number, file_id, filename = result
    cur.execute('SELECT full_name FROM users WHERE user_id = ?', (user_id,))
    full_name = cur.fetchone()[0]
    conn.close()

    if action == 'view':
        await context.bot.send_document(
            chat_id=query.from_user.id,
            document=file_id,
            caption=f"📄 {full_name} — {lesson_number}-dars\n`{filename}`",
            parse_mode='Markdown'
        )
        await query.edit_message_text(f"✅ Yuborildi: `{filename}`", parse_mode='Markdown')

    elif action == 'approve':
        conn = sqlite3.connect('homework.db')
        cur = conn.cursor()
        cur.execute('UPDATE homework SET status = 1 WHERE id = ?', (hw_id,))
        conn.commit()
        conn.close()

        add_score(user_id, 1, f"{lesson_number}-dars yaxshi bajarildi")

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🏅 **{lesson_number}-dars** yaxshi bajarildi! +1 bonus",
                parse_mode='Markdown'
            )
        except:
            pass

        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=f"✅ **{full_name}** — {lesson_number}-dars yaxshi ✓",
                parse_mode='Markdown'
            )
        except:
            pass

        await query.edit_message_text(f"✅ {full_name} — Yaxshi!")

    elif action == 'reject':
        context.user_data['pending_feedback'] = {
            'hw_id': hw_id,
            'user_id': user_id,
            'lesson_number': lesson_number,
            'full_name': full_name
        }
        await query.edit_message_text(
            f"✏️ **{full_name}** — {lesson_number}-dars\n\n"
            f"Kamchilikni yozing (/cancel bekor):",
            parse_mode='Markdown'
        )


async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'pending_feedback' not in context.user_data:
        return ConversationHandler.END

    feedback = update.message.text
    data = context.user_data['pending_feedback']

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()
    cur.execute('''
        UPDATE homework 
        SET status = 2, comment = ?
        WHERE id = ?
    ''', (feedback, data['hw_id']))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            chat_id=data['user_id'],
            text=f"✏️ **{data['lesson_number']}-dars** kamchiliklar:\n\n"
                 f"{feedback}\n\n"
                 f"Tuzatib qayta topshiring 🙂",
            parse_mode='Markdown'
        )
    except:
        pass

    try:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"⚠️ **{data['full_name']}** — {data['lesson_number']}-dars biroz kamchilik\n"
                 f"(izoh shaxsiy xabarda)",
            parse_mode='Markdown'
        )
    except:
        pass

    await update.message.reply_text("✅ Kamchilik yuborildi!")
    del context.user_data['pending_feedback']
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'pending_feedback' in context.user_data:
        del context.user_data['pending_feedback']
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


async def not_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Faqat adminlar uchun!")
        return

    if not context.args:
        await update.message.reply_text("❌ /notdone <dars_raqami>")
        return

    try:
        lesson_number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Raqam kiriting!")
        return

    conn = sqlite3.connect('homework.db')
    cur = conn.cursor()

    cur.execute('SELECT user_id, full_name FROM users')
    all_users = cur.fetchall()

    cur.execute('SELECT user_id FROM homework WHERE lesson_number = ?', (lesson_number,))
    submitted = {row[0] for row in cur.fetchall()}
    conn.close()

    not_submitted = [(uid, name) for uid, name in all_users if uid not in submitted and not is_admin(uid)]

    if not not_submitted:
        await update.message.reply_text(f"✅ {lesson_number}-darsni hammalar topshirgan!")
        return

    message = f"📌 **{lesson_number}-darsni topshirmaganlar:**\n\n"
    for _, name in not_submitted:
        message += f"— {name}\n"

    await update.message.reply_text(message, parse_mode='Markdown')


# ============================================
# MAIN
# ============================================
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Komandalar
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('myid', myid))
    app.add_handler(CommandHandler('my', my_results))
    app.add_handler(CommandHandler('top', top_students))
    app.add_handler(CommandHandler('topweek', top_week))
    app.add_handler(CommandHandler('topmonth', top_month))
    app.add_handler(CommandHandler('check', check_homework))
    app.add_handler(CommandHandler('notdone', not_done))
    app.add_handler(CommandHandler('addadmin', add_admin))

    # Super admin komandalar
    app.add_handler(CommandHandler('addpoints', add_points_command))
    app.add_handler(CommandHandler('removepoints', remove_points_command))
    app.add_handler(CommandHandler('setpoints', set_points_command))

    # Conversation
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            WAITING_FOR_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        per_chat=True,
        per_user=True
    )
    app.add_handler(conv_handler)

    # Fayl qabul qilish
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot ishga tushdi!")
    print(f"📋 Rejim: {MODE}")
    print(f"👨‍💼 Super Admin: {SUPER_ADMIN}")
    app.run_polling()


if __name__ == '__main__':
    main()

