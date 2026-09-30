"""
TraceX Lookup Bot - FREE VERSION (Reply Keyboard)
Version: 14.0.0 - Free, Reply Keyboard, 2 Services
"""

import os
import sys

def _require_package(import_name, pip_name=None):
    try:
        return __import__(import_name)
    except ImportError:
        name = pip_name or import_name
        print(f"❌ Missing dependency: {name}")
        print(f"Install it with: pip install {name}")
        raise

telebot = _require_package("telebot", "pyTelegramBotAPI")
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
requests = _require_package("requests", "requests")
import time
import re
import json
import threading
import signal
from flask import Flask

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Missing BOT_TOKEN env variable")
    sys.exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "7850023357"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "gauravbeniwalx")

LOOKUP_API_BASE = "https://gauravbeniwal.online/lookupportal/api/lookup.php"
WEBSITE_URL = "https://gauravbeniwal.online/lookupportal"
BOT_VERSION = "14.0.0"

RATE_LIMIT_SECONDS = 30
TELEGRAM_SAFE_LIMIT = 3900

REQUIRED_CHANNELS = [
    {"name": "Gaurav Beniwal", "id": "@Gaurav_beni_0001", "link": "https://t.me/Gaurav_beni_0001"},
    {"name": "Beniwal Mods", "id": "@beniwalmods", "link": "https://t.me/beniwalmods"},
    {"name": "Beniwalzon YT", "id": "@BeniwalzonYT", "link": "https://t.me/BeniwalzonYT"},
    {"name": "Private Community", "id": -1003004551707, "link": "https://t.me/+j7KaRgC8l14zODc1"},
]

LOOKUP_SERVICES = {
    "number": {"name": "Number Info", "emoji": "📱", "query_type": "mobile"},
    "telegram": {"name": "Telegram to Number", "emoji": "💬", "query_type": "username"},
}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)

user_states = {}
user_last_lookup = {}
active_sessions = set()
active_sessions_lock = threading.Lock()

# ==================== HELPERS ====================
def escape_html(text):
    if text is None:
        return ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def format_json_for_telegram(data):
    try:
        if isinstance(data, (dict, list)):
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            json_str = str(data)
        json_str = json_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<pre>{json_str}</pre>"
    except Exception as e:
        print(f"JSON format error: {e}")
        return f"<pre>{escape_html(str(data))}</pre>"

def footer():
    return f"\n\n━━━━━━━━━━━━━━━━\n🌐 {WEBSITE_URL}\n👨‍💻 @{ADMIN_USERNAME}"

def get_main_keyboard():
    """Reply keyboard — main menu (no credits, no buy)"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📱 NUMBER INFO"),
        KeyboardButton("💬 TG TO NUMBER")
    )
    keyboard.add(
        KeyboardButton("📢 SUPPORT")
    )
    return keyboard

def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(KeyboardButton("❌ CANCEL"))
    return keyboard

def get_channel_join_markup():
    """Inline buttons ONLY for channel join — no other inline"""
    markup = InlineKeyboardMarkup(row_width=1)
    for channel in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 {channel['name']}", url=channel['link']))
    markup.add(InlineKeyboardButton("✅ I HAVE JOINED", callback_data="check_join"))
    return markup

def lookup_result_markup():
    """Small inline buttons for result actions (optional but useful)"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔍 NEW SEARCH", callback_data="back_to_lookup"),
        InlineKeyboardButton("🏠 MENU", callback_data="main_menu")
    )
    return markup

def is_active_session(user_id):
    with active_sessions_lock:
        return user_id in active_sessions

def add_active_session(user_id):
    with active_sessions_lock:
        active_sessions.add(user_id)

def remove_active_session(user_id):
    with active_sessions_lock:
        active_sessions.discard(user_id)

def split_long_text(text, limit=TELEGRAM_SAFE_LIMIT):
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    pre_start = text.find("<pre>")
    pre_end = text.rfind("</pre>")
    if pre_start != -1 and pre_end != -1 and pre_start < pre_end:
        before = text[:pre_start]
        inner = text[pre_start + len("<pre>"):pre_end]
        after = text[pre_end + len("</pre>"):]
        chunk_budget = max(500, limit - 400)
        chunks, lines, current, first_chunk = [], inner.split("\n"), "", True
        for line in lines:
            candidate = (current + "\n" + line) if current else line
            if len(candidate) > chunk_budget and current:
                prefix = before if first_chunk else ""
                chunks.append(f"{prefix}<pre>{current}</pre>")
                first_chunk = False
                current = line
            else:
                current = candidate
        if current or first_chunk:
            prefix = before if first_chunk else ""
            chunks.append(f"{prefix}<pre>{current}</pre>")
        if after and chunks:
            chunks[-1] = chunks[-1] + after
        return chunks if chunks else [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [""]

def send_or_edit_long_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    chunks = split_long_text(text)
    sent_messages = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        is_first = idx == 0
        is_last = idx == total - 1
        markup = reply_markup if is_last else None
        body = f"<b>📄 Part {idx + 1}/{total}</b>\n{chunk}" if total > 1 else chunk
        if len(body) > 4096:
            body = body[:4090] + "…"
        try:
            if is_first:
                sent_messages.append(bot.edit_message_text(
                    body, chat_id, message_id, reply_markup=markup,
                    parse_mode=parse_mode, disable_web_page_preview=True))
            else:
                sent_messages.append(bot.send_message(
                    chat_id, body, reply_markup=markup,
                    parse_mode=parse_mode, disable_web_page_preview=True))
        except Exception as e:
            print(f"Long message send error: {e}")
            try:
                plain = re.sub(r"<[^>]+>", "", body)
                if is_first:
                    sent_messages.append(bot.edit_message_text(
                        plain, chat_id, message_id, reply_markup=markup,
                        disable_web_page_preview=True))
                else:
                    sent_messages.append(bot.send_message(
                        chat_id, plain, reply_markup=markup,
                        disable_web_page_preview=True))
            except Exception as e2:
                print(f"Fallback send failed: {e2}")
    return sent_messages

def safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup,
                                     parse_mode=parse_mode, disable_web_page_preview=True)
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return None
        try:
            plain = re.sub(r"<[^>]+>", "", str(text))
            return bot.edit_message_text(plain, chat_id, message_id,
                                         reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception as e2:
            print(f"safe_edit_message failed: {e} / fallback: {e2}")
            return None

def normalize_indian_mobile(value):
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits if re.match(r"^[6-9]\d{9}$", digits) else None

# ==================== LOOKUP API ====================
def call_lookup_api(service, query):
    try:
        url = f"{LOOKUP_API_BASE}?service={service}&spell={query}"
        print(f"[LOOKUP] Service: {service}, Query: {query}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 16) TraceXBot/14.0.0",
            "Accept": "application/json",
        }
        response = requests.get(url, headers=headers, timeout=(10, 25))
        print(f"[LOOKUP] Status: {response.status_code}")
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}", "success": False}
        content = response.text
        if not content or len(content.strip()) < 5:
            return {"error": "empty_response", "success": False}
        try:
            return response.json()
        except Exception:
            return {"raw_response": content, "success": True}
    except requests.exceptions.Timeout:
        return {"error": "timeout", "success": False}
    except requests.exceptions.ConnectionError:
        return {"error": "connection_error", "success": False}
    except Exception as e:
        return {"error": f"exception_{e}", "success": False}

# ==================== CHANNEL CHECK ====================
def is_channel_member(user_id, channel_id):
    if str(user_id) == str(ADMIN_ID):
        return True
    try:
        member = bot.get_chat_member(channel_id, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Channel check error for {channel_id}: {e}")
        return False

def check_all_channels(user_id):
    if str(user_id) == str(ADMIN_ID):
        return True, []
    missing = []
    for channel in REQUIRED_CHANNELS:
        if not is_channel_member(user_id, channel['id']):
            missing.append(channel)
    return len(missing) == 0, missing

def send_join_required(chat_id, missing_channels=None):
    if missing_channels is None:
        all_joined, missing_channels = check_all_channels(chat_id)
        if all_joined:
            return True
    if missing_channels:
        channel_list = "\n".join([f"• {ch['name']}" for ch in missing_channels])
        message = f"""🔒 <b>JOIN REQUIRED</b>
━━━━━━━━━━━━━━━━━━

Bot use karne ke liye in channels ko join karo:

{channel_list}

━━━━━━━━━━━━━━━━━━
✅ Join karne ke baad <b>I HAVE JOINED</b> dabao"""
        bot.send_message(chat_id, message, reply_markup=get_channel_join_markup(),
                         parse_mode="HTML", disable_web_page_preview=True)
        return False
    return True

# ==================== LOOKUP PROCESSOR ====================
def process_lookup(message):
    user_id = message.from_user.id
    query_input = str(message.text or "").strip()

    if query_input == "❌ CANCEL" or query_input == "/cancel":
        user_states.pop(user_id, None)
        remove_active_session(user_id)
        bot.reply_to(message, "❌ <b>Cancelled.</b>",
                     reply_markup=get_main_keyboard(), parse_mode='HTML')
        return

    state = user_states.get(user_id)
    if not (isinstance(state, dict) and state.get("state") == "awaiting_lookup"):
        return

    service_key = state.get("service")
    user_states.pop(user_id, None)

    service = LOOKUP_SERVICES.get(service_key)
    if not service:
        bot.reply_to(message, "❌ <b>Invalid service.</b>",
                     reply_markup=get_main_keyboard(), parse_mode='HTML')
        return

    query_clean = query_input
    if service["query_type"] == "mobile":
        phone = normalize_indian_mobile(query_input)
        if not phone:
            user_states[user_id] = {"state": "awaiting_lookup", "service": service_key}
            bot.reply_to(message,
                "❌ <b>Invalid number!</b>\n\n"
                "10-digit mobile number bhejo (6/7/8/9 se start).\n\n"
                "<b>Example:</b> <code>9876543210</code>",
                reply_markup=get_cancel_keyboard(), parse_mode='HTML')
            return
        query_clean = phone
    elif service["query_type"] == "username":
        query_clean = query_input.lstrip('@').strip()
        if not query_clean or len(query_clean) < 3 or not re.match(r"^[A-Za-z0-9_]{3,32}$", query_clean):
            user_states[user_id] = {"state": "awaiting_lookup", "service": service_key}
            bot.reply_to(message,
                "❌ <b>Invalid username!</b>\n\n"
                "Valid Telegram username bhejo (3-32 chars, letters/numbers/_).\n\n"
                "<b>Example:</b> <code>username</code>",
                reply_markup=get_cancel_keyboard(), parse_mode='HTML')
            return

    now = time.time()
    last = user_last_lookup.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS and str(user_id) != str(ADMIN_ID):
        wait_time = int(RATE_LIMIT_SECONDS - (now - last))
        bot.reply_to(message,
            f"⏳ <b>Wait {wait_time}s</b>\n\nRate limit: 1 lookup / 30 sec.",
            reply_markup=get_main_keyboard(), parse_mode='HTML')
        return

    if is_active_session(user_id):
        bot.reply_to(message, "⏳ <b>Search already in progress...</b>",
                     reply_markup=get_main_keyboard(), parse_mode='HTML')
        return

    add_active_session(user_id)
    user_last_lookup[user_id] = now
    loading_msg = None

    try:
        loading_msg = bot.reply_to(message,
            f"<b>{service['emoji']} Searching...</b>\n\n<i>Please wait...</i>",
            parse_mode='HTML')
        time.sleep(0.4)
        result = call_lookup_api(service_key, query_clean)

        if not result or result.get('error'):
            output = (f"<b>{service['emoji']} {service['name'].upper()}</b>\n"
                      f"━━━━━━━━━━━━━━━━━━\n\n"
                      f"🔎 Query: <code>{escape_html(query_clean)}</code>\n\n"
                      f"<b>❌ Error</b>\n"
                      f"{format_json_for_telegram(result or {'error': 'No response'})}")
            safe_edit_message(message.chat.id, loading_msg.message_id, output, parse_mode='HTML')
            return

        json_output = format_json_for_telegram(result)
        output = (f"<b>{service['emoji']} {service['name'].upper()}</b>\n"
                  f"━━━━━━━━━━━━━━━━━━\n\n"
                  f"🔎 Query: <code>{escape_html(query_clean)}</code>\n\n"
                  f"📄 <b>Result:</b>\n{json_output}\n\n"
                  f"━━━━━━━━━━━━━━━━━━\n"
                  f"✅ <b>Lookup Complete</b>")
        output += footer()
        send_or_edit_long_message(message.chat.id, loading_msg.message_id, output,
                                  reply_markup=lookup_result_markup(), parse_mode='HTML')
    except Exception as e:
        print(f"process_lookup error: {e}")
        try:
            if loading_msg:
                safe_edit_message(message.chat.id, loading_msg.message_id,
                    f"❌ <b>Search failed!</b>\n\n<code>{escape_html(str(e)[:100])}</code>",
                    parse_mode='HTML')
            else:
                bot.reply_to(message, "❌ <b>Search failed!</b>", parse_mode='HTML')
        except Exception as inner:
            print(f"Error notify: {inner}")
    finally:
        remove_active_session(user_id)

# ==================== HANDLERS ====================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "User"

    # Channel check on every /start
    all_joined, missing = check_all_channels(user_id)
    if not all_joined:
        send_join_required(message.chat.id, missing)
        return

    welcome_msg = (f"🚀 <b>TRACEX LOOKUP</b>\n"
                   f"━━━━━━━━━━━━━━━━━━\n\n"
                   f"👋 Welcome, <b>{escape_html(first_name)}</b>!\n\n"
                   f"✅ All channels joined.\n"
                   f"🎁 <b>100% FREE</b>\n"
                   f"⏱️ Rate limit: 1 lookup / 30 sec\n\n"
                   f"━━━━━━━━━━━━━━━━━━\n"
                   f"📋 <b>Services:</b>\n\n"
                   f"📱 <b>Number Info</b> — 10-digit mobile number\n"
                   f"💬 <b>TG to Number</b> — Telegram username\n\n"
                   f"━━━━━━━━━━━━━━━━━━\n"
                   f"🌐 {WEBSITE_URL}\n"
                   f"👨‍💻 @{ADMIN_USERNAME}\n\n"
                   f"👇 Neeche buttons se service choose karo")

    bot.send_message(message.chat.id, welcome_msg,
                     reply_markup=get_main_keyboard(),
                     parse_mode='HTML',
                     disable_web_page_preview=True)

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    remove_active_session(user_id)
    bot.reply_to(message, "❌ <b>Cancelled.</b>",
                 reply_markup=get_main_keyboard(), parse_mode='HTML')

@bot.message_handler(content_types=['text'])
def text_handler(message):
    user_id = message.from_user.id
    text = message.text.strip()

    # Check state FIRST (so user can send number/username without channel re-check blocking)
    state = user_states.get(user_id)
    if isinstance(state, dict) and state.get("state") == "awaiting_lookup":
        # Silent channel re-check
        all_joined, missing = check_all_channels(user_id)
        if not all_joined:
            user_states.pop(user_id, None)
            send_join_required(message.chat.id, missing)
            return
        process_lookup(message)
        return

    # Channel check for other actions
    all_joined, missing = check_all_channels(user_id)
    if not all_joined:
        send_join_required(message.chat.id, missing)
        return

    # Main menu buttons
    if text == "📱 NUMBER INFO":
        user_states[user_id] = {"state": "awaiting_lookup", "service": "number"}
        bot.reply_to(message,
            "📱 <b>NUMBER INFO</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Ab <b>10-digit mobile number</b> bhejo.\n\n"
            "<b>Example:</b> <code>9876543210</code>\n\n"
            "⏱️ Rate limit: 1 lookup / 30 sec",
            reply_markup=get_cancel_keyboard(), parse_mode='HTML')

    elif text == "💬 TG TO NUMBER":
        user_states[user_id] = {"state": "awaiting_lookup", "service": "telegram"}
        bot.reply_to(message,
            "💬 <b>TG TO NUMBER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Ab <b>Telegram username</b> bhejo.\n\n"
            "<b>Example:</b> <code>username</code>\n\n"
            "⏱️ Rate limit: 1 lookup / 30 sec",
            reply_markup=get_cancel_keyboard(), parse_mode='HTML')

    elif text == "📢 SUPPORT":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("👨‍💻 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME}"))
        markup.add(InlineKeyboardButton("🌐 WEBSITE", url=WEBSITE_URL))
        bot.reply_to(message,
            f"📢 <b>Support</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👨‍💻 @{ADMIN_USERNAME}\n"
            f"🌐 {WEBSITE_URL}\n\n"
            f"Koi bhi issue ho toh admin se contact karo.",
            reply_markup=markup, parse_mode='HTML')

    elif text == "❌ CANCEL":
        user_states.pop(user_id, None)
        remove_active_session(user_id)
        bot.reply_to(message, "❌ <b>Cancelled.</b>",
                     reply_markup=get_main_keyboard(), parse_mode='HTML')

    else:
        bot.reply_to(message,
            "❌ <b>Unknown command.</b>\n\nNeeche buttons use karo.",
            reply_markup=get_main_keyboard(), parse_mode='HTML')

# ==================== CALLBACKS ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data or ""
    print(f"[CB] user={user_id} data={data}")

    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"answer_cb error: {e}")

    # check_join
    if data == "check_join":
        all_joined, missing = check_all_channels(user_id)
        if all_joined:
            try:
                bot.answer_callback_query(call.id, "✅ Verified!", show_alert=True)
            except Exception:
                pass
            try:
                bot.edit_message_text(
                    "✅ <b>Verified!</b>\n\nAb /start bhejo ya buttons use karo.",
                    call.message.chat.id, call.message.message_id,
                    parse_mode="HTML")
            except Exception:
                pass
            try:
                bot.send_message(call.message.chat.id,
                                 "✅ <b>Verified!</b>\n\nNeeche buttons use karo.",
                                 reply_markup=get_main_keyboard(), parse_mode="HTML")
            except Exception:
                pass
        else:
            try:
                bot.answer_callback_query(call.id,
                    f"❌ Missing: {', '.join([ch['name'] for ch in missing])}",
                    show_alert=True)
            except Exception:
                pass
            send_join_required(call.message.chat.id, missing)
        return

    # Channel gate for other callbacks
    all_joined, missing = check_all_channels(user_id)
    if not all_joined:
        try:
            bot.answer_callback_query(call.id, "❌ Join all channels first!", show_alert=True)
        except Exception:
            pass
        send_join_required(call.message.chat.id, missing)
        return

    if data == "main_menu":
        try:
            bot.edit_message_text("🏠 <b>Main Menu</b>\n\nNeeche buttons use karo.",
                                  call.message.chat.id, call.message.message_id,
                                  parse_mode='HTML')
        except Exception:
            pass
        try:
            bot.send_message(call.message.chat.id,
                             "🏠 <b>Main Menu</b>",
                             reply_markup=get_main_keyboard(), parse_mode='HTML')
        except Exception:
            pass
        return

    if data == "back_to_lookup":
        try:
            bot.send_message(call.message.chat.id,
                             "👇 <b>Neeche buttons se service choose karo:</b>",
                             reply_markup=get_main_keyboard(), parse_mode='HTML')
        except Exception as e:
            print(f"back_to_lookup err: {e}")
        return

# ==================== FLASK ====================
app = Flask(__name__)

@app.route('/')
def home():
    return f"TraceX FREE Bot v{BOT_VERSION} - Running!"

def keep_alive():
    def run():
        port = int(os.getenv("PORT", "8080"))
        app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)
    t = threading.Thread(target=run, daemon=True)
    t.start()

# ==================== START ====================
if __name__ == "__main__":
    print("=" * 50)
    print(f"TraceX Lookup FREE v{BOT_VERSION}")
    print(f"Admin: @{ADMIN_USERNAME}")
    print("=" * 50)
    for key, svc in LOOKUP_SERVICES.items():
        print(f"   • {svc['emoji']} {svc['name']}")
    print(f"⏱️ Rate limit: {RATE_LIMIT_SECONDS}s")
    print("=" * 50)

    keep_alive()
    print("✅ Flask started")

    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        print(f"remove_webhook: {e}")

    print("✅ Bot running!")
    print("=" * 50)

    def signal_handler(signum, frame):
        print("\n🛑 Stopped")
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except (ValueError, AttributeError) as e:
        print(f"Signal handler setup skipped: {e}")

    while True:
        try:
            bot.infinity_polling(timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
