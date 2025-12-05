import os
import json
import asyncio
import random
import string
import logging
import time
import gc
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    Defaults
)

# ===== تنظیمات اولیه =====
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== تنظیم مسیر داده‌ها (برای جلوگیری از حذف شدن در سرور) =====
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def get_path(filename):
    return os.path.join(DATA_DIR, filename)

# ===== بارگذاری توکن و اطلاعات =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
# نام کاربری کانال‌ها باید بدون @ وارد شوند یا هندل شوند
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME") 
SECOND_CHANNEL_USERNAME = os.getenv("SECOND_CHANNEL_USERNAME")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except:
    ADMIN_ID = 0
    logger.warning("⚠️ ADMIN_ID معتبر نیست")

# نام فایل‌ها (داخل پوشه data)
VIDEO_DB_FILE = get_path("videos.json")
USERS_FILE = get_path("users.json")
PACKAGES_FILE = get_path("packages.json")
DEMO_MESSAGES_FILE = get_path("demo_messages.json")

# ===== متغیرهای حافظه موقت =====
_user_state = {}
_pending_users = {}
_admin_temp_packages = {}
_user_start_args = {}

# ===== مدیریت فایل‌ها =====
def _ensure_files():
    for file_path in [VIDEO_DB_FILE, PACKAGES_FILE, DEMO_MESSAGES_FILE]:
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f: json.dump({}, f)
    
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f: json.dump([], f)

def load_json(file_path, default=None):
    try:
        with open(file_path, "r", encoding="utf-8") as f: 
            return json.load(f)
    except:
        return default if default is not None else {}

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# توابع کمکی خواندن/نوشتن
def load_videos(): return load_json(VIDEO_DB_FILE, {})
def save_videos(data): save_json(VIDEO_DB_FILE, data)
def load_packages(): return load_json(PACKAGES_FILE, {})
def save_packages(data): save_json(PACKAGES_FILE, data)
def load_demo_messages(): return load_json(DEMO_MESSAGES_FILE, {})
def save_demo_messages(data): save_json(DEMO_MESSAGES_FILE, data)
def load_users(): return load_json(USERS_FILE, [])
def save_users(data): save_json(USERS_FILE, data)

def add_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        save_users(users)

def generate_code(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# ===== لاجیک عضویت اجباری =====
async def check_membership(user_id, context):
    channels_to_check = []
    if CHANNEL_USERNAME: channels_to_check.append(CHANNEL_USERNAME if CHANNEL_USERNAME.startswith('@') else f'@{CHANNEL_USERNAME}')
    if SECOND_CHANNEL_USERNAME: channels_to_check.append(SECOND_CHANNEL_USERNAME if SECOND_CHANNEL_USERNAME.startswith('@') else f'@{SECOND_CHANNEL_USERNAME}')

    if not channels_to_check: return True

    for channel in channels_to_check:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logger.error(f"Error checking membership for {channel}: {e}")
            # اگر ربات در کانال ادمین نباشد خطا میدهد، در این صورت سخت‌گیری نمیکنیم
            continue 
    return True

async def show_membership_required(update: Update, context: ContextTypes.DEFAULT_TYPE, start_args=None):
    user_id = update.effective_user.id
    if start_args: _user_start_args[user_id] = start_args

    keyboard = []
    if CHANNEL_USERNAME:
        uname = CHANNEL_USERNAME.replace('@', '')
        keyboard.append([InlineKeyboardButton("📢 کانال اول", url=f"https://t.me/{uname}")])
    if SECOND_CHANNEL_USERNAME:
        uname = SECOND_CHANNEL_USERNAME.replace('@', '')
        keyboard.append([InlineKeyboardButton("📢 کانال دوم", url=f"https://t.me/{uname}")])
    
    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])

    text = "⚠️ برای استفاده از ربات لطفا در کانال‌های زیر عضو شوید:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if await check_membership(user_id, context):
        await query.edit_message_text("✅ عضویت تایید شد!")
        # اگر کدی ذخیره شده بود، اجرا شود
        if user_id in _user_start_args:
            args = _user_start_args[user_id]
            await send_media_content_logic(update, context, args[0], user_id, is_callback=True)
            del _user_start_args[user_id]
    else:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشده‌اید!", show_alert=True)

# ===== هندلر استارت =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id)
    args = context.args

    if not await check_membership(user.id, context):
        await show_membership_required(update, context, args)
        return

    if args:
        await send_media_content_logic(update, context, args[0], user.id)
    else:
        if user.id == ADMIN_ID:
            await admin_panel(update, context)
        else:
            await update.message.reply_text("👋 سلام! برای دریافت محتوا باید لینک مخصوص داشته باشید.")

# ===== لاجیک ارسال مدیا =====
async def send_media_content_logic(update, context, code, user_id, is_callback=False):
    vids = load_videos()
    packages = load_packages()
    demo_messages = load_demo_messages()
    
    bot = context.bot
    target_chat_id = user_id

    # تابع کمکی برای ارسال پیام (چون ممکن است از طریق کال‌بک باشد یا پیام)
    async def send_reply(text):
        if is_callback: await bot.send_message(chat_id=target_chat_id, text=text)
        else: await update.message.reply_text(text)

    if code in vids:
        file_id = vids[code]
        try:
            msg = await bot.send_video(
                chat_id=target_chat_id,
                video=file_id,
                caption="🎥 این ویدیو ۲۰ ثانیه دیگر حذف می‌شود. آن را ذخیره کنید."
            )
            
            if code in demo_messages:
                await bot.send_message(chat_id=target_chat_id, text=demo_messages[code])

            context.job_queue.run_once(auto_delete_job, 20, chat_id=target_chat_id, data=msg.message_id)
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            await send_reply("❌ خطا در ارسال ویدیو.")

    elif code in packages:
        package = packages[code]
        count = 0
        for item in package:
            try:
                msg = None
                if isinstance(item, str): # فرمت قدیم
                    msg = await bot.send_video(chat_id=target_chat_id, video=item)
                elif isinstance(item, dict): # فرمت جدید
                    if item['type'] == 'photo':
                        msg = await bot.send_photo(chat_id=target_chat_id, photo=item['file_id'])
                    else:
                        msg = await bot.send_video(chat_id=target_chat_id, video=item['file_id'])
                
                if msg:
                    count += 1
                    context.job_queue.run_once(auto_delete_job, 20, chat_id=target_chat_id, data=msg.message_id)
                    await asyncio.sleep(0.5) # جلوگیری از فلود
            except Exception as e:
                logger.error(f"Error sending package item: {e}")

        await send_reply(f"✅ {count} آیتم ارسال شد و تا ۲۰ ثانیه دیگر حذف می‌شوند.")
    
    else:
        await send_reply("❌ کد نامعتبر یا منقضی شده است.")

async def auto_delete_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception:
        pass # پیام قبلا حذف شده یا دسترسی نداریم

# ===== پنل ادمین =====
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    keyboard = [
        [InlineKeyboardButton("📤 آپلود ویدیو", callback_data="upload_video"),
         InlineKeyboardButton("📦 آپلود پکیج", callback_data="upload_package")],
        [InlineKeyboardButton("🎬 آپلود دمو", callback_data="upload_demo"),
         InlineKeyboardButton("📊 آمار", callback_data="show_stats")]
    ]
    await update.message.reply_text("🎛 پنل مدیریت:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id != ADMIN_ID: return

    if data == "upload_video":
        _user_state[user_id] = "uploading"
        await query.edit_message_text("🎬 ویدیو را ارسال کنید:")
    
    elif data == "upload_package":
        _user_state[user_id] = "uploading_package"
        _admin_temp_packages[user_id] = []
        await query.edit_message_text("📦 مدیاها را بفرستید. پایان با /finish_package")

    elif data == "upload_demo":
        _user_state[user_id] = "uploading_demo"
        await query.edit_message_text("🎬 ویدیو دمو را بفرستید:")

    elif data == "show_stats":
        stats = f"👥 کاربران: {len(load_users())}\n🎬 ویدیوها: {len(load_videos())}\n📦 پکیج‌ها: {len(load_packages())}"
        await query.edit_message_text(stats)

# ===== هندلر دریافت مدیا از ادمین =====
async def handle_admin_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID: return

    state = _user_state.get(user.id)
    if not state: return

    # استخراج فایل آیدی
    file_id = None
    msg_type = 'video'
    
    if update.message.video: file_id = update.message.video.file_id
    elif update.message.photo: 
        file_id = update.message.photo[-1].file_id
        msg_type = 'photo'
    elif update.message.document: # هندل کردن فایل
        mime = update.message.document.mime_type
        if mime and 'video' in mime: file_id = update.message.document.file_id
        elif mime and 'image' in mime: 
            file_id = update.message.document.file_id
            msg_type = 'photo'
    
    if not file_id:
        await update.message.reply_text("❌ فایل نامعتبر.")
        return

    if state == "uploading":
        code = generate_code()
        vids = load_videos()
        vids[code] = file_id
        save_videos(vids)
        await update.message.reply_text(f"✅ ذخیره شد.\n🔗 لینک: https://t.me/{context.bot.username}?start={code}")
        del _user_state[user.id]

    elif state == "uploading_package":
        _admin_temp_packages[user.id].append({'file_id': file_id, 'type': msg_type})
        await update.message.reply_text(f"➕ اضافه شد ({len(_admin_temp_packages[user.id])}).")

    elif state == "uploading_demo":
        code = generate_code()
        vids = load_videos()
        vids[code] = file_id
        save_videos(vids)
        _user_state[user.id] = "waiting_demo_msg"
        _pending_users[user.id] = code
        await update.message.reply_text("📝 حالا متن دمو را بفرستید:")

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID: return
    
    state = _user_state.get(user.id)
    if state == "waiting_demo_msg":
        code = _pending_users.get(user.id)
        msg = load_demo_messages()
        msg[code] = update.message.text
        save_demo_messages(msg)
        await update.message.reply_text(f"✅ دمو ساخته شد.\n🔗 لینک: https://t.me/{context.bot.username}?start={code}")
        del _user_state[user.id]
        del _pending_users[user.id]

async def finish_package_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID: return

    items = _admin_temp_packages.get(user.id, [])
    if not items:
        await update.message.reply_text("❌ لیست خالی است.")
        return

    code = generate_code()
    pkgs = load_packages()
    pkgs[code] = items
    save_packages(pkgs)
    
    del _admin_temp_packages[user.id]
    del _user_state[user.id]
    await update.message.reply_text(f"✅ پکیج ذخیره شد.\n🔗 لینک: https://t.me/{context.bot.username}?start={code}")

# ===== اجرای اصلی =====
if __name__ == "__main__":
    _ensure_files()
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN یافت نشد!")
        exit()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("finish_package", finish_package_command))
    
    # دکمه‌ها
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(admin_callback)) # سایر دکمه‌های ادمین
    
    # پیام‌ها
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_admin_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))

        # ===== متغیرهای Webhook =====
    PORT = int(os.environ.get('PORT', 8080))
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL', None)

    if not WEBHOOK_URL:
        # اگر WEBHOOK_URL در Zeabur تنظیم نشده باشد، باید آن را به صورت دستی پیدا و تنظیم کنید
        print("❌ WEBHOOK_URL در متغیرها نیست. لطفا آن را در Zeabur تنظیم کنید.")
        exit()

    # حذف هر گونه Webhook قبلی
    print("🔄 تنظیم Webhook...")
    
    # اجرای ربات در حالت Webhook
    # توجه: آدرس اصلی Zeabur باید با /bot/BOT_TOKEN ترکیب شود تا کار کند
    # PTB از شما میخواهد که URL را به /updater بفرستید
    # URL نهایی را باید از Zeabur بگیرید
    
    # برای جلوگیری از خطاهای SSL رایج در محیط های ابری
    context = None 
    
    # URL نهایی تلگرام
    webhook_path = "/webhook"
    
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=WEBHOOK_URL + webhook_path
    )
    
    print(f"✅ ربات با Webhook روی پورت {PORT} و آدرس {WEBHOOK_URL} روشن شد.")
    
          
