# ===== ایمپورت‌ها =====
import os, json, asyncio, random, string, logging, threading, time, gc
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    Defaults
)

# ===== تنظیمات Logging =====
logging.basicConfig(
    level=logging.WARNING, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ===== تنظیم مسیر دیسک دائمی Render =====
# تمام فایل‌های .json در این پوشه ذخیره خواهند شد
DATA_DIR = "/app/data" 
# اطمینان از وجود پوشه دیتا
os.makedirs(DATA_DIR, exist_ok=True)


# ===== بارگذاری توکن و اطلاعات =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
SECOND_CHANNEL_USERNAME = os.getenv("SECOND_CHANNEL_USERNAME")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except:
    ADMIN_ID = 0
    logging.warning("⚠️ ADMIN_ID معتبر نیست")

# ===== آدرس فایل‌ها (با استفاده از دیسک دائمی Render) =====
VIDEO_DB_FILE = os.path.join(DATA_DIR, "videos.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
PACKAGES_FILE = os.path.join(DATA_DIR, "packages.json")
DEMO_MESSAGES_FILE = os.path.join(DATA_DIR, "demo_messages.json")


# ===== کش‌ها (Cache) =====
# تمام داده‌ها ابتدا اینجا نگهداری می‌شوند
_videos_cache = None
_users_cache = None
_packages_cache = None
_demo_messages_cache = None
_user_state = {}
_pending_users = {}
_admin_temp_packages = {}
_pending_payments = {}
_payment_receipts = {}
_auto_delete_timers = {}
_user_start_args = {}

# ===== پرچم‌های Dirty (برای ذخیره‌سازی دسته‌ای) =====
_videos_dirty = False
_users_dirty = False
_packages_dirty = False
_demo_messages_dirty = False

# ===== ترد پس‌زمینه (ادغام پاکسازی و ذخیره‌سازی) =====
def background_tasks():
    """
    این ترد در پس‌زمینه اجرا می‌شود تا:
    1. تغییرات کش‌ها را به‌صورت دسته‌ای (هر 5 دقیقه) در فایل‌های JSON ذخیره کند.
    2. کش‌های موقت را برای جلوگیری از پر شدن حافظه (RAM) پاکسازی کند.
    """
    global _videos_dirty, _users_dirty, _packages_dirty, _demo_messages_dirty
    global _videos_cache, _users_cache, _packages_cache, _demo_messages_cache
    
    while True:
        time.sleep(300) # هر 5 دقیقه یکبار اجرا می‌شود
        
        try:
            # --- بخش 1: ذخیره‌سازی دوره‌ای (Batch Save) ---
            if _videos_dirty:
                try:
                    with open(VIDEO_DB_FILE, "w", encoding="utf-8") as f:
                        json.dump(_videos_cache, f, indent=2, ensure_ascii=False)
                    _videos_dirty = False
                    logging.info("Background save: videos.json updated.")
                except Exception as e:
                    logging.error(f"Failed to save videos.json: {e}")
            
            if _users_dirty:
                try:
                    with open(USERS_FILE, "w", encoding="utf-8") as f:
                        json.dump(_users_cache, f, indent=2)
                    _users_dirty = False
                    logging.info("Background save: users.json updated.")
                except Exception as e:
                    logging.error(f"Failed to save users.json: {e}")

            if _packages_dirty:
                try:
                    with open(PACKAGES_FILE, "w", encoding="utf-8") as f:
                        json.dump(_packages_cache, f, indent=2, ensure_ascii=False)
                    _packages_dirty = False
                    logging.info("Background save: packages.json updated.")
                except Exception as e:
                    logging.error(f"Failed to save packages.json: {e}")
            
            if _demo_messages_dirty:
                try:
                    with open(DEMO_MESSAGES_FILE, "w", encoding="utf-8") as f:
                        json.dump(_demo_messages_cache, f, indent=2, ensure_ascii=False)
                    _demo_messages_dirty = False
                    logging.info("Background save: demo_messages.json updated.")
                except Exception as e:
                    logging.error(f"Failed to save demo_messages.json: {e}")


            # --- بخش 2: پاکسازی کش‌های موقت ---
            global _pending_users, _user_state, _admin_temp_packages, _pending_payments, _payment_receipts, _auto_delete_timers, _user_start_args
            for data_dict in [_pending_users, _user_state, _admin_temp_packages, _pending_payments, _payment_receipts, _auto_delete_timers, _user_start_args]:
                if len(data_dict) > 200: 
                    data_dict.clear()
            
            gc.collect() 
            logging.info("Background cleanup finished.")
            
        except Exception as e:
            logging.error(f"Error in background_tasks: {e}")
            pass

# ===== مدیریت فایل‌ها =====
def _ensure_files():
    # این تابع در ابتدای اجرا فایل‌ها را در دیسک دائمی می‌سازد
    if not os.path.exists(VIDEO_DB_FILE):
        with open(VIDEO_DB_FILE, "w", encoding="utf-8") as f: json.dump({}, f)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f: json.dump([], f)
    if not os.path.exists(PACKAGES_FILE):
        with open(PACKAGES_FILE, "w", encoding="utf-8") as f: json.dump({}, f)
    if not os.path.exists(DEMO_MESSAGES_FILE):
        with open(DEMO_MESSAGES_FILE, "w", encoding="utf-8") as f: json.dump({}, f)

# --- توابع Load (بارگذاری از فایل به کش در صورت خالی بودن کش) ---
def load_videos():
    global _videos_cache
    if _videos_cache is not None: return _videos_cache.copy()
    try:
        with open(VIDEO_DB_FILE, "r", encoding="utf-8") as f: _videos_cache = json.load(f)
        return _videos_cache.copy()
    except: 
        _videos_cache = {}
        return {}

def load_packages():
    global _packages_cache
    if _packages_cache is not None: return _packages_cache.copy()
    try:
        with open(PACKAGES_FILE, "r", encoding="utf-8") as f: _packages_cache = json.load(f)
        return _packages_cache.copy()
    except: 
        _packages_cache = {}
        return {}

def load_demo_messages():
    global _demo_messages_cache
    if _demo_messages_cache is not None: return _demo_messages_cache.copy()
    try:
        with open(DEMO_MESSAGES_FILE, "r", encoding="utf-8") as f: _demo_messages_cache = json.load(f)
        return _demo_messages_cache.copy()
    except: 
        _demo_messages_cache = {}
        return {}

def load_users():
    global _users_cache
    if _users_cache is not None: return _users_cache.copy()
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f: _users_cache = json.load(f)
        return _users_cache.copy()
    except: 
        _users_cache = []
        return []

# --- توابع Save (بهینه‌سازی شده برای نوشتن در کش) ---
# این توابع دیگر مستقیما در فایل *نمی‌نویسند*
# فقط کش را آپدیت می‌کنند و پرچم dirty را True می‌کنند

def save_videos(data):
    global _videos_cache, _videos_dirty
    _videos_cache = data.copy()
    _videos_dirty = True

def save_packages(data):
    global _packages_cache, _packages_dirty
    _packages_cache = data.copy()
    _packages_dirty = True

def save_demo_messages(data):
    global _demo_messages_cache, _demo_messages_dirty
    _demo_messages_cache = data.copy()
    _demo_messages_dirty = True

def save_users(data):
    global _users_cache, _users_dirty
    _users_cache = data.copy()
    _users_dirty = True

def add_user(user_id):
    users = load_users() 
    if user_id not in users:
        users.append(user_id)
        save_users(users) 

def generate_code(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# ===== بررسی عضویت اجباری (بدون تغییر) =====
async def check_membership(user_id, context):
    channels_to_check = []

    if CHANNEL_USERNAME and CHANNEL_USERNAME.strip():
        channel = CHANNEL_USERNAME.strip()
        if not channel.startswith('@'):
            channel = '@' + channel
        channels_to_check.append(channel)

    if SECOND_CHANNEL_USERNAME and SECOND_CHANNEL_USERNAME.strip():
        channel = SECOND_CHANNEL_USERNAME.strip()
        if not channel.startswith('@'):
            channel = '@' + channel
        channels_to_check.append(channel)

    if not channels_to_check:
        return True

    for channel in channels_to_check:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logging.error(f"خطا در بررسی عضویت: {e}")
            return False

    return True

async def show_membership_required(update: Update, context: ContextTypes.DEFAULT_TYPE, start_args=None):
    user_id = update.effective_user.id

    if start_args:
        _user_start_args[user_id] = start_args

    keyboard = []

    if CHANNEL_USERNAME and CHANNEL_USERNAME.strip():
        channel_username = CHANNEL_USERNAME.strip().replace('@', '')
        keyboard.append([InlineKeyboardButton("📢 کانال اول", url=f"https://t.me/{channel_username}")])

    if SECOND_CHANNEL_USERNAME and SECOND_CHANNEL_USERNAME.strip():
        channel_username = SECOND_CHANNEL_USERNAME.strip().replace('@', '')
        keyboard.append([InlineKeyboardButton("📢 کانال دوم", url=f"https://t.me/{channel_username}")])

    keyboard.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_membership")])

    text = "⚠️ برای استفاده از ربات و دریافت ویدیوها باید عضو این دو کانال باشی عزیزم:\n\n"
    if CHANNEL_USERNAME and CHANNEL_USERNAME.strip():
        text += f"🔹 @{CHANNEL_USERNAME.strip().replace('@', '')}\n"
    if SECOND_CHANNEL_USERNAME and SECOND_CHANNEL_USERNAME.strip():
        text += f"🔹 @{SECOND_CHANNEL_USERNAME.strip().replace('@', '')}\n"
    text += "\nبعد اینکه عضو شدی دکمه تایید عضویت و بزن عشقم."

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def send_video_after_membership(user_id, context, start_args=None):
    try:
        vids = load_videos()
        packages = load_packages()
        demo_messages = load_demo_messages()

        if start_args:
            code = start_args[0]

            if code in vids:
                file_id = vids[code]
                sent_message = await context.bot.send_video(
                    chat_id=user_id,
                    video=file_id,
                    caption="🎥 این ویدیو فقط ۲۰ ثانیه قابل مشاهده است! لطفا ان را در پیامهای ذخیره شده خود ذخیره کنید"
                )

                if code in demo_messages:
                    demo_text = demo_messages[code]
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=demo_text
                    )

                job_name = f"delete_video_{sent_message.message_id}"
                context.job_queue.run_once(
                    auto_delete_video,
                    15,
                    chat_id=user_id,
                    data=sent_message.message_id,
                    name=job_name
                )
                return True

            elif code in packages:
                package = packages[code]
                media_count = 0

                for media_item in package:
                    try:
                        if isinstance(media_item, str):
                            sent_message = await context.bot.send_video(
                                chat_id=user_id,
                                video=media_item,
                                caption=f"🎥 ویدیو {media_count + 1} از {len(package)}"
                            )
                        elif isinstance(media_item, dict):
                            if media_item.get('type') == 'photo':
                                sent_message = await context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=media_item['file_id'],
                                    caption=f"🖼 عکس {media_count + 1} از {len(package)}"
                                )
                            else:
                                sent_message = await context.bot.send_video(
                                    chat_id=user_id,
                                    video=media_item['file_id'],
                                    caption=f"🎥 ویدیو {media_count + 1} از {len(package)}"
                                )
                        
                        media_count += 1

                        job_name = f"delete_video_{sent_message.message_id}"
                        context.job_queue.run_once(
                            auto_delete_video,
                            15,
                            chat_id=user_id,
                            data=sent_message.message_id,
                            name=job_name
                        )

                        await asyncio.sleep(0.2) 

                    except Exception as e:
                        continue

                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ {media_count} مدیا ارسال شد.مدیا ها پس از 20 ثانیه به طور خودکار حذف میشن، برای دسترسی مجدد آنها را در پیامهای ذخیره شده خود ذخیره کنید"
                )
                return True

        return False
    except Exception as e:
        return False

async def auto_delete_video(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    message_id = job.data

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        pass 

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین دسترسی دارد.")
        return

    keyboard = [
        [InlineKeyboardButton("📤 آپلود ویدیو", callback_data="upload_video"),
         InlineKeyboardButton("📦 آپلود پکیج", callback_data="upload_package")],
        [InlineKeyboardButton("🎬 آپلود دمو", callback_data="upload_demo")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="show_stats")]
    ]

    await update.message.reply_text(
        "🎛️ پنل مدیریت:\n\n"
        "• 📤 آپلود ویدیو: آپلود یک ویدیو\n"
        "• 📦 آپلود پکیج: آپلود چند ویدیو یا عکس به عنوان پکیج\n"
        "• 🎬 آپلود دمو: آپلود ویدیو با پیام دلخواه\n"
        "• 📊 آمار ربات: مشاهده آمار ربات",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ فقط ادمین دسترسی دارد.")
        return

    user_id = query.from_user.id
    data = query.data

    if data == "upload_video":
        _user_state[user_id] = "uploading"
        await query.edit_message_text("🎬 لطفاً ویدیو رو ارسال کن:")

    elif data == "upload_package":
        _user_state[user_id] = "uploading_package"
        _admin_temp_packages[user_id] = []
        await query.edit_message_text("📦 ویدیوها و عکس‌ها را یکی یکی ارسال کن و در انتها دستور /finish_package را بفرست.")

    elif data == "upload_demo":
        _user_state[user_id] = "uploading_demo"
        await query.edit_message_text("🎬 لطفاً ویدیو رو برای دمو ارسال کن:")

    elif data == "show_stats":
        users = load_users()
        vids = load_videos()
        packages = load_packages()
        demo_messages = load_demo_messages()
        stats_text = (
            f"📊 آمار ربات:\n"
            f"👥 تعداد کاربران: {len(users)}\n"
            f"🎬 ویدیوها: {len(vids)}\n"
            f"📦 پکیج‌ها: {len(packages)}\n"
            f"🎬 دموها: {len(demo_messages)}"
        )
        await query.edit_message_text(stats_text)

async def handle_media_from_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    video = update.message.video
    photo = update.message.photo
    document = update.message.document
    
    file_id = None
    media_type = None

    if video:
        file_id = video.file_id
        media_type = 'video'
    elif photo:
        file_id = photo[-1].file_id 
        media_type = 'photo'
    elif document:
        if document.mime_type and document.mime_type.startswith('video/'):
            file_id = document.file_id
            media_type = 'video'
        elif document.mime_type and document.mime_type.startswith('image/'):
            file_id = document.file_id
            media_type = 'photo'

    if not file_id:
        await update.message.reply_text("لطفاً یک ویدیو یا عکس ارسال کنید.")
        return

    state = _user_state.get(user.id)

    if state == "uploading":
        code = generate_code()
        vids = load_videos()
        vids[code] = file_id
        save_videos(vids) # بهینه‌سازی شده: فقط در کش می‌نویسد
        link = f"https://t.me/{context.bot.username}?start={code}"
        await update.message.reply_text(f"✅ ویدیو ذخیره شد!\n🔗 لینک: {link}")
        _user_state.pop(user.id, None)

    elif state == "uploading_package":
        if user.id not in _admin_temp_packages:
            _admin_temp_packages[user_id] = []
        
        media_data = {'file_id': file_id, 'type': media_type}
        _admin_temp_packages[user.id].append(media_data)
        count = len(_admin_temp_packages[user.id])
        media_type_farsi = "عکس" if media_type == 'photo' else "ویدیو"
        await update.message.reply_text(f"✅ {media_type_farsi} {count} اضافه شد. برای پایان /finish_package")

    elif state == "uploading_demo":
        code = generate_code()
        vids = load_videos()
        vids[code] = file_id
        save_videos(vids) # بهینه‌سازی شده: فقط در کش می‌نویسد

        _user_state[user.id] = "waiting_demo_message"
        _pending_users[user.id] = code
        await update.message.reply_text("✅ ویدیو ذخیره شد! حالا پیام دمو را ارسال کنید:")

async def handle_demo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    state = _user_state.get(user.id)
    if state == "waiting_demo_message":
        demo_text = update.message.text
        code = _pending_users.get(user.id)

        if code and demo_text:
            demo_messages = load_demo_messages()
            demo_messages[code] = demo_text
            save_demo_messages(demo_messages) # بهینه‌سازی شده: فقط در کش می‌نویسد

            link = f"https://t.me/{context.bot.username}?start={code}"
            await update.message.reply_text(
                f"✅ دمو ذخیره شد!\n\n"
                f"🔗 لینک: {link}\n"
                f"📝 پیام دمو: {demo_text}"
            )

            _user_state.pop(user.id, None)
            _pending_users.pop(user.id, None)

async def finish_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return

    if user.id not in _admin_temp_packages or not _admin_temp_packages[user.id]:
        await update.message.reply_text("❌ هیچ مدیایی اضافه نشده است.")
        return

    package_files = _admin_temp_packages[user.id]
    code = generate_code()
    packages = load_packages()
    packages[code] = package_files
    save_packages(packages) # بهینه‌سازی شده: فقط در کش می‌نویسد

    link = f"https://t.me/{context.bot.username}?start={code}"
    await update.message.reply_text(f"✅ پکیج با {len(package_files)} مدیا ذخیره شد!\n🔗 لینک: {link}")

    _user_state.pop(user.id, None)
    _admin_temp_packages.pop(user.id, None)

async def start_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    args = context.args
    add_user(user.id) # بهینه‌سازی شده: فقط در کش می‌نویسد

    is_member = await check_membership(user.id, context)

    if not is_member:
        await show_membership_required(update, context, args)
        return

    if args:
        await send_media_content(update, context, args[0])
    else:
        welcome_text = "👋 سلام! برای دریافت ویدیو از لینک مخصوص استفاده کنید."
        await update.message.reply_text(welcome_text)

async def send_media_content(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    vids = load_videos()
    packages = load_packages()
    demo_messages = load_demo_messages()

    if code in vids:
        file_id = vids[code]
        sent_message = await update.message.reply_video(
            file_id,
            caption="🎥 این ویدیو تا ۲۰ ثانیه قابل مشاهده است و پس از آن به طور خودکار حذف خواهد شد، برای دسترسی مجدد لطفاً آن را به پیام های ذخیره شده خود(saved massage) ارسال کنید❌!"
        )

        if code in demo_messages:
            demo_text = demo_messages[code]
            await update.message.reply_text(demo_text)

        job_name = f"delete_video_{sent_message.message_id}"
        context.job_queue.run_once(
            auto_delete_video,
            15,
            chat_id=update.effective_chat.id,
            data=sent_message.message_id,
            name=job_name
        )

    elif code in packages:
        package = packages[code]
        media_count = 0

        for i, media_item in enumerate(package):
            try:
                if isinstance(media_item, str):
                    sent_message = await update.message.reply_video(
                        media_item,
                        caption=f"🎥 ویدیو {i + 1} از {len(package)}"
                    )
                elif isinstance(media_item, dict):
                    if media_item.get('type') == 'photo':
                        sent_message = await update.message.reply_photo(
                            media_item['file_id'],
                            caption=f"🖼 عکس {i + 1} از {len(package)}"
                        )
                    else:
                        sent_message = await update.message.reply_video(
                            media_item['file_id'],
                            caption=f"🎥 ویدیو {i + 1} از {len(package)}"
                        )

                media_count += 1
                job_name = f"delete_video_{sent_message.message_id}"
                context.job_queue.run_once(
                    auto_delete_video,
                    15,
                    chat_id=update.effective_chat.id,
                    data=sent_message.message_id,
                    name=job_name
                )
                await asyncio.sleep(0.2) 
            except Exception as e:
                logging.warning(f"Failed to send media {i} in package {code}: {e}")
                continue
        
        await update.message.reply_text(
            f"✅ {media_count} مدیا ارسال شد.مدیا ها پس از 20 ثانیه به طور خودکار حذف میشن، برای دسترسی مجدد آنها را در پیامهای ذخیره شده خود ذخیره کنید"
        )
    
    else:
        # اگر کد وجود نداشت
        await update.message.reply_text("❌ لینک یا کد مورد نظر یافت نشد یا منقضی شده است.")

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 در حال بررسی عضویت...")

    user_id = query.from_user.id
    is_member = await check_membership(user_id, context)

    if is_member:
        await query.edit_message_text("✅ عضویت شما تایید شد! خوش آمدید.")
        
        start_args = _user_start_args.pop(user_id, None)
        if start_args:
            await send_video_after_membership(user_id, context, start_args)
        else:
             await context.bot.send_message(user_id, "👋 سلام! برای دریافت ویدیو از لینک مخصوص استفاده کنید.")

    else:
        await query.answer("❌ هنوز عضو همه‌ی کانال‌ها نشده‌اید!", show_alert=True)


# ===== تابع Main (برای اجرا) =====
def main():
    if not BOT_TOKEN:
        logging.critical("❌ توکن ربات (BOT_TOKEN) یافت نشد! لطفا متغیرهای محیطی Render را بررسی کنید.")
        return
    if ADMIN_ID == 0:
        logging.warning("⚠️ ADMIN_ID تنظیم نشده است. پنل ادمین کار نخواهد کرد.")

    # 1. اطمینان از وجود فایل‌ها در دیسک دائمی
    _ensure_files()

    # 2. بارگذاری اولیه‌ی کش‌ها از فایل‌ها
    load_videos()
    load_users()
    load_packages()
    load_demo_messages()
    logging.warning("Initial cache loaded from persistent disk.")

    # 3. راه‌اندازی ترد پس‌زمینه
    bg_thread = threading.Thread(target=background_tasks, daemon=True)
    bg_thread.start()
    logging.warning("Background tasks thread started (Save/Cleanup every 5 min).")

    # 4. ساخت اپلیکیشن ربات
    defaults = Defaults(parse_mode="HTML")
    application = ApplicationBuilder().token(BOT_TOKEN).defaults(defaults).build()

    # --- 5. ثبت هندلرها ---

    # دستورات ادمین
    application.add_handler(CommandHandler("admin", admin_panel, filters=filters.User(ADMIN_ID)))
    application.add_handler(CommandHandler("finish_package", finish_package, filters=filters.User(ADMIN_ID)))

    # دکمه‌های پنل ادمین
    application.add_handler(CallbackQueryHandler(handle_admin_buttons, pattern="^(upload_video|upload_package|upload_demo|show_stats)$"))

    # دکمه بررسی عضویت
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))

    # دستور /start
    application.add_handler(CommandHandler("start", start_link, filters=filters.ChatType.PRIVATE))

    # هندلرهای ادمین برای دریافت مدیا و پیام دمو
    admin_media_filter = (filters.VIDEO | filters.PHOTO | filters.Document.ALL) & filters.User(ADMIN_ID)
    application.add_handler(MessageHandler(admin_media_filter, handle_media_from_admin))
    
    # (رفع خطای تایپی قبلی: ADMIN_SYSTEM به ADMIN_ID تصحیح شد)
    demo_message_filter = filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID)
    application.add_handler(MessageHandler(demo_message_filter, handle_demo_message))

    # (اختیاری) یک هندلر برای پیام‌های متنی عادی از کاربران
    async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start_link(update, context) # همان رفتار /start را اجرا می‌کند
    
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, echo))


    # --- 6. اجرای ربات ---
    logging.warning("Bot is starting to poll...")
    application.run_polling()

if __name__ == "__main__":
    main()
