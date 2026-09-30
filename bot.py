"""
TraceX Lookup Bot - FREE VERSION
Version: 14.1.0
- Fixed inline callback buttons
- Clean callback handling
- Reply keyboard for main navigation
- Inline buttons for actions/support/channel verification
- 2 lookup services
"""

import os
import sys
import time
import re
import json
import threading
import signal

from flask import Flask


# ============================================================
# DEPENDENCY LOADER
# ============================================================

def _require_package(import_name, pip_name=None):
    try:
        return __import__(import_name)
    except ImportError:
        package = pip_name or import_name
        print(f"❌ Missing dependency: {package}")
        print(f"Install with: pip install {package}")
        raise


telebot = _require_package("telebot", "pyTelegramBotAPI")
requests = _require_package("requests", "requests")

from telebot.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ Missing BOT_TOKEN environment variable")
    sys.exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", "7850023357"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "gauravbeniwalx")

LOOKUP_API_BASE = (
    "https://gauravbeniwal.online/lookupportal/api/lookup.php"
)

WEBSITE_URL = "https://gauravbeniwal.online/lookupportal"

BOT_VERSION = "14.1.0"

RATE_LIMIT_SECONDS = 30
TELEGRAM_SAFE_LIMIT = 3900


# ============================================================
# REQUIRED CHANNELS
# ============================================================

REQUIRED_CHANNELS = [
    {
        "name": "Gaurav Beniwal",
        "id": "@Gaurav_beni_0001",
        "link": "https://t.me/Gaurav_beni_0001",
    },
    {
        "name": "Beniwal Mods",
        "id": "@beniwalmods",
        "link": "https://t.me/beniwalmods",
    },
    {
        "name": "Beniwalzon YT",
        "id": "@BeniwalzonYT",
        "link": "https://t.me/BeniwalzonYT",
    },
    {
        "name": "Private Community",
        "id": -1003004551707,
        "link": "https://t.me/+j7KaRgC8l14zODc1",
    },
]


# ============================================================
# LOOKUP SERVICES
# ============================================================

LOOKUP_SERVICES = {
    "number": {
        "name": "Number Info",
        "emoji": "📱",
        "query_type": "mobile",
    },
    "telegram": {
        "name": "Telegram to Number",
        "emoji": "💬",
        "query_type": "username",
    },
}


# ============================================================
# BOT INITIALIZATION
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode=None,
    threaded=True,
)


# ============================================================
# STATE
# ============================================================

user_states = {}
user_last_lookup = {}

active_sessions = set()
active_sessions_lock = threading.Lock()


# ============================================================
# TEXT HELPERS
# ============================================================

def escape_html(text):
    if text is None:
        return ""

    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def footer():
    return (
        f"\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🌐 {escape_html(WEBSITE_URL)}\n"
        f"👨‍💻 @{escape_html(ADMIN_USERNAME)}"
    )


def format_json_for_telegram(data):
    try:
        if isinstance(data, (dict, list)):
            output = json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
        else:
            output = str(data)

        output = escape_html(output)

        return f"<pre>{output}</pre>"

    except Exception as exc:
        print(f"[JSON] Format error: {exc}")
        return f"<pre>{escape_html(str(data))}</pre>"


# ============================================================
# KEYBOARDS
# ============================================================

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2,
    )

    keyboard.add(
        KeyboardButton("📱 NUMBER INFO"),
        KeyboardButton("💬 TG TO NUMBER"),
    )

    keyboard.add(
        KeyboardButton("📢 SUPPORT"),
    )

    return keyboard


def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=1,
    )

    keyboard.add(
        KeyboardButton("❌ CANCEL"),
    )

    return keyboard


def get_channel_join_markup():
    """
    Inline keyboard used for channel verification.
    """

    markup = InlineKeyboardMarkup(row_width=1)

    for channel in REQUIRED_CHANNELS:
        markup.add(
            InlineKeyboardButton(
                f"📢 {channel['name']}",
                url=channel["link"],
            )
        )

    markup.add(
        InlineKeyboardButton(
            "✅ I HAVE JOINED",
            callback_data="check_join",
        )
    )

    return markup


def get_result_markup():
    """
    Inline buttons shown after lookup.
    """

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "🔍 NEW SEARCH",
            callback_data="back_to_lookup",
        ),
        InlineKeyboardButton(
            "🏠 MENU",
            callback_data="main_menu",
        ),
    )

    return markup


def get_support_markup():
    markup = InlineKeyboardMarkup(row_width=1)

    markup.add(
        InlineKeyboardButton(
            "👨‍💻 CONTACT ADMIN",
            url=f"https://t.me/{ADMIN_USERNAME}",
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🌐 WEBSITE",
            url=WEBSITE_URL,
        )
    )

    return markup


# ============================================================
# SESSION HELPERS
# ============================================================

def is_active_session(user_id):
    with active_sessions_lock:
        return user_id in active_sessions


def add_active_session(user_id):
    with active_sessions_lock:
        active_sessions.add(user_id)


def remove_active_session(user_id):
    with active_sessions_lock:
        active_sessions.discard(user_id)


# ============================================================
# TEXT SPLITTER
# ============================================================

def split_long_text(text, limit=TELEGRAM_SAFE_LIMIT):
    text = str(text or "")

    if len(text) <= limit:
        return [text]

    pre_start = text.find("<pre>")
    pre_end = text.rfind("</pre>")

    if pre_start != -1 and pre_end != -1 and pre_start < pre_end:

        before = text[:pre_start]

        inner = text[
            pre_start + len("<pre>"):
            pre_end
        ]

        after = text[
            pre_end + len("</pre>"):
        ]

        chunk_budget = max(500, limit - 400)

        chunks = []
        current = ""
        first_chunk = True

        for line in inner.split("\n"):

            candidate = (
                f"{current}\n{line}"
                if current
                else line
            )

            if len(candidate) > chunk_budget and current:

                prefix = before if first_chunk else ""

                chunks.append(
                    f"{prefix}<pre>{current}</pre>"
                )

                first_chunk = False
                current = line

            else:
                current = candidate

        if current or first_chunk:

            prefix = before if first_chunk else ""

            chunks.append(
                f"{prefix}<pre>{current}</pre>"
            )

        if after and chunks:
            chunks[-1] += after

        return chunks or [text]

    chunks = []
    current = ""

    for line in text.splitlines(keepends=True):

        if len(current) + len(line) > limit and current:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [""]


# ============================================================
# TELEGRAM MESSAGE HELPERS
# ============================================================

def safe_edit_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
    parse_mode="HTML",
):
    try:

        return bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

    except Exception as exc:

        error = str(exc).lower()

        if "message is not modified" in error:
            return None

        print(
            f"[EDIT] Failed: {exc}"
        )

        try:

            plain = re.sub(
                r"<[^>]+>",
                "",
                str(text),
            )

            return bot.edit_message_text(
                plain,
                chat_id,
                message_id,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )

        except Exception as fallback_error:

            print(
                f"[EDIT] Fallback failed: "
                f"{fallback_error}"
            )

            return None


def send_or_edit_long_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
    parse_mode="HTML",
):
    chunks = split_long_text(text)

    sent_messages = []

    total = len(chunks)

    for index, chunk in enumerate(chunks):

        first = index == 0
        last = index == total - 1

        markup = (
            reply_markup
            if last
            else None
        )

        if total > 1:
            body = (
                f"<b>📄 Part "
                f"{index + 1}/{total}</b>\n"
                f"{chunk}"
            )
        else:
            body = chunk

        if len(body) > 4096:
            body = body[:4090] + "…"

        try:

            if first:

                result = bot.edit_message_text(
                    body,
                    chat_id,
                    message_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

            else:

                result = bot.send_message(
                    chat_id,
                    body,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

            sent_messages.append(result)

        except Exception as exc:

            print(
                f"[MESSAGE] Send/edit error: {exc}"
            )

            try:

                plain = re.sub(
                    r"<[^>]+>",
                    "",
                    body,
                )

                if first:

                    result = bot.edit_message_text(
                        plain,
                        chat_id,
                        message_id,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )

                else:

                    result = bot.send_message(
                        chat_id,
                        plain,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )

                sent_messages.append(result)

            except Exception as fallback_error:

                print(
                    f"[MESSAGE] Fallback failed: "
                    f"{fallback_error}"
                )

    return sent_messages


# ============================================================
# MOBILE VALIDATION
# ============================================================

def normalize_indian_mobile(value):
    raw = str(value or "").strip()

    digits = re.sub(
        r"\D",
        "",
        raw,
    )

    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if re.match(
        r"^[6-9]\d{9}$",
        digits,
    ):
        return digits

    return None


# ============================================================
# LOOKUP API
# ============================================================

def call_lookup_api(service, query):

    try:

        url = (
            f"{LOOKUP_API_BASE}"
            f"?service={service}"
            f"&spell={query}"
        )

        print(
            f"[LOOKUP] service={service} "
            f"query={query}"
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 16) "
                "TraceXBot/14.1.0"
            ),
            "Accept": "application/json",
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=(10, 25),
        )

        print(
            f"[LOOKUP] HTTP {response.status_code}"
        )

        if response.status_code != 200:

            return {
                "success": False,
                "error": (
                    f"HTTP {response.status_code}"
                ),
            }

        content = response.text

        if not content or len(content.strip()) < 5:

            return {
                "success": False,
                "error": "empty_response",
            }

        try:
            return response.json()

        except Exception:

            return {
                "success": True,
                "raw_response": content,
            }

    except requests.exceptions.Timeout:

        return {
            "success": False,
            "error": "timeout",
        }

    except requests.exceptions.ConnectionError:

        return {
            "success": False,
            "error": "connection_error",
        }

    except Exception as exc:

        return {
            "success": False,
            "error": f"exception_{exc}",
        }


# ============================================================
# CHANNEL VERIFICATION
# ============================================================

def is_channel_member(user_id, channel_id):

    # Admin bypass
    if str(user_id) == str(ADMIN_ID):
        return True

    try:

        member = bot.get_chat_member(
            channel_id,
            user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as exc:

        print(
            f"[CHANNEL] Check failed "
            f"{channel_id}: {exc}"
        )

        return False


def check_all_channels(user_id):

    if str(user_id) == str(ADMIN_ID):
        return True, []

    missing = []

    for channel in REQUIRED_CHANNELS:

        if not is_channel_member(
            user_id,
            channel["id"],
        ):
            missing.append(channel)

    return len(missing) == 0, missing


def send_join_required(
    chat_id,
    missing_channels=None,
):

    if missing_channels is None:

        joined, missing_channels = (
            check_all_channels(chat_id)
        )

        if joined:
            return True

    if missing_channels:

        channel_list = "\n".join(
            f"• {channel['name']}"
            for channel in missing_channels
        )

        message = (
            "🔒 <b>ACCESS REQUIRED</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Please join the required "
            "channels before using the bot.\n\n"
            f"{channel_list}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "After joining, tap "
            "<b>I HAVE JOINED</b>."
        )

        bot.send_message(
            chat_id,
            message,
            reply_markup=get_channel_join_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        return False

    return True


# ============================================================
# LOOKUP PROCESSOR
# ============================================================

def process_lookup(message):

    user_id = message.from_user.id
    query_input = str(
        message.text or ""
    ).strip()

    # Cancel
    if query_input in (
        "❌ CANCEL",
        "/cancel",
    ):

        user_states.pop(
            user_id,
            None,
        )

        remove_active_session(user_id)

        bot.reply_to(
            message,
            "✅ <b>Cancelled.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML",
        )

        return

    state = user_states.get(user_id)

    if not (
        isinstance(state, dict)
        and state.get("state")
        == "awaiting_lookup"
    ):
        return

    service_key = state.get("service")

    user_states.pop(
        user_id,
        None,
    )

    service = LOOKUP_SERVICES.get(
        service_key
    )

    if not service:

        bot.reply_to(
            message,
            "❌ <b>Invalid service.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Validate input
    # --------------------------------------------------------

    query_clean = query_input

    if service["query_type"] == "mobile":

        phone = normalize_indian_mobile(
            query_input
        )

        if not phone:

            user_states[user_id] = {
                "state": "awaiting_lookup",
                "service": service_key,
            }

            bot.reply_to(
                message,
                "❌ <b>Invalid mobile number.</b>\n\n"
                "Send a valid 10-digit Indian "
                "mobile number starting with "
                "6, 7, 8 or 9.\n\n"
                "<b>Example:</b> "
                "<code>9876543210</code>",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML",
            )

            return

        query_clean = phone

    elif service["query_type"] == "username":

        query_clean = (
            query_input
            .lstrip("@")
            .strip()
        )

        if not re.match(
            r"^[A-Za-z0-9_]{3,32}$",
            query_clean,
        ):

            user_states[user_id] = {
                "state": "awaiting_lookup",
                "service": service_key,
            }

            bot.reply_to(
                message,
                "❌ <b>Invalid Telegram username.</b>\n\n"
                "Use 3–32 characters containing "
                "letters, numbers or underscores.\n\n"
                "<b>Example:</b> "
                "<code>username</code>",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML",
            )

            return

    # --------------------------------------------------------
    # Rate limit
    # --------------------------------------------------------

    now = time.time()

    last_lookup = user_last_lookup.get(
        user_id,
        0,
    )

    if (
        now - last_lookup
        < RATE_LIMIT_SECONDS
        and str(user_id) != str(ADMIN_ID)
    ):

        wait_time = int(
            RATE_LIMIT_SECONDS
            - (now - last_lookup)
        )

        bot.reply_to(
            message,
            f"⏳ <b>Please wait {wait_time}s.</b>\n\n"
            "Limit: 1 lookup every 30 seconds.",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Prevent duplicate active searches
    # --------------------------------------------------------

    if is_active_session(user_id):

        bot.reply_to(
            message,
            "⏳ <b>Search already in progress.</b>\n\n"
            "Please wait for the current request "
            "to finish.",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Start lookup
    # --------------------------------------------------------

    add_active_session(user_id)

    user_last_lookup[user_id] = now

    loading_msg = None

    try:

        loading_msg = bot.reply_to(
            message,
            f"{service['emoji']} "
            f"<b>Searching...</b>\n\n"
            "<i>Please wait.</i>",
            parse_mode="HTML",
        )

        time.sleep(0.4)

        result = call_lookup_api(
            service_key,
            query_clean,
        )

        # ----------------------------------------------------
        # API error
        # ----------------------------------------------------

        if (
            not result
            or result.get("error")
        ):

            output = (
                f"<b>{service['emoji']} "
                f"{service['name'].upper()}</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🔎 Query: "
                f"<code>{escape_html(query_clean)}</code>\n\n"
                "<b>❌ Request failed.</b>\n\n"
                f"{format_json_for_telegram(result or {'error': 'No response'})}"
            )

            safe_edit_message(
                message.chat.id,
                loading_msg.message_id,
                output,
                parse_mode="HTML",
            )

            return

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        json_output = format_json_for_telegram(
            result
        )

        output = (
            f"<b>{service['emoji']} "
            f"{service['name'].upper()}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🔎 Query: "
            f"<code>{escape_html(query_clean)}</code>\n\n"
            "📄 <b>Result</b>\n"
            f"{json_output}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "✅ <b>Lookup complete.</b>"
        )

        output += footer()

        send_or_edit_long_message(
            message.chat.id,
            loading_msg.message_id,
            output,
            reply_markup=get_result_markup(),
            parse_mode="HTML",
        )

    except Exception as exc:

        print(
            f"[LOOKUP] Processing error: {exc}"
        )

        try:

            error_message = (
                "❌ <b>Search failed.</b>\n\n"
                "Please try again later."
            )

            if loading_msg:

                safe_edit_message(
                    message.chat.id,
                    loading_msg.message_id,
                    error_message,
                    parse_mode="HTML",
                )

            else:

                bot.reply_to(
                    message,
                    error_message,
                    parse_mode="HTML",
                )

        except Exception as notify_error:

            print(
                f"[LOOKUP] Notify error: "
                f"{notify_error}"
            )

    finally:

        remove_active_session(user_id)


# ============================================================
# /START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    user_id = message.from_user.id

    first_name = (
        message.from_user.first_name
        or "User"
    )

    joined, missing = check_all_channels(
        user_id
    )

    if not joined:

        send_join_required(
            message.chat.id,
            missing,
        )

        return

    welcome = (
        "🚀 <b>TRACEX LOOKUP</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Welcome, <b>{escape_html(first_name)}</b>.\n\n"
        "✅ Access verified\n"
        "🎁 Free service\n"
        "⏱️ 1 lookup / 30 seconds\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Available Services</b>\n\n"
        "📱 <b>Number Info</b>\n"
        "💬 <b>Telegram to Number</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Select a service below."
    )

    bot.send_message(
        message.chat.id,
        welcome,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ============================================================
# /CANCEL
# ============================================================

@bot.message_handler(
    commands=["cancel"]
)
def cancel_command(message):

    user_id = message.from_user.id

    user_states.pop(
        user_id,
        None,
    )

    remove_active_session(user_id)

    bot.reply_to(
        message,
        "✅ <b>Cancelled.</b>",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# TEXT HANDLER
# ============================================================

@bot.message_handler(
    content_types=["text"]
)
def text_handler(message):

    user_id = message.from_user.id

    text = (
        message.text or ""
    ).strip()

    # --------------------------------------------------------
    # Active lookup input
    # --------------------------------------------------------

    state = user_states.get(user_id)

    if (
        isinstance(state, dict)
        and state.get("state")
        == "awaiting_lookup"
    ):

        joined, missing = check_all_channels(
            user_id
        )

        if not joined:

            user_states.pop(
                user_id,
                None,
            )

            send_join_required(
                message.chat.id,
                missing,
            )

            return

        process_lookup(message)

        return

    # --------------------------------------------------------
    # Channel access check
    # --------------------------------------------------------

    joined, missing = check_all_channels(
        user_id
    )

    if not joined:

        send_join_required(
            message.chat.id,
            missing,
        )

        return

    # --------------------------------------------------------
    # Number Info
    # --------------------------------------------------------

    if text == "📱 NUMBER INFO":

        user_states[user_id] = {
            "state": "awaiting_lookup",
            "service": "number",
        }

        bot.reply_to(
            message,
            "📱 <b>NUMBER INFO</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Send a valid 10-digit mobile number.\n\n"
            "<b>Example:</b> "
            "<code>9876543210</code>\n\n"
            "⏱️ Limit: 1 lookup / 30 seconds.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Telegram to Number
    # --------------------------------------------------------

    if text == "💬 TG TO NUMBER":

        user_states[user_id] = {
            "state": "awaiting_lookup",
            "service": "telegram",
        }

        bot.reply_to(
            message,
            "💬 <b>TELEGRAM TO NUMBER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Send a Telegram username.\n\n"
            "<b>Example:</b> "
            "<code>username</code>\n\n"
            "⏱️ Limit: 1 lookup / 30 seconds.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Support
    # --------------------------------------------------------

    if text == "📢 SUPPORT":

        support_message = (
            "📢 <b>SUPPORT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👨‍💻 @{escape_html(ADMIN_USERNAME)}\n"
            f"🌐 {escape_html(WEBSITE_URL)}\n\n"
            "For assistance, contact the administrator."
        )

        bot.reply_to(
            message,
            support_message,
            reply_markup=get_support_markup(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        return

    # --------------------------------------------------------
    # Cancel
    # --------------------------------------------------------

    if text == "❌ CANCEL":

        user_states.pop(
            user_id,
            None,
        )

        remove_active_session(user_id)

        bot.reply_to(
            message,
            "✅ <b>Cancelled.</b>",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # Unknown text
    # --------------------------------------------------------

    bot.reply_to(
        message,
        "❌ <b>Unknown command.</b>\n\n"
        "Please use the menu buttons below.",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# INLINE CALLBACK HANDLER
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callback_handler(call):

    user_id = call.from_user.id
    data = call.data or ""

    print(
        f"[CALLBACK] "
        f"user={user_id} "
        f"data={data}"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # Answer the callback ONLY ONCE.
    # --------------------------------------------------------

    try:

        bot.answer_callback_query(
            call.id
        )

    except Exception as exc:

        print(
            f"[CALLBACK] Answer error: {exc}"
        )

    # --------------------------------------------------------
    # Invalid callback message
    # --------------------------------------------------------

    if not call.message:

        return

    chat_id = call.message.chat.id
    message_id = call.message.message_id

    # ========================================================
    # CHECK JOIN
    # ========================================================

    if data == "check_join":

        joined, missing = check_all_channels(
            user_id
        )

        if not joined:

            missing_names = ", ".join(
                channel["name"]
                for channel in missing
            )

            try:

                bot.answer_callback_query(
                    call.id,
                    f"Missing: {missing_names}",
                    show_alert=True,
                )

            except Exception as exc:

                print(
                    f"[CALLBACK] Alert error: {exc}"
                )

            return

        # Access verified

        verified_text = (
            "✅ <b>ACCESS VERIFIED</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Your channel membership has been "
            "verified successfully.\n\n"
            "Use the menu below to continue."
        )

        safe_edit_message(
            chat_id,
            message_id,
            verified_text,
            parse_mode="HTML",
        )

        try:

            bot.send_message(
                chat_id,
                "🏠 <b>Main Menu</b>\n\n"
                "Select a service below.",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML",
            )

        except Exception as exc:

            print(
                f"[CALLBACK] Menu send error: {exc}"
            )

        return

    # ========================================================
    # MAIN MENU
    # ========================================================

    if data == "main_menu":

        # Clear lookup state
        user_states.pop(
            user_id,
            None,
        )

        remove_active_session(user_id)

        menu_text = (
            "🏠 <b>MAIN MENU</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Select a service below."
        )

        safe_edit_message(
            chat_id,
            message_id,
            menu_text,
            parse_mode="HTML",
        )

        try:

            bot.send_message(
                chat_id,
                "👇 Choose an option:",
                reply_markup=get_main_keyboard(),
            )

        except Exception as exc:

            print(
                f"[CALLBACK] Main menu error: {exc}"
            )

        return

    # ========================================================
    # NEW SEARCH
    # ========================================================

    if data == "back_to_lookup":

        user_states.pop(
            user_id,
            None,
        )

        remove_active_session(user_id)

        safe_edit_message(
            chat_id,
            message_id,
            (
                "🔍 <b>NEW SEARCH</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "Choose a service from the menu below."
            ),
            parse_mode="HTML",
        )

        try:

            bot.send_message(
                chat_id,
                "👇 Select a service:",
                reply_markup=get_main_keyboard(),
            )

        except Exception as exc:

            print(
                f"[CALLBACK] New search error: {exc}"
            )

        return

    # ========================================================
    # UNKNOWN CALLBACK
    # ========================================================

    print(
        f"[CALLBACK] Unknown data: {data}"
    )

    try:

        bot.answer_callback_query(
            call.id,
            "This button is no longer available.",
            show_alert=True,
        )

    except Exception:
        pass


# ============================================================
# FLASK KEEP-ALIVE
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return (
        f"TraceX FREE Bot "
        f"v{BOT_VERSION} - Running!"
    )


def keep_alive():

    def run():

        port = int(
            os.getenv(
                "PORT",
                "8080",
            )
        )

        app.run(
            host="0.0.0.0",
            port=port,
            use_reloader=False,
            threaded=True,
        )

    thread = threading.Thread(
        target=run,
        daemon=True,
    )

    thread.start()


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    print("=" * 55)
    print(
        f"TraceX Lookup FREE v{BOT_VERSION}"
    )
    print(
        f"Admin: @{ADMIN_USERNAME}"
    )
    print("=" * 55)

    for key, service in LOOKUP_SERVICES.items():

        print(
            f"   • {service['emoji']} "
            f"{service['name']}"
        )

    print(
        f"⏱️ Rate limit: "
        f"{RATE_LIMIT_SECONDS}s"
    )

    print("=" * 55)

    # Start Flask
    keep_alive()

    print("✅ Flask started")

    # Remove any previous webhook
    try:

        bot.remove_webhook()

        time.sleep(1)

        print("✅ Webhook removed")

    except Exception as exc:

        print(
            f"⚠️ Webhook cleanup: {exc}"
        )

    print("✅ Bot polling started")
    print("=" * 55)

    # --------------------------------------------------------
    # Graceful shutdown
    # --------------------------------------------------------

    def signal_handler(
        signum,
        frame,
    ):

        print("\n🛑 Bot stopped")

        sys.exit(0)


    try:

        signal.signal(
            signal.SIGINT,
            signal_handler,
        )

        signal.signal(
            signal.SIGTERM,
            signal_handler,
        )

    except (
        ValueError,
        AttributeError,
    ) as exc:

        print(
            f"⚠️ Signal handler skipped: {exc}"
        )

    # --------------------------------------------------------
    # Polling loop
    # --------------------------------------------------------

    while True:

        try:

            bot.infinity_polling(
                timeout=30,
                skip_pending=True,
                allowed_updates=[
                    "message",
                    "callback_query",
                ],
            )

        except Exception as exc:

            print(
                f"⚠️ Polling error: {exc}"
            )

            time.sleep(5)
