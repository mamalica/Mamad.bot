import os
import json
import asyncio
import random
import string
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

# ===== تنظیمات پایه =====
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
SECOND_CHANNEL_USERNAME = os.getenv("SECOND_CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
VIDEO_DB_FILE = "videos.json"
USERS_FILE = "users.json"
user_state = {}
pending_users = {}
bot = Bot(token=BOT_TOKEN)
app = Flask(__name__)

# ===== ساخت فایل‌ها =====
for file in [VIDEO_DB_FILE, USERS_FILE]:
    if not os.path.exists(file):
        with open(file, "w", encoding="utf-8") as f:
            json.dump({} if file == VIDEO_DB_FILE else [], f)

# ===== مدیریت ویدیوها =====
...
# (اینجا توابع load_videos, save_videos, generate_code)
# ===== مدیریت کاربران =====
...
# ===== بررسی عضویت =====
async def is_member(chat_id, user_id, context):
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===== وب‌هوک =====
@app.route('/', methods=['GET'])
def health():
    return "OK"

@app.route('/', methods=['POST'])
def webhook_handler():
    update = Update.de_json(request.get_json(force=True), bot)
    return asyncio.run(dispatch_update(update)), 200

async def dispatch_update(update: Update):
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    # ثبت هندلرها
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(handle_admin_buttons, pattern="^upload_video$"))
    application.add_handler(CallbackQueryHandler(handle_check_button, pattern="^check_"))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_from_admin))
    application.add_handler(CommandHandler("start", start_link))
    application.add_handler(CommandHandler("member", show_member_count))
    await application.initialize()
    await application.process_update(update)
    await application.shutdown()

# ===== بقیه توابع (admin_panel، handle_...، send_video) =====
# مشابه کد اصلی شما

if __name__ == "__main__":
    app.run()
