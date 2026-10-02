"""
TraceX Lookup Bot - Premium Telecom Lookup Bot
Version: 13.0.1

CHANGES FROM v13.0.0
--------------------
1.  FIXED: API call now uses 'query' parameter instead of 'spell' to match the backend.
2.  FIXED: Added 'api_key' to the lookup API request. It's now configured via 'LOOKUP_API_KEY'.
3.  IMPROVED: Result formatting for 'number' and 'telegram' lookups now correctly parses the 'data' array.
4.  IMPROVED: 'has_valid_results' function is more robust and correctly identifies successful lookups.
"""

import os
import sys
import re
import time
import json
import uuid
import signal
import threading
from datetime import datetime, timedelta, timezone

# ============================================================
# DEPENDENCIES
# ============================================================

def require_package(import_name, pip_name=None):
    try:
        return __import__(import_name)
    except ImportError:
        package = pip_name or import_name
        print(f"Missing dependency: {package}")
        print(f"Install with: pip install {package}")
        raise


telebot = require_package("telebot", "pyTelegramBotAPI")
requests = require_package("requests")
from flask import Flask

from telebot.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ============================================================
# CONFIG
# ============================================================

def env(name, required=True, default=None):
    value = os.getenv(name)

    if required and not value:
        if default is not None:
            return default

        print(f"Missing required environment variable: {name}")
        sys.exit(1)

    return value if value else default


BOT_TOKEN = env("BOT_TOKEN")

ADMIN_ID = int(env("ADMIN_ID", default="7850023357"))
ADMIN_CHANNEL_ID = int(
    env("ADMIN_CHANNEL_ID", default="-1003743686626")
)
ADMIN_USERNAME = env(
    "ADMIN_USERNAME",
    default="gaurav_beniwal_0001"
)

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = env(
    "SUPABASE_SERVICE_ROLE_KEY",
    required=False
)

# ============================================================
# AUTHORIZED LOOKUP BACKEND
# ============================================================

AUTHORIZED_LOOKUP_API_BASE = env(
    "AUTHORIZED_LOOKUP_API_BASE",
    required=False,
    default=""
)

LOOKUP_API_KEY = env(
    "LOOKUP_API_KEY",
    required=False,
    default="" # IMPORTANT: Add your API key to environment variables
)

# ============================================================
# UTR
# ============================================================

UTR_VERIFY_API = env(
    "UTR_VERIFY_API",
    required=False,
    default="https://upipaymentgatewayhdfc.onrender.com/verify-utr"
)

# ============================================================
# GENERAL SETTINGS
# ============================================================

WEBSITE_URL = env(
    "WEBSITE_URL",
    required=False,
    default="https://gauravbeniwal.online/lookupportal"
)

PAYMENT_QR_IMAGE = env(
    "PAYMENT_QR_IMAGE",
    required=False,
    default="payment_qr.png"
)

BOT_VERSION = "13.0.1"

# IMPORTANT:
# This is lifetime free usage, NOT daily.
FREE_LOOKUPS = 3

TELEGRAM_SAFE_LIMIT = 3900
TELEGRAM_MESSAGE_LIMIT = 4096

COOLDOWN_SECONDS = 3

REQUEST_TIMEOUT_CONNECT = 10
REQUEST_TIMEOUT_READ = 25

IST = timezone(timedelta(hours=5, minutes=30))

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
# SERVICES
# ============================================================

LOOKUP_SERVICES = {
    "number": {
        "name": "Number Info",
        "emoji": "📱",
        "cost": 3,
        "query_type": "mobile",
        "placeholder": "9876543210",
        "api_service_name": "numberinfo", # Added to map to API service name
    },

    "telegram": {
        "name": "TG to Number",
        "emoji": "💬",
        "cost": 10,
        "query_type": "username",
        "placeholder": "username",
        "api_service_name": "tg2num", # Added to map to API service name
    },
}

# ============================================================
# PAYMENT PLANS
# ============================================================

PLAN_CONFIG = {
    "credits_50": {
        "amount": 50,
        "credits": 50,
        "label": "50 Credits - ₹50",
    },

    "credits_100": {
        "amount": 100,
        "credits": 100,
        "label": "100 Credits - ₹100",
    },

    "credits_200": {
        "amount": 200,
        "credits": 200,
        "label": "200 Credits - ₹200",
    },

    "credits_500": {
        "amount": 500,
        "credits": 500,
        "label": "500 Credits - ₹500",
    },

    "unlimited_999": {
        "amount": 999,
        "credits": 0,
        "unlimited_minutes": 43200,
        "label": "Unlimited 30 Days - ₹999",
    },
}

# ============================================================
# TELEBOT
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode=None,
    threaded=True,
)

# ============================================================
# SUPABASE REST CLIENT
# ============================================================

class SupabaseResult:
    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count


class SupabaseTableQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.method = "GET"
        self.payload = None
        self.params = {}
        self.headers = {}

    def select(self, columns="*", count=None):
        self.method = "GET"
        self.params["select"] = columns or "*"

        if count == "exact":
            self.headers["Prefer"] = "count=exact"

        return self

    def insert(self, payload):
        self.method = "POST"
        self.payload = payload
        self.headers["Prefer"] = "return=representation"
        return self

    def update(self, payload):
        self.method = "PATCH"
        self.payload = payload
        self.headers["Prefer"] = "return=representation"
        return self

    def delete(self):
        self.method = "DELETE"
        self.headers["Prefer"] = "return=representation"
        return self

    def eq(self, column, value):
        self.params[str(column)] = f"eq.{value}"
        return self

    def neq(self, column, value):
        self.params[str(column)] = f"neq.{value}"
        return self

    def limit(self, n):
        self.params["limit"] = str(int(n))
        return self

    def range(self, start, end):
        self.params["offset"] = str(int(start))
        self.params["limit"] = str(
            int(end) - int(start) + 1
        )
        return self

    def order(self, column, desc=False):
        direction = "desc" if desc else "asc"
        self.params["order"] = f"{column}.{direction}"
        return self

    def execute(self):
        if not self.client.url or not self.client.key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY are required"
            )

        url = (
            f"{self.client.url}"
            f"/rest/v1/{self.table}"
        )

        headers = dict(self.client.headers)
        headers.update(self.headers)

        response = requests.request(
            self.method,
            url,
            params=self.params,
            json=self.payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase REST error "
                f"{response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json() if response.text else []
        except Exception:
            data = []

        count = None

        content_range = (
            response.headers.get("content-range")
            or response.headers.get("Content-Range")
        )

        if content_range and "/" in content_range:
            try:
                total = content_range.split("/")[-1]
                count = (
                    None
                    if total == "*"
                    else int(total)
                )
            except Exception:
                count = None

        if count is None and isinstance(data, list):
            count = len(data)

        return SupabaseResult(
            data=data,
            count=count
        )


class SupabaseLiteClient:
    def __init__(self, url, key):
        self.url = str(url or "").rstrip("/")
        self.key = str(key or "")

        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def table(self, name):
        return SupabaseTableQuery(self, name)


SUPABASE_KEY = (
    SUPABASE_SERVICE_ROLE_KEY
    or SUPABASE_ANON_KEY
)

supabase = SupabaseLiteClient(
    SUPABASE_URL,
    SUPABASE_KEY
)

# ============================================================
# RUNTIME STATE
# ============================================================

user_states = {}
user_cooldown = {}
active_sessions = set()

state_lock = threading.RLock()
credit_lock = threading.RLock()
session_lock = threading.RLock()

# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def now_ist():
    return datetime.now(IST)


def iso_now():
    return now_utc().isoformat()


def escape_html(value):
    if value is None:
        return ""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def footer():
    return (
        "\n\n━━━━━━━━━━━━━━━━\n"
        f"🌐 {WEBSITE_URL}\n"
        f"👨‍💻 @{ADMIN_USERNAME}"
    )


def is_admin(user_id):
    return str(user_id) == str(ADMIN_ID)


# ============================================================
# KEYBOARDS
# ============================================================

def get_main_keyboard_for_user(user_id):
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    keyboard.add(
        KeyboardButton("📱 NUMBER INFO"),
        KeyboardButton("💬 TG TO NUMBER"),
    )

    keyboard.add(
        KeyboardButton("💎 MY CREDITS"),
        KeyboardButton("🛒 BUY CREDITS"),
    )

    keyboard.add(
        KeyboardButton("📢 SUPPORT"),
        KeyboardButton("🚀 UNLIMITED"),
    )

    if is_admin(user_id):
        keyboard.add(
            KeyboardButton("🛠 ADMIN")
        )

    return keyboard


def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=1
    )

    keyboard.add(
        KeyboardButton("❌ CANCEL")
    )

    return keyboard


def get_channel_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)

    for channel in REQUIRED_CHANNELS:
        markup.add(
            InlineKeyboardButton(
                f"📢 {channel['name']}",
                url=channel["link"]
            )
        )

    markup.add(
        InlineKeyboardButton(
            "✅ I HAVE JOINED",
            callback_data="check_join"
        )
    )

    return markup


def cancel_button():
    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "❌ CANCEL",
            callback_data="cancel"
        )
    )

    return markup


def lookup_result_markup():
    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "🔍 NEW SEARCH",
            callback_data="back_to_lookup"
        ),
        InlineKeyboardButton(
            "🏠 MENU",
            callback_data="main_menu"
        ),
    )

    return markup


def credit_packs_markup():
    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "₹50",
            callback_data="plan_credits_50"
        ),
        InlineKeyboardButton(
            "₹100",
            callback_data="plan_credits_100"
        ),
    )

    markup.add(
        InlineKeyboardButton(
            "₹200",
            callback_data="plan_credits_200"
        ),
        InlineKeyboardButton(
            "₹500",
            callback_data="plan_credits_500"
        ),
    )

    markup.add(
        InlineKeyboardButton(
            "🚀 UNLIMITED 30D - ₹999",
            callback_data="plan_unlimited_999"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 BACK",
            callback_data="main_menu"
        )
    )

    return markup


# ============================================================
# MESSAGE HELPERS
# ============================================================

def format_json_for_telegram(data):
    try:
        if isinstance(data, (dict, list)):
            text = json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                default=str
            )
        else:
            text = str(data)

        return (
            "<pre>"
            + escape_html(text)
            + "</pre>"
        )

    except Exception:
        return (
            "<pre>"
            + escape_html(str(data))
            + "</pre>"
        )


def split_long_text(text, limit=TELEGRAM_SAFE_LIMIT):
    text = str(text or "")

    if len(text) <= limit:
        return [text]

    pre_start = text.find("<pre>")
    pre_end = text.rfind("</pre>")

    if (
        pre_start != -1
        and pre_end != -1
        and pre_start < pre_end
    ):
        before = text[:pre_start]

        inner = text[
            pre_start + len("<pre>"):
            pre_end
        ]

        after = text[
            pre_end + len("</pre>"):
        ]

        budget = max(500, limit - 400)

        chunks = []
        current = ""
        first = True

        for line in inner.split("\n"):
            candidate = (
                current + "\n" + line
                if current
                else line
            )

            if len(candidate) > budget and current:
                prefix = before if first else ""

                chunks.append(
                    f"{prefix}<pre>{current}</pre>"
                )

                first = False
                current = line
            else:
                current = candidate

        if current or first:
            prefix = before if first else ""

            chunks.append(
                f"{prefix}<pre>{current}</pre>"
            )

        if after and chunks:
            chunks[-1] += after

        return chunks or [text]

    chunks = []
    current = ""

    for line in text.splitlines(keepends=True):
        if (
            len(current) + len(line) > limit
            and current
        ):
            chunks.append(current.rstrip())
            current = line
        else:
            current += line

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [""]


def safe_edit_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
    parse_mode="HTML"
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

    except Exception as error:
        if "message is not modified" in str(error).lower():
            return None

        try:
            plain = re.sub(
                r"<[^>]+>",
                "",
                str(text)
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
                "safe_edit_message:",
                error,
                fallback_error
            )

            return None


def send_or_edit_long_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
    parse_mode="HTML"
):
    chunks = split_long_text(text)

    total = len(chunks)

    for index, chunk in enumerate(chunks):
        first = index == 0
        last = index == total - 1

        markup = (
            reply_markup
            if last
            else None
        )

        body = chunk

        if total > 1:
            body = (
                f"<b>📄 Part "
                f"{index + 1}/{total}</b>\n"
                f"{chunk}"
            )

        if len(body) > TELEGRAM_MESSAGE_LIMIT:
            body = (
                body[:4090]
                + "…"
            )

        try:
            if first:
                bot.edit_message_text(
                    body,
                    chat_id,
                    message_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            else:
                bot.send_message(
                    chat_id,
                    body,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

        except Exception as error:
            print(
                "Long message error:",
                error
            )

            try:
                plain = re.sub(
                    r"<[^>]+>",
                    "",
                    body
                )

                if first:
                    bot.edit_message_text(
                        plain,
                        chat_id,
                        message_id,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )
                else:
                    bot.send_message(
                        chat_id,
                        plain,
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )

            except Exception as fallback:
                print(
                    "Long message fallback:",
                    fallback
                )


# ============================================================
# SESSION CONTROL
# ============================================================

def is_active_session(user_id):
    with session_lock:
        return user_id in active_sessions


def add_active_session(user_id):
    with session_lock:
        active_sessions.add(user_id)


def remove_active_session(user_id):
    with session_lock:
        active_sessions.discard(user_id)


# ============================================================
# USER DATABASE
# ============================================================

def get_user(user_id):
    """
    Compatible with existing telegram_users table.
    """

    try:
        result = (
            supabase
            .table("telegram_users")
            .select("*")
            .eq("telegram_user_id", user_id)
            .limit(1)
            .execute()
        )

        if result.data:
            user = result.data[0]

            try:
                (
                    supabase
                    .table("telegram_users")
                    .update({
                        "last_seen": iso_now()
                    })
                    .eq(
                        "telegram_user_id",
                        user_id
                    )
                    .execute()
                )
            except Exception as update_error:
                print(
                    "last_seen update:",
                    update_error
                )

            return user

        # New user.
        new_user = {
            "telegram_user_id": user_id,
            "credits": 0,
            "total_searches": 0,
            "daily_free_used": 0,
            "daily_reset_date": now_ist().strftime(
                "%Y-%m-%d"
            ),
            "first_seen": iso_now(),
            "last_seen": iso_now(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "is_banned": False,
        }

        created = (
            supabase
            .table("telegram_users")
            .insert(new_user)
            .execute()
        )

        if created.data:
            return created.data[0]

        return None

    except Exception as error:
        print(
            "get_user error:",
            error
        )
        return None


# ============================================================
# FREE LOOKUP SYSTEM
# ============================================================

def get_free_used(user):
    if not user:
        return 0

    try:
        used = int(
            user.get(
                "daily_free_used",
                0
            ) or 0
        )
    except Exception:
        used = 0

    return max(
        0,
        min(
            FREE_LOOKUPS,
            used
        )
    )


def get_free_remaining(user):
    """
    Lifetime free quota.
    NO DAILY RESET.
    """

    used = get_free_used(user)

    return max(
        0,
        FREE_LOOKUPS - used
    )


def consume_free_lookup(user_id):
    """
    Consume one lifetime free lookup.
    """

    with credit_lock:
        try:
            user = get_user(user_id)

            if not user:
                return False

            used = get_free_used(user)

            if used >= FREE_LOOKUPS:
                return False

            new_used = used + 1

            result = (
                supabase
                .table("telegram_users")
                .update({
                    "daily_free_used": new_used,
                    "updated_at": iso_now(),
                })
                .eq(
                    "telegram_user_id",
                    user_id
                )
                .execute()
            )

            return bool(result.data)

        except Exception as error:
            print(
                "consume_free_lookup:",
                error
            )
            return False


# ============================================================
# CREDITS
# ============================================================

def get_credits(user_id):
    user = get_user(user_id)

    if not user:
        return 0

    try:
        return max(
            0,
            int(user.get("credits", 0) or 0)
        )
    except Exception:
        return 0


def add_credits(user_id, amount):
    if amount <= 0:
        return 0

    with credit_lock:
        try:
            user = get_user(user_id)

            if not user:
                return 0

            current = int(
                user.get("credits", 0) or 0
            )

            new_total = current + amount

            result = (
                supabase
                .table("telegram_users")
                .update({
                    "credits": new_total,
                    "updated_at": iso_now(),
                })
                .eq(
                    "telegram_user_id",
                    user_id
                )
                .execute()
            )

            if result.data:
                return int(
                    result.data[0].get(
                        "credits",
                        new_total
                    )
                )

            return new_total

        except Exception as error:
            print(
                "add_credits:",
                error
            )
            return 0


def deduct_credits(user_id, amount):
    """
    Deduct paid credits only.
    Unlimited users do not consume credits.
    """

    if amount <= 0:
        return False

    with credit_lock:
        try:
            user = get_user(user_id)

            if not user:
                return False

            unlimited, _ = get_active_unlimited(
                user
            )

            if unlimited:
                return True

            current = int(
                user.get("credits", 0) or 0
            )

            if current < amount:
                return False

            new_total = current - amount

            result = (
                supabase
                .table("telegram_users")
                .update({
                    "credits": new_total,
                    "updated_at": iso_now(),
                })
                .eq(
                    "telegram_user_id",
                    user_id
                )
                .execute()
            )

            return bool(result.data)

        except Exception as error:
            print(
                "deduct_credits:",
                error
            )
            return False


# ============================================================
# SEARCH COUNTER
# ============================================================

def increment_total_searches(user_id):
    try:
        user = get_user(user_id)

        if not user:
            return False

        current = int(
            user.get(
                "total_searches",
                0
            ) or 0
        )

        (
            supabase
            .table("telegram_users")
            .update({
                "total_searches": current + 1,
                "updated_at": iso_now(),
            })
            .eq(
                "telegram_user_id",
                user_id
            )
            .execute()
        )

        return True

    except Exception as error:
        print(
            "increment_total_searches:",
            error
        )
        return False


# ============================================================
# UNLIMITED
# ============================================================

def get_active_unlimited(user):
    if not user:
        return False, None

    raw = user.get(
        "unlimited_expiry"
    )

    if not raw:
        return False, None

    try:
        expiry = datetime.fromisoformat(
            str(raw).replace(
                "Z",
                "+00:00"
            )
        )

        if expiry.tzinfo is None:
            expiry = expiry.replace(
                tzinfo=timezone.utc
            )

        if expiry > now_utc():
            return True, expiry

    except Exception as error:
        print(
            "unlimited expiry:",
            error
        )

    return False, None


# ============================================================
# BAN
# ============================================================

def ban_user(user_id):
    try:
        (
            supabase
            .table("telegram_users")
            .update({
                "is_banned": True,
                "updated_at": iso_now(),
            })
            .eq(
                "telegram_user_id",
                user_id
            )
            .execute()
        )

        return True

    except Exception as error:
        print(
            "ban_user:",
            error
        )
        return False


def unban_user(user_id):
    try:
        (
            supabase
            .table("telegram_users")
            .update({
                "is_banned": False,
                "updated_at": iso_now(),
            })
            .eq(
                "telegram_user_id",
                user_id
            )
            .execute()
        )

        return True

    except Exception as error:
        print(
            "unban_user:",
            error
        )
        return False


# ============================================================
# PHONE VALIDATION
# ============================================================

def normalize_indian_mobile(value):
    raw = str(value or "").strip()

    digits = re.sub(
        r"\D",
        "",
        raw
    )

    if (
        digits.startswith("91")
        and len(digits) == 12
    ):
        digits = digits[2:]

    if re.fullmatch(
        r"[6-9]\d{9}",
        digits
    ):
        return digits

    return None


# ============================================================
# TELEGRAM USERNAME VALIDATION
# ============================================================

def normalize_username(value):
    username = str(
        value or ""
    ).strip()

    username = username.lstrip("@")

    if not re.fullmatch(
        r"[A-Za-z0-9_]{5,32}",
        username
    ):
        return None

    return username


# ============================================================
# CHANNEL CHECK
# ============================================================

def is_channel_member(user_id, channel_id):
    if is_admin(user_id):
        return True

    try:
        member = bot.get_chat_member(
            channel_id,
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception as error:
        print(
            "Channel check:",
            channel_id,
            error
        )

        return False


def check_all_channels(user_id):
    if is_admin(user_id):
        return True, []

    missing = []

    for channel in REQUIRED_CHANNELS:
        if not is_channel_member(
            user_id,
            channel["id"]
        ):
            missing.append(channel)

    return (
        len(missing) == 0,
        missing
    )


def send_join_required(
    chat_id,
    missing_channels=None
):
    if missing_channels is None:
        joined, missing_channels = (
            check_all_channels(chat_id)
        )

        if joined:
            return True

    if not missing_channels:
        return True

    names = "\n".join(
        f"• {c['name']}"
        for c in missing_channels
    )

    message = (
        "🔒 <b>Join Required</b>\n\n"
        "Join these channels to continue:\n\n"
        f"{escape_html(names)}\n\n"
        "After joining, tap "
        "✅ I HAVE JOINED."
    )

    bot.send_message(
        chat_id,
        message,
        reply_markup=get_channel_join_markup(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    return False


# ============================================================
# LOOKUP API
# ============================================================

def call_lookup_api(service_key, query):
    """
    Calls ONLY the configured authorized backend.
    """

    if not AUTHORIZED_LOOKUP_API_BASE:
        return {
            "success": False,
            "error": "lookup_backend_not_configured",
        }

    service = LOOKUP_SERVICES.get(service_key)
    if not service:
        return {"success": False, "error": "invalid_service_key"}

    try:
        # FIX: Use the correct API service name and query parameter
        params = {
            "api_key": LOOKUP_API_KEY,
            "service": service.get("api_service_name"),
            "query": query,
        }

        headers = {
            "User-Agent": (
                f"TraceXBot/{BOT_VERSION}"
            ),
            "Accept": "application/json",
        }

        response = requests.get(
            AUTHORIZED_LOOKUP_API_BASE,
            params=params,
            headers=headers,
            timeout=(
                REQUEST_TIMEOUT_CONNECT,
                REQUEST_TIMEOUT_READ,
            ),
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": (
                    f"HTTP {response.status_code}"
                ),
            }

        if not response.text.strip():
            return {
                "success": False,
                "error": "empty_response",
            }

        try:
            return response.json()

        except ValueError:
            return {
                "success": False,
                "error": "invalid_json",
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

    except Exception as error:
        return {
            "success": False,
            "error": str(error)[:300],
        }


def has_valid_results(result):
    if not isinstance(result, dict):
        return False

    if result.get("error"):
        return False

    # Check for the explicit success flag and data array from the API
    if result.get("success") is True:
        data = result.get("data")
        if isinstance(data, list) and len(data) > 0:
            return True

    # Fallback for other potential formats
    data = result.get("data")
    if isinstance(data, list) and data:
        return True
    if isinstance(data, dict) and data:
        return True

    return False


# ============================================================
# PAYMENT CLAIM
# ============================================================

def create_payment_claim(
    plan_id,
    telegram_user_id,
    telegram_username
):
    try:
        plan = PLAN_CONFIG.get(plan_id)

        if not plan:
            return None

        tx_code = (
            "TX"
            + uuid.uuid4()
            .hex[:12]
            .upper()
        )

        now = iso_now()

        payload = {
            "payment_id": tx_code,
            "telegram_user_id": str(
                telegram_user_id
            ),
            "telegram_username": str(
                telegram_username
                or "no_username"
            ),
            "plan_id": plan_id,
            "amount": plan["amount"],
            "credits": plan.get(
                "credits",
                0
            ),
            "payment_for": (
                "unlimited"
                if "unlimited" in plan_id
                else "credits"
            ),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }

        result = (
            supabase
            .table("payment_claims")
            .insert(payload)
            .execute()
        )

        if result.data:
            return tx_code

        return None

    except Exception as error:
        print(
            "create_payment_claim:",
            error
        )
        return None


# ============================================================
# UTR VERIFICATION
# ============================================================

def verify_utr(utr, expected_amount):
    try:
        response = requests.get(
            UTR_VERIFY_API,
            params={
                "utr": utr
            },
            timeout=30,
        )

        if response.status_code != 200:
            return (
                False,
                f"Verification API HTTP "
                f"{response.status_code}",
                None,
            )

        try:
            data = response.json()

        except ValueError:
            return (
                False,
                "Verification API returned invalid JSON.",
                None,
            )

        status = str(
            data.get(
                "status",
                ""
            )
        ).lower().strip()

        amount = data.get(
            "amount",
            0
        )

        try:
            amount = float(amount)

        except Exception:
            amount = 0

        valid_statuses = {
            "success",
            "completed",
            "paid",
            "verified",
        }

        if status not in valid_statuses:
            return (
                False,
                f"Payment status: {status or 'unknown'}",
                data,
            )

        if amount != float(expected_amount):
            return (
                False,
                (
                    "Amount mismatch. "
                    f"Expected ₹{expected_amount}, "
                    f"received ₹{amount}"
                ),
                data,
            )

        return (
            True,
            "Payment verified.",
            data,
        )

    except requests.exceptions.Timeout:
        return (
            False,
            "Verification timeout.",
            None,
        )

    except Exception as error:
        return (
            False,
            f"Verification error: {error}",
            None,
        )


# ============================================================
# PAYMENT FULFILLMENT
# ============================================================

def fulfill_payment(claim):
    try:
        user_id = int(
            claim.get(
                "telegram_user_id"
            )
        )

        plan_id = claim.get(
            "plan_id"
        )

        plan = PLAN_CONFIG.get(
            plan_id
        )

        if not plan:
            return (
                False,
                "Invalid plan."
            )

        user = get_user(user_id)

        if not user:
            return (
                False,
                "User not found."
            )

        # ----------------------------------------------------
        # UNLIMITED
        # ----------------------------------------------------

        minutes = int(
            plan.get(
                "unlimited_minutes",
                0
            ) or 0
        )

        if minutes > 0:
            current_expiry = (
                user.get(
                    "unlimited_expiry"
                )
            )

            start = now_utc()

            if current_expiry:
                try:
                    expiry = datetime.fromisoformat(
                        str(
                            current_expiry
                        ).replace(
                            "Z",
                            "+00:00"
                        )
                    )

                    if expiry.tzinfo is None:
                        expiry = expiry.replace(
                            tzinfo=timezone.utc
                        )

                    if expiry > start:
                        start = expiry

                except Exception:
                    pass

            new_expiry = (
                start
                + timedelta(
                    minutes=minutes
                )
            )

            (
                supabase
                .table("telegram_users")
                .update({
                    "unlimited_expiry":
                        new_expiry.isoformat(),
                    "updated_at":
                        iso_now(),
                })
                .eq(
                    "telegram_user_id",
                    user_id
                )
                .execute()
            )

            return (
                True,
                (
                    "Unlimited activated until "
                    f"{new_expiry.astimezone(IST).strftime('%d-%m-%Y %H:%M')} IST"
                )
            )

        # ----------------------------------------------------
        # CREDITS
        # ----------------------------------------------------

        credits = int(
            plan.get(
                "credits",
                0
            ) or 0
        )

        if credits <= 0:
            return (
                False,
                "Invalid credit amount."
            )

        new_total = add_credits(
            user_id,
            credits
        )

        return (
            True,
            (
                f"Added {credits} credits.\n"
                f"Total balance: {new_total}"
            )
        )

    except Exception as error:
        print(
            "fulfill_payment:",
            error
        )

        return (
            False,
            str(error)
        )


# ============================================================
# UTR PROCESSING
# ============================================================

def process_utr_submission(
    user_id,
    utr,
    tx_code
):
    try:
        utr = str(
            utr or ""
        ).strip()

        tx_code = str(
            tx_code or ""
        ).strip()

        if not re.fullmatch(
            r"\d{12}",
            utr
        ):
            return (
                False,
                "UTR must contain exactly 12 digits.",
                None,
            )

        # ----------------------------------------------------
        # DUPLICATE UTR
        # ----------------------------------------------------

        existing = (
            supabase
            .table("payment_claims")
            .select("*")
            .eq("utr", utr)
            .limit(1)
            .execute()
        )

        if existing.data:
            return (
                False,
                "This UTR has already been used.",
                None,
            )

        # ----------------------------------------------------
        # CLAIM
        # ----------------------------------------------------

        claim_response = (
            supabase
            .table("payment_claims")
            .select("*")
            .eq(
                "payment_id",
                tx_code
            )
            .limit(1)
            .execute()
        )

        if not claim_response.data:
            return (
                False,
                "Transaction not found.",
                None,
            )

        claim = claim_response.data[0]

        # Prevent one user from submitting someone else's claim.
        if str(
            claim.get(
                "telegram_user_id"
            )
        ) != str(user_id):
            return (
                False,
                "This payment belongs to another account.",
                None,
            )

        if str(
            claim.get(
                "status",
                ""
            )
        ).lower() == "success":
            return (
                False,
                "Payment already verified.",
                claim,
            )

        expected_amount = float(
            claim.get(
                "amount",
                0
            )
        )

        # ----------------------------------------------------
        # VERIFY
        # ----------------------------------------------------

        ok, message, api_data = (
            verify_utr(
                utr,
                expected_amount
            )
        )

        if not ok:
            return (
                False,
                message,
                claim,
            )

        # ----------------------------------------------------
        # MARK SUCCESS
        # ----------------------------------------------------

        update_payload = {
            "utr": utr,
            "status": "success",
            "updated_at": iso_now(),
        }

        try:
            (
                supabase
                .table("payment_claims")
                .update({
                    **update_payload,
                    "raw_response": api_data,
                })
                .eq(
                    "id",
                    claim.get("id")
                )
                .execute()
            )

        except Exception:
            (
                supabase
                .table("payment_claims")
                .update(
                    update_payload
                )
                .eq(
                    "id",
                    claim.get("id")
                )
                .execute()
            )

        # ----------------------------------------------------
        # FULFILL
        # ----------------------------------------------------

        ok, detail = fulfill_payment(
            claim
        )

        if not ok:
            return (
                False,
                (
                    "Payment verified but "
                    "fulfillment failed. "
                    f"Contact @{ADMIN_USERNAME}"
                ),
                claim,
            )

        # ----------------------------------------------------
        # USER NOTIFICATION
        # ----------------------------------------------------

        try:
            bot.send_message(
                user_id,
                (
                    "✅ <b>Payment Verified</b>\n\n"
                    f"{escape_html(detail)}\n\n"
                    f"🧾 <code>{escape_html(tx_code)}</code>\n"
                    f"UTR: <code>{escape_html(utr)}</code>"
                ),
                parse_mode="HTML",
            )

        except Exception as error:
            print(
                "User payment notification:",
                error
            )

        # ----------------------------------------------------
        # ADMIN NOTIFICATION
        # ----------------------------------------------------

        try:
            bot.send_message(
                ADMIN_CHANNEL_ID,
                (
                    "✅ <b>Payment Verified</b>\n\n"
                    f"👤 <code>{user_id}</code>\n"
                    f"📦 <code>{escape_html(str(claim.get('plan_id')))}</code>\n"
                    f"💰 ₹{expected_amount:g}\n"
                    f"🧾 UTR: <code>{utr}</code>"
                ),
                parse_mode="HTML",
            )

        except Exception as error:
            print(
                "Admin notification:",
                error
            )

        return (
            True,
            detail,
            claim
        )

    except Exception as error:
        print(
            "process_utr_submission:",
            error
        )

        return (
            False,
            "Internal payment processing error.",
            None,
        )


# ============================================================
# PAYMENT QR
# ============================================================

def send_payment_qr(
    chat_id,
    user_id,
    username,
    plan_id
):
    plan = PLAN_CONFIG.get(
        plan_id
    )

    if not plan:
        bot.send_message(
            chat_id,
            "❌ Invalid plan.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )
        return

    tx_code = create_payment_claim(
        plan_id,
        user_id,
        username
    )

    if not tx_code:
        bot.send_message(
            chat_id,
            (
                "❌ Payment session could not "
                "be created.\n\n"
                f"Contact @{ADMIN_USERNAME}"
            ),
        )
        return

    caption = (
        "💳 <b>Payment Required</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>{escape_html(plan['label'])}</b>\n"
        f"💰 Amount: <b>₹{plan['amount']}</b>\n"
        f"🧾 ID: <code>{tx_code}</code>\n\n"
        "Scan QR and pay the exact amount.\n\n"
        "After payment, send the 12-digit UTR.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📞 @{ADMIN_USERNAME}"
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📸 SEND UTR",
            callback_data=f"submit_utr_{tx_code}"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 MAIN MENU",
            callback_data="main_menu"
        )
    )

    path = PAYMENT_QR_IMAGE

    if not os.path.isabs(path):
        path = os.path.join(
            os.getcwd(),
            path
        )

    try:
        if os.path.exists(path):
            with open(
                path,
                "rb"
            ) as image:
                bot.send_photo(
                    chat_id,
                    image,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
        else:
            bot.send_message(
                chat_id,
                caption
                + "\n\n⚠️ QR image not found.",
                reply_markup=markup,
                parse_mode="HTML",
            )

    except Exception as error:
        print(
            "send_payment_qr:",
            error
        )

        bot.send_message(
            chat_id,
            caption,
            reply_markup=markup,
            parse_mode="HTML",
        )


# ============================================================
# LOOKUP ACCESS
# ============================================================

def get_lookup_access(
    user,
    service
):
    """
    Returns:
        {
            "allowed": bool,
            "mode": "free" | "credits" | "unlimited" | None,
            "cost": int,
            "free_remaining": int,
            "credits": int
        }
    """

    cost = int(
        service.get(
            "cost",
            0
        )
    )

    unlimited, _ = get_active_unlimited(
        user
    )

    credits = int(
        user.get(
            "credits",
            0
        ) or 0
    )

    free_remaining = get_free_remaining(
        user
    )

    if unlimited:
        return {
            "allowed": True,
            "mode": "unlimited",
            "cost": cost,
            "free_remaining":
                free_remaining,
            "credits": credits,
        }

    if free_remaining > 0:
        return {
            "allowed": True,
            "mode": "free",
            "cost": cost,
            "free_remaining":
                free_remaining,
            "credits": credits,
        }

    if credits >= cost:
        return {
            "allowed": True,
            "mode": "credits",
            "cost": cost,
            "free_remaining":
                free_remaining,
            "credits": credits,
        }

    return {
        "allowed": False,
        "mode": None,
        "cost": cost,
        "free_remaining":
            free_remaining,
        "credits": credits,
    }


# ============================================================
# CONSUME LOOKUP ACCESS
# ============================================================

def consume_lookup_access(
    user_id,
    mode,
    cost
):
    """
    IMPORTANT:
    Call this ONLY after successful lookup result.
    """

    if mode == "unlimited":
        return True

    if mode == "free":
        return consume_free_lookup(
            user_id
        )

    if mode == "credits":
        return deduct_credits(
            user_id,
            cost
        )

    return False


# ============================================================
# LOOKUP PROCESSOR
# ============================================================

def process_lookup(message):
    user_id = message.from_user.id

    query_input = str(
        message.text or ""
    ).strip()

    if query_input in (
        "❌ CANCEL",
        "/cancel",
    ):
        user_states.pop(
            user_id,
            None
        )

        remove_active_session(
            user_id
        )

        bot.reply_to(
            message,
            "❌ Cancelled.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )

        return

    state = user_states.get(
        user_id
    )

    if not (
        isinstance(state, dict)
        and state.get("state")
        == "awaiting_lookup"
    ):
        return

    service_key = state.get(
        "service"
    )

    # Remove input state immediately.
    user_states.pop(
        user_id,
        None
    )

    service = LOOKUP_SERVICES.get(
        service_key
    )

    if not service:
        bot.reply_to(
            message,
            "❌ Invalid service.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )

        return

    # ========================================================
    # VALIDATE QUERY
    # ========================================================

    if service["query_type"] == "mobile":
        query_clean = normalize_indian_mobile(
            query_input
        )

        if not query_clean:
            bot.reply_to(
                message,
                (
                    "❌ <b>Invalid number</b>\n\n"
                    "Enter a valid 10-digit "
                    "Indian mobile number.\n\n"
                    "Example: "
                    "<code>9876543210</code>"
                ),
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
                parse_mode="HTML",
            )

            return

    else:
        query_clean = normalize_username(
            query_input
        )

        if not query_clean:
            bot.reply_to(
                message,
                (
                    "❌ <b>Invalid username</b>\n\n"
                    "Use a valid Telegram "
                    "username."
                ),
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
                parse_mode="HTML",
            )

            return

    # ========================================================
    # SESSION PROTECTION
    # ========================================================

    if is_active_session(user_id):
        bot.reply_to(
            message,
            "⏳ Search already in progress.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )

        return

    last_search = user_cooldown.get(
        user_id
    )

    if last_search:
        elapsed = (
            time.time()
            - last_search
        )

        if elapsed < COOLDOWN_SECONDS:
            remaining = max(
                1,
                int(
                    COOLDOWN_SECONDS
                    - elapsed
                )
            )

            bot.reply_to(
                message,
                (
                    f"⏳ Please wait "
                    f"{remaining}s."
                ),
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
            )

            return

    add_active_session(
        user_id
    )

    loading_message = None

    try:
        # ====================================================
        # USER
        # ====================================================

        user = get_user(
            user_id
        )

        if not user:
            bot.reply_to(
                message,
                (
                    "❌ Account could not "
                    "be loaded. Try again."
                ),
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
            )

            return

        if user.get(
            "is_banned"
        ):
            bot.reply_to(
                message,
                (
                    "🚫 <b>Account Banned</b>\n\n"
                    f"Contact @{ADMIN_USERNAME}"
                ),
                parse_mode="HTML",
            )

            return

        # ====================================================
        # ACCESS
        # ====================================================

        access = get_lookup_access(
            user,
            service
        )

        if not access["allowed"]:
            bot.reply_to(
                message,
                (
                    "❌ <b>Insufficient Credits</b>\n\n"
                    f"{service['emoji']} "
                    f"{escape_html(service['name'])}\n\n"
                    "🎁 Free lookups: "
                    "<b>0/3</b> remaining\n"
                    f"💎 Credits: "
                    f"<b>{access['credits']}</b>\n"
                    f"💳 Required: "
                    f"<b>{access['cost']}</b> credits\n\n"
                    "Buy credits or activate "
                    "Unlimited."
                ),
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
                parse_mode="HTML",
            )

            return

        user_cooldown[
            user_id
        ] = time.time()

        # ====================================================
        # LOADING
        # ====================================================

        mode_text = {
            "free": "🎁 Free lookup",
            "credits": (
                f"💎 {access['cost']} credits"
            ),
            "unlimited": "🚀 Unlimited",
        }.get(
            access["mode"],
            ""
        )

        loading_message = bot.reply_to(
            message,
            (
                f"{service['emoji']} "
                f"<b>Searching...</b>\n\n"
                f"{mode_text}"
            ),
            parse_mode="HTML",
        )

        # ====================================================
        # API CALL
        # ====================================================

        result = call_lookup_api(
            service_key,
            query_clean
        )

        # ====================================================
        # API FAILURE
        # ====================================================

        if (
            not result
            or result.get("error")
        ):
            output = (
                "<b>❌ Lookup Failed</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🔎 Query: "
                f"<code>{escape_html(query_clean)}</code>\n\n"
                f"{format_json_for_telegram(result or {'error': 'No response'})}\n\n"
                "💎 <b>No credits deducted</b>"
            )

            safe_edit_message(
                message.chat.id,
                loading_message.message_id,
                output,
                parse_mode="HTML",
            )

            return

        # ====================================================
        # EMPTY RESULT
        # ====================================================

        if not has_valid_results(
            result
        ):
            output = (
                f"<b>{service['emoji']} "
                f"{escape_html(service['name'].upper())}</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🔎 Query: "
                f"<code>{escape_html(query_clean)}</code>\n\n"
                "📄 <b>No usable result found.</b>\n\n"
                f"{format_json_for_telegram(result)}\n\n"
                "💎 <b>No credits deducted</b>"
            )

            send_or_edit_long_message(
                message.chat.id,
                loading_message.message_id,
                output,
                reply_markup=
                    lookup_result_markup(),
                parse_mode="HTML",
            )

            return

        # ====================================================
        # CHARGE ONLY AFTER SUCCESS
        # ====================================================

        charged = consume_lookup_access(
            user_id,
            access["mode"],
            access["cost"]
        )

        if not charged:
            safe_edit_message(
                message.chat.id,
                loading_message.message_id,
                (
                    "❌ <b>Could not reserve "
                    "lookup access.</b>\n\n"
                    "No result was charged."
                ),
                parse_mode="HTML",
            )

            return

        increment_total_searches(
            user_id
        )

        # ====================================================
        # UPDATED BALANCES
        # ====================================================

        updated_user = get_user(
            user_id
        )

        remaining_free = get_free_remaining(
            updated_user
        )

        remaining_credits = int(
            updated_user.get(
                "credits",
                0
            ) or 0
        )

        # ====================================================
        # OUTPUT
        # ====================================================

        output = (
            f"<b>{service['emoji']} "
            f"{escape_html(service['name'].upper())}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🔎 Query: "
            f"<code>{escape_html(query_clean)}</code>\n\n"
            "📄 <b>Result:</b>\n"
            f"{format_json_for_telegram(result)}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        if access["mode"] == "free":
            output += (
                "🎁 <b>Free lookup used</b>\n"
                f"🎁 Remaining free: "
                f"<b>{remaining_free}/3</b>"
            )

        elif access["mode"] == "credits":
            output += (
                f"💎 Used: "
                f"<b>{access['cost']}</b> credits\n"
                f"💎 Remaining: "
                f"<b>{remaining_credits}</b>"
            )

        else:
            output += (
                "🚀 <b>Unlimited Active</b>"
            )

        output += footer()

        send_or_edit_long_message(
            message.chat.id,
            loading_message.message_id,
            output,
            reply_markup=
                lookup_result_markup(),
            parse_mode="HTML",
        )

    except Exception as error:
        print(
            "process_lookup:",
            error
        )

        try:
            if loading_message:
                safe_edit_message(
                    message.chat.id,
                    loading_message.message_id,
                    (
                        "❌ <b>Search failed</b>\n\n"
                        "Please try again."
                    ),
                    parse_mode="HTML",
                )

            else:
                bot.reply_to(
                    message,
                    "❌ Search failed."
                )

        except Exception as inner:
            print(
                "Lookup error notification:",
                inner
            )

    finally:
        remove_active_session(
            user_id
        )


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

    user = get_user(
        user_id
    )

    if user and user.get(
        "is_banned"
    ):
        bot.reply_to(
            message,
            (
                "🚫 <b>Banned</b>\n\n"
                f"Contact @{ADMIN_USERNAME}"
            ),
            parse_mode="HTML",
        )

        return

    joined, missing = (
        check_all_channels(
            user_id
        )
    )

    if not joined:
        send_join_required(
            message.chat.id,
            missing
        )

        return

    if not user:
        user = get_user(
            user_id
        )

    credits = int(
        user.get(
            "credits",
            0
        ) or 0
    )

    free_remaining = get_free_remaining(
        user
    )

    unlimited, expiry = (
        get_active_unlimited(
            user
        )
    )

    unlimited_text = ""

    if unlimited and expiry:
        unlimited_text = (
            "\n🚀 Unlimited: "
            f"<b>{expiry.astimezone(IST).strftime('%d-%m-%Y %H:%M')}</b> IST"
        )

    welcome = (
        "🚀 <b>TRACEX LOOKUP</b>\n\n"
        f"👋 <b>{escape_html(first_name)}</b>\n\n"
        f"💎 Credits: <b>{credits}</b>"
        f"{unlimited_text}\n"
        f"🎁 Free lookups: "
        f"<b>{free_remaining}/3</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📋 <b>Services</b>\n\n"
        "📱 Number Info — "
        "<b>3 credits</b>\n"
        "💬 TG to Number — "
        "<b>10 credits</b>\n\n"
        "🎁 Every new account gets "
        "<b>3 lifetime free lookups</b>.\n"
        "After that, credits are required.\n\n"
        f"🌐 {WEBSITE_URL}\n"
        f"👨‍💻 @{ADMIN_USERNAME}\n\n"
        "👇 Choose a service."
    )

    bot.send_message(
        message.chat.id,
        welcome,
        reply_markup=
            get_main_keyboard_for_user(
                user_id
            ),
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
        None
    )

    remove_active_session(
        user_id
    )

    bot.reply_to(
        message,
        "❌ Cancelled.",
        reply_markup=
            get_main_keyboard_for_user(
                user_id
            ),
    )


# ============================================================
# /RESETCOOLDOWN
# ============================================================

@bot.message_handler(
    commands=["resetcooldown"]
)
def reset_cooldown(message):
    if not is_admin(
        message.from_user.id
    ):
        return

    user_cooldown.clear()

    with session_lock:
        active_sessions.clear()

    bot.reply_to(
        message,
        "✅ Cooldowns cleared."
    )


# ============================================================
# TEXT HANDLER
# ============================================================

@bot.message_handler(
    content_types=["text"]
)
def text_handler(message):
    user_id = message.from_user.id

    user = get_user(
        user_id
    )

    if user and user.get(
        "is_banned"
    ):
        bot.reply_to(
            message,
            (
                "🚫 <b>Banned</b>\n\n"
                f"Contact @{ADMIN_USERNAME}"
            ),
            parse_mode="HTML",
        )

        return

    joined, missing = (
        check_all_channels(
            user_id
        )
    )

    if not joined:
        send_join_required(
            message.chat.id,
            missing
        )

        return

    text = (
        message.text or ""
    ).strip()

    # ========================================================
    # STATES
    # ========================================================

    state = user_states.get(
        user_id
    )

    if isinstance(state, dict):

        if state.get(
            "state"
        ) == "awaiting_lookup":
            process_lookup(
                message
            )
            return

        if state.get(
            "state"
        ) == "awaiting_utr":

            tx_code = state.get(
                "tx_code"
            )

            user_states.pop(
                user_id,
                None
            )

            if text in (
                "❌ CANCEL",
                "/cancel"
            ):
                bot.reply_to(
                    message,
                    "❌ Cancelled.",
                    reply_markup=
                        get_main_keyboard_for_user(
                            user_id
                        ),
                )
                return

            ok, detail, _ = (
                process_utr_submission(
                    user_id,
                    text,
                    tx_code
                )
            )

            if ok:
                bot.reply_to(
                    message,
                    (
                        "✅ <b>Verified!</b>\n\n"
                        f"{escape_html(detail)}"
                    ),
                    reply_markup=
                        get_main_keyboard_for_user(
                            user_id
                        ),
                    parse_mode="HTML",
                )
            else:
                bot.reply_to(
                    message,
                    (
                        "❌ <b>Verification Failed</b>\n\n"
                        f"{escape_html(detail)}\n\n"
                        f"Contact @{ADMIN_USERNAME} "
                        "if payment was deducted."
                    ),
                    reply_markup=
                        get_main_keyboard_for_user(
                            user_id
                        ),
                    parse_mode="HTML",
                )

            return

        if state.get(
            "state"
        ) == "admin_add":
            process_admin_add(
                message
            )
            return

        if state.get(
            "state"
        ) == "admin_remove":
            process_admin_remove(
                message
            )
            return

        if state.get(
            "state"
        ) == "admin_ban":
            process_admin_ban(
                message
            )
            return

        if state.get(
            "state"
        ) == "admin_unban":
            process_admin_unban(
                message
            )
            return

    # ========================================================
    # MENU
    # ========================================================

    if text == "📱 NUMBER INFO":

        user_states[user_id] = {
            "state": "awaiting_lookup",
            "service": "number",
        }

        bot.reply_to(
            message,
            (
                "📱 <b>Number Info</b>\n\n"
                "Send a valid 10-digit "
                "mobile number.\n\n"
                "💳 Cost: "
                "<b>3 credits</b>\n"
                "🎁 New users get "
                "3 lifetime free lookups.\n\n"
                "Example:\n"
                "<code>9876543210</code>\n\n"
                "Type ❌ CANCEL to abort."
            ),
            reply_markup=
                get_cancel_keyboard(),
            parse_mode="HTML",
        )

    elif text == "💬 TG TO NUMBER":

        user_states[user_id] = {
            "state": "awaiting_lookup",
            "service": "telegram",
        }

        bot.reply_to(
            message,
            (
                "💬 <b>TG to Number</b>\n\n"
                "Send a Telegram username.\n\n"
                "💳 Cost: "
                "<b>10 credits</b>\n"
                "🎁 New users get "
                "3 lifetime free lookups.\n\n"
                "Example:\n"
                "<code>username</code>\n\n"
                "Type ❌ CANCEL to abort."
            ),
            reply_markup=
                get_cancel_keyboard(),
            parse_mode="HTML",
        )

    elif text == "💎 MY CREDITS":

        user = get_user(
            user_id
        )

        credits = int(
            user.get(
                "credits",
                0
            ) or 0
        )

        free_remaining = get_free_remaining(
            user
        )

        unlimited, expiry = (
            get_active_unlimited(
                user
            )
        )

        unlimited_text = (
            f"\n🚀 Unlimited until: "
            f"<b>{expiry.astimezone(IST).strftime('%d-%m-%Y %H:%M')}</b> IST"
            if unlimited and expiry
            else ""
        )

        total_searches = int(
            user.get(
                "total_searches",
                0
            ) or 0
        )

        bot.reply_to(
            message,
            (
                "💎 <b>My Account</b>\n\n"
                f"💰 Credits: <b>{credits}</b>\n"
                f"🎁 Free remaining: "
                f"<b>{free_remaining}/3</b>\n"
                f"🔎 Total searches: "
                f"<b>{total_searches}</b>"
                f"{unlimited_text}\n\n"
                "━━━━━━━━━━━━━━━━\n"
                "📱 Number Info: "
                "<b>3 credits</b>\n"
                "💬 TG to Number: "
                "<b>10 credits</b>"
            ),
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
            parse_mode="HTML",
        )

    elif text == "🛒 BUY CREDITS":

        bot.reply_to(
            message,
            (
                "💎 <b>Credit Store</b>\n\n"
                "• ₹50 → 50 credits\n"
                "• ₹100 → 100 credits\n"
                "• ₹200 → 200 credits\n"
                "• ₹500 → 500 credits\n\n"
                "🚀 <b>Unlimited</b>\n"
                "₹999 → 30 days\n\n"
                "📱 Number Info = "
                "<b>3 credits</b>\n"
                "💬 TG to Number = "
                "<b>10 credits</b>"
            ),
            reply_markup=
                credit_packs_markup(),
            parse_mode="HTML",
        )

    elif text == "🚀 UNLIMITED":

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "🚀 BUY ₹999",
                callback_data=
                    "plan_unlimited_999"
            )
        )

        markup.add(
            InlineKeyboardButton(
                "🔙 BACK",
                callback_data="main_menu"
            )
        )

        bot.reply_to(
            message,
            (
                "🚀 <b>Unlimited Plan</b>\n\n"
                "30 Days Unlimited\n\n"
                "💰 Price: "
                "<b>₹999</b>\n\n"
                "✅ Unlimited lookups\n"
                "✅ No credit deduction\n"
                "✅ All services included\n\n"
                "Tap below to continue."
            ),
            reply_markup=markup,
            parse_mode="HTML",
        )

    elif text == "📢 SUPPORT":

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "👨‍💻 CONTACT ADMIN",
                url=(
                    "https://t.me/"
                    f"{ADMIN_USERNAME}"
                )
            )
        )

        markup.add(
            InlineKeyboardButton(
                "🌐 WEBSITE",
                url=WEBSITE_URL
            )
        )

        bot.reply_to(
            message,
            (
                "📢 <b>Support</b>\n\n"
                f"👨‍💻 @{ADMIN_USERNAME}\n"
                f"🌐 {WEBSITE_URL}\n\n"
                "For payment or bot issues, "
                "contact admin."
            ),
            reply_markup=markup,
            parse_mode="HTML",
        )

    elif text == "🛠 ADMIN":

        if not is_admin(user_id):
            bot.reply_to(
                message,
                "❌ Unauthorized."
            )
            return

        show_admin_panel(
            message
        )

    elif text == "❌ CANCEL":

        user_states.pop(
            user_id,
            None
        )

        remove_active_session(
            user_id
        )

        bot.reply_to(
            message,
            "❌ Cancelled.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )

    else:

        bot.reply_to(
            message,
            (
                "❌ Unknown command.\n\n"
                "Use /start for menu."
            ),
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )


# ============================================================
# CALLBACK HANDLER
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callback_handler(call):
    user_id = call.from_user.id

    user = get_user(
        user_id
    )

    if user and user.get(
        "is_banned"
    ):
        bot.answer_callback_query(
            call.id,
            "You are banned!",
            show_alert=True
        )
        return

    # --------------------------------------------------------
    # CHANNEL CHECK
    # --------------------------------------------------------

    if call.data == "check_join":

        joined, missing = (
            check_all_channels(
                user_id
            )
        )

        if joined:

            bot.answer_callback_query(
                call.id,
                "✅ Verified!",
                show_alert=True
            )

            try:
                bot.edit_message_text(
                    (
                        "✅ <b>Verified!</b>\n\n"
                        "Use /start to open the menu."
                    ),
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=
                        get_main_keyboard_for_user(
                            user_id
                        ),
                    parse_mode="HTML",
                )

            except Exception:
                bot.send_message(
                    call.message.chat.id,
                    "✅ Verified! Use /start."
                )

        else:

            bot.answer_callback_query(
                call.id,
                "Join all required channels first.",
                show_alert=True
            )

            send_join_required(
                call.message.chat.id,
                missing
            )

        return

    # --------------------------------------------------------
    # GLOBAL CHANNEL CHECK
    # --------------------------------------------------------

    joined, missing = (
        check_all_channels(
            user_id
        )
    )

    if not joined:
        bot.answer_callback_query(
            call.id,
            "Join all required channels first.",
            show_alert=True
        )

        send_join_required(
            call.message.chat.id,
            missing
        )

        return

    # --------------------------------------------------------
    # MAIN MENU
    # --------------------------------------------------------

    if call.data == "main_menu":

        try:
            bot.edit_message_text(
                "🏠 <b>Main Menu</b>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
                parse_mode="HTML",
            )

        except Exception:
            bot.send_message(
                call.message.chat.id,
                "🏠 Main Menu",
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
            )

        bot.answer_callback_query(
            call.id
        )

    # --------------------------------------------------------
    # CANCEL
    # --------------------------------------------------------

    elif call.data == "cancel":

        user_states.pop(
            user_id,
            None
        )

        remove_active_session(
            user_id
        )

        bot.answer_callback_query(
            call.id,
            "Cancelled."
        )

        try:
            bot.edit_message_text(
                "❌ Cancelled.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=
                    get_main_keyboard_for_user(
                        user_id
                    ),
            )
        except Exception:
            pass

    # --------------------------------------------------------
    # BACK TO LOOKUP
    # --------------------------------------------------------

    elif call.data == "back_to_lookup":

        bot.send_message(
            call.message.chat.id,
            "👇 Choose a service.",
            reply_markup=
                get_main_keyboard_for_user(
                    user_id
                ),
        )

        bot.answer_callback_query(
            call.id
        )

    # --------------------------------------------------------
    # PAYMENT PLAN
    # --------------------------------------------------------

    elif call.data.startswith(
        "plan_"
    ):

        plan_id = call.data[
            len("plan_"):
        ]

        handle_plan_selection(
            call,
            plan_id
        )

    # --------------------------------------------------------
    # UTR
    # --------------------------------------------------------

    elif call.data.startswith(
        "submit_utr_"
    ):

        tx_code = call.data[
            len("submit_utr_"):
        ]

        # Validate ownership before accepting UTR.
        try:
            claim = (
                supabase
                .table("payment_claims")
                .select("*")
                .eq(
                    "payment_id",
                    tx_code
                )
                .limit(1)
                .execute()
            )

            if (
                not claim.data
                or str(
                    claim.data[0].get(
                        "telegram_user_id"
                    )
                ) != str(user_id)
            ):
                bot.answer_callback_query(
                    call.id,
                    "Invalid payment session.",
                    show_alert=True
                )
                return

        except Exception:
            bot.answer_callback_query(
                call.id,
                "Could not verify payment session.",
                show_alert=True
            )
            return

        user_states[user_id] = {
            "state": "awaiting_utr",
            "tx_code": tx_code,
        }

        bot.send_message(
            call.message.chat.id,
            (
                "📸 <b>Send UTR Number</b>\n\n"
                f"🧾 ID: <code>{escape_html(tx_code)}</code>\n\n"
                "Send the 12-digit UTR from "
                "your payment."
            ),
            reply_markup=cancel_button(),
            parse_mode="HTML",
        )

        bot.answer_callback_query(
            call.id,
            "Send UTR now."
        )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    elif call.data in (
        "admin_add",
        "admin_remove",
        "admin_ban",
        "admin_unban",
    ):

        if not is_admin(user_id):
            bot.answer_callback_query(
                call.id,
                "Unauthorized.",
                show_alert=True
            )
            return

        handle_admin_action(
            call
        )

    elif call.data == "admin_stats":

        if not is_admin(user_id):
            return

        show_admin_stats(
            call.message
        )

        bot.answer_callback_query(
            call.id
        )

    elif call.data == "admin_back":

        if not is_admin(user_id):
            return

        show_admin_panel(
            call.message
        )

        bot.answer_callback_query(
            call.id
        )


# ============================================================
# PLAN SELECTION
# ============================================================

def handle_plan_selection(
    call,
    plan_id
):
    user_id = call.from_user.id

    username = (
        call.from_user.username
        or "no_username"
    )

    if plan_id not in PLAN_CONFIG:
        bot.answer_callback_query(
            call.id,
            "Invalid plan.",
            show_alert=True
        )
        return

    bot.answer_callback_query(
        call.id,
        "Creating payment..."
    )

    send_payment_qr(
        call.message.chat.id,
        user_id,
        username,
        plan_id
    )


# ============================================================
# ADMIN
# ============================================================

def get_stats():
    try:
        users = (
            supabase
            .table("telegram_users")
            .select("*")
            .execute()
        )

        rows = users.data or []

        total_users = len(rows)

        total_searches = sum(
            int(
                row.get(
                    "total_searches",
                    0
                ) or 0
            )
            for row in rows
        )

        total_credits = sum(
            int(
                row.get(
                    "credits",
                    0
                ) or 0
            )
            for row in rows
        )

        banned = sum(
            1
            for row in rows
            if row.get(
                "is_banned"
            )
        )

        payments = (
            supabase
            .table("payment_claims")
            .select("amount")
            .eq(
                "status",
                "success"
            )
            .execute()
        )

        revenue = sum(
            float(
                row.get(
                    "amount",
                    0
                ) or 0
            )
            for row in (
                payments.data or []
            )
        )

        return {
            "total_users":
                total_users,
            "total_searches":
                total_searches,
            "total_credits":
                total_credits,
            "banned_users":
                banned,
            "total_revenue":
                revenue,
        }

    except Exception as error:
        print(
            "get_stats:",
            error
        )

        return {
            "total_users": 0,
            "total_searches": 0,
            "total_credits": 0,
            "banned_users": 0,
            "total_revenue": 0,
        }


def show_admin_panel(message):
    stats = get_stats()

    msg = (
        "🛠 <b>Admin Panel</b>\n\n"
        "📊 <b>Stats</b>\n"
        f"👥 Users: <b>{stats['total_users']}</b>\n"
        f"🔍 Searches: <b>{stats['total_searches']}</b>\n"
        f"💎 Credits: <b>{stats['total_credits']}</b>\n"
        f"💰 Revenue: <b>₹{stats['total_revenue']:.2f}</b>\n"
        f"🚫 Banned: <b>{stats['banned_users']}</b>"
    )

    markup = InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(
        InlineKeyboardButton(
            "➕ ADD",
            callback_data="admin_add"
        ),
        InlineKeyboardButton(
            "➖ REMOVE",
            callback_data="admin_remove"
        ),
    )

    markup.add(
        InlineKeyboardButton(
            "🚫 BAN",
            callback_data="admin_ban"
        ),
        InlineKeyboardButton(
            "✅ UNBAN",
            callback_data="admin_unban"
        ),
    )

    markup.add(
        InlineKeyboardButton(
            "📊 STATS",
            callback_data="admin_stats"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔙 BACK",
            callback_data="main_menu"
        )
    )

    bot.send_message(
        message.chat.id,
        msg,
        reply_markup=markup,
        parse_mode="HTML",
    )


def show_admin_stats(message):
    stats = get_stats()

    msg = (
        "📊 <b>Detailed Stats</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"🔍 Total Searches: <b>{stats['total_searches']}</b>\n"
        f"💎 Total Credits: <b>{stats['total_credits']}</b>\n"
        f"💰 Revenue: <b>₹{stats['total_revenue']:.2f}</b>\n"
        f"🚫 Banned: <b>{stats['banned_users']}</b>\n\n"
        f"🕐 {now_ist().strftime('%d-%m-%Y %H:%M:%S IST')}"
    )

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔙 BACK",
            callback_data="admin_back"
        )
    )

    bot.send_message(
        message.chat.id,
        msg,
        reply_markup=markup,
        parse_mode="HTML",
    )


def handle_admin_action(call):
    user_id = call.from_user.id

    if call.data == "admin_add":

        user_states[user_id] = {
            "state": "admin_add"
        }

        bot.send_message(
            call.message.chat.id,
            (
                "➕ <b>Add Credits</b>\n\n"
                "Format:\n"
                "<code>user_id credits</code>\n\n"
                "Example:\n"
                "<code>123456789 50</code>\n\n"
                "Type /cancel to abort."
            ),
            parse_mode="HTML",
        )

    elif call.data == "admin_remove":

        user_states[user_id] = {
            "state": "admin_remove"
        }

        bot.send_message(
            call.message.chat.id,
            (
                "➖ <b>Remove Credits</b>\n\n"
                "Format:\n"
                "<code>user_id credits</code>"
            ),
            parse_mode="HTML",
        )

    elif call.data == "admin_ban":

        user_states[user_id] = {
            "state": "admin_ban"
        }

        bot.send_message(
            call.message.chat.id,
            (
                "🚫 <b>Ban User</b>\n\n"
                "Send Telegram user ID."
            ),
            parse_mode="HTML",
        )

    elif call.data == "admin_unban":

        user_states[user_id] = {
            "state": "admin_unban"
        }

        bot.send_message(
            call.message.chat.id,
            (
                "✅ <b>Unban User</b>\n\n"
                "Send Telegram user ID."
            ),
            parse_mode="HTML",
        )

    bot.answer_callback_query(
        call.id
    )


def process_admin_add(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    user_states.pop(
        admin_id,
        None
    )

    if message.text == "/cancel":
        bot.reply_to(
            message,
            "Cancelled."
        )
        return

    try:
        parts = message.text.split()

        if len(parts) != 2:
            raise ValueError()

        target = int(parts[0])
        amount = int(parts[1])

        if amount <= 0:
            raise ValueError()

        if not get_user(target):
            bot.reply_to(
                message,
                "❌ User not found."
            )
            return

        total = add_credits(
            target,
            amount
        )

        bot.reply_to(
            message,
            (
                "✅ <b>Credits Added</b>\n\n"
                f"User: <code>{target}</code>\n"
                f"Added: <b>{amount}</b>\n"
                f"Total: <b>{total}</b>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        bot.reply_to(
            message,
            "❌ Invalid format."
        )


def process_admin_remove(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    user_states.pop(
        admin_id,
        None
    )

    if message.text == "/cancel":
        bot.reply_to(
            message,
            "Cancelled."
        )
        return

    try:
        parts = message.text.split()

        if len(parts) != 2:
            raise ValueError()

        target = int(parts[0])
        amount = int(parts[1])

        if amount <= 0:
            raise ValueError()

        user = get_user(
            target
        )

        if not user:
            bot.reply_to(
                message,
                "❌ User not found."
            )
            return

        current = int(
            user.get(
                "credits",
                0
            ) or 0
        )

        new_total = max(
            0,
            current - amount
        )

        (
            supabase
            .table("telegram_users")
            .update({
                "credits": new_total,
                "updated_at": iso_now(),
            })
            .eq(
                "telegram_user_id",
                target
            )
            .execute()
        )

        bot.reply_to(
            message,
            (
                "✅ <b>Credits Removed</b>\n\n"
                f"User: <code>{target}</code>\n"
                f"Removed: <b>{amount}</b>\n"
                f"Total: <b>{new_total}</b>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        bot.reply_to(
            message,
            "❌ Invalid format."
        )


def process_admin_ban(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    user_states.pop(
        admin_id,
        None
    )

    if message.text == "/cancel":
        bot.reply_to(
            message,
            "Cancelled."
        )
        return

    try:
        target = int(
            message.text.strip()
        )

        if not get_user(target):
            bot.reply_to(
                message,
                "❌ User not found."
            )
            return

        ban_user(
            target
        )

        bot.reply_to(
            message,
            (
                "🚫 <b>User Banned</b>\n\n"
                f"<code>{target}</code>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        bot.reply_to(
            message,
            "❌ Invalid user ID."
        )


def process_admin_unban(message):
    admin_id = message.from_user.id

    if not is_admin(admin_id):
        return

    user_states.pop(
        admin_id,
        None
    )

    if message.text == "/cancel":
        bot.reply_to(
            message,
            "Cancelled."
        )
        return

    try:
        target = int(
            message.text.strip()
        )

        if not get_user(target):
            bot.reply_to(
                message,
                "❌ User not found."
            )
            return

        unban_user(
            target
        )

        bot.reply_to(
            message,
            (
                "✅ <b>User Unbanned</b>\n\n"
                f"<code>{target}</code>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        bot.reply_to(
            message,
            "❌ Invalid user ID."
        )


# ============================================================
# ADMIN MANUAL PAYMENT VERIFY
# ============================================================

@bot.message_handler(
    commands=["verify"]
)
def verify_command(message):
    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split()

    if len(parts) != 2:
        bot.reply_to(
            message,
            "Usage: /verify TXCODE"
        )
        return

    tx_code = parts[1].strip()

    try:
        response = (
            supabase
            .table("payment_claims")
            .select("*")
            .eq(
                "payment_id",
                tx_code
            )
            .limit(1)
            .execute()
        )

        if not response.data:
            bot.reply_to(
                message,
                "❌ Transaction not found."
            )
            return

        claim = response.data[0]

        if str(
            claim.get("status")
        ).lower() == "success":
            bot.reply_to(
                message,
                "⚠️ Already verified."
            )
            return

        ok, detail = fulfill_payment(
            claim
        )

        if not ok:
            bot.reply_to(
                message,
                f"❌ {detail}"
            )
            return

        (
            supabase
            .table("payment_claims")
            .update({
                "status": "success",
                "updated_at": iso_now(),
            })
            .eq(
                "id",
                claim.get("id")
            )
            .execute()
        )

        bot.reply_to(
            message,
            (
                "✅ <b>Payment Fulfilled</b>\n\n"
                f"{escape_html(detail)}"
            ),
            parse_mode="HTML",
        )

    except Exception as error:
        bot.reply_to(
            message,
            (
                "❌ Verification error.\n\n"
                f"{escape_html(str(error))}"
            ),
            parse_mode="HTML",
        )


# ============================================================
# HEALTH SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return (
        f"TraceX Bot v{BOT_VERSION} - Running"
    )


@app.route("/health")
def health():
    return {
        "status": "ok",
        "version": BOT_VERSION,
        "time": iso_now(),
    }


def keep_alive():
    def run():
        port = int(
            os.getenv(
                "PORT",
                "8080"
            )
        )

        app.run(
            host="0.0.0.0",
            port=port,
            use_reloader=False,
        )

    thread = threading.Thread(
        target=run,
        daemon=True
    )

    thread.start()


# ============================================================
# STARTUP
# ============================================================

def print_startup():
    print("=" * 60)
    print(
        f"TraceX Lookup Bot v{BOT_VERSION}"
    )
    print("=" * 60)

    print(
        f"Admin: @{ADMIN_USERNAME}"
    )

    print(
        "\nServices:"
    )

    for key, service in LOOKUP_SERVICES.items():
        print(
            f"  {service['emoji']} "
            f"{service['name']} "
            f"= {service['cost']} credits"
        )

    print(
        f"\nNew-user free quota: "
        f"{FREE_LOOKUPS} lifetime lookups"
    )

    print(
        "\nDatabase mode:"
    )

    print(
        "  Existing telegram_users schema"
    )

    print(
        "  daily_free_used = lifetime free usage"
    )

    print(
        "  No daily reset"
    )

    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print_startup()

    keep_alive()

    print("✅ Flask health server started.")

    try:
        bot.remove_webhook()

        time.sleep(1)

    except Exception as error:
        print(
            "Webhook cleanup:",
            error
        )

    print("✅ Telegram webhook cleared.")
    print("🚀 Bot is running.")
    print("=" * 60)

    def signal_handler(
        sig,
        frame
    ):
        print(
            "\n🛑 Bot stopped."
        )

        sys.exit(0)

    signal.signal(
        signal.SIGINT,
        signal_handler
    )

    signal.signal(
        signal.SIGTERM,
        signal_handler
    )

    while True:

        try:
            bot.infinity_polling(
                timeout=30,
                skip_pending=True,
            )

        except KeyboardInterrupt:
            print(
                "\n🛑 Keyboard interrupt."
            )
            break

        except Exception as error:
            print(
                "Polling error:",
                error
            )

            time.sleep(5)
