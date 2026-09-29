"""
TraceX Lookup Bot - Premium Telecom Lookup Bot
Version: 12.0.0 - Simplified with Auto UTR Verification
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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
requests = _require_package("requests", "requests")
import time
import re
from datetime import datetime, timedelta, timezone
import threading
import signal
import uuid
import json
from flask import Flask

# ==================== SECURE CONFIGURATION ====================
def get_env_var(var_name, required=True, default=None):
    value = os.getenv(var_name)
    if required and not value:
        print(f"❌ Missing required environment variable: {var_name}")
        if default is not None:
            return default
        sys.exit(1)
    return value or default

BOT_TOKEN = get_env_var("BOT_TOKEN")
ADMIN_ID = int(get_env_var("ADMIN_ID", default="7850023357"))
ADMIN_CHANNEL_ID = int(get_env_var("ADMIN_CHANNEL_ID", default="-1003743686626"))
ADMIN_USERNAME = get_env_var("ADMIN_USERNAME", default="gaurav_beniwal_0001")

SUPABASE_URL = get_env_var("SUPABASE_URL")
SUPABASE_ANON_KEY = get_env_var("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = get_env_var("SUPABASE_SERVICE_ROLE_KEY", required=False)

# ==================== API CONFIGURATION ====================
LOOKUP_API_BASE = "https://gauravbeniwal.online/lookupportal/api/lookup.php"
UTR_VERIFY_API = "https://upipaymentgatewayhdfc.onrender.com/verify-utr"

# Required channels (must join all)
REQUIRED_CHANNELS = [
    {"name": "Gaurav Beniwal", "username": "@Gaurav_beni_0001", "link": "https://t.me/Gaurav_beni_0001"},
    {"name": "Beniwal Mods", "username": "@beniwalmods", "link": "https://t.me/beniwalmods"},
    {"name": "Beniwalzon YT", "username": "@BeniwalzonYT", "link": "https://t.me/BeniwalzonYT"},
    {"name": "Private Community", "username": "", "link": "https://t.me/+j7KaRgC8l14zODc1"},
]

# Services
LOOKUP_SERVICES = {
    "number": {
        "name": "Number Info",
        "emoji": "📱",
        "cost": 1,
        "query_type": "mobile",
        "placeholder": "9876543210",
    },
    "telegram": {
        "name": "Telegram to Number",
        "emoji": "💬",
        "cost": 1,
        "query_type": "username",
        "placeholder": "username",
    },
}

# Plans - simplified
PLAN_CONFIG = {
    "credits_50": {"amount": 50, "credits": 50, "label": "50 Credits - ₹50"},
    "credits_100": {"amount": 100, "credits": 100, "label": "100 Credits - ₹100"},
    "credits_200": {"amount": 200, "credits": 200, "label": "200 Credits - ₹200"},
    "credits_500": {"amount": 500, "credits": 500, "label": "500 Credits - ₹500"},
    "unlimited_999": {"amount": 999, "credits": 0, "unlimited_minutes": 43200, "label": "Unlimited 30 Days - ₹999"},
}

WEBSITE_URL = "https://gauravbeniwal.online/lookupportal"
PAYMENT_QR_IMAGE = get_env_var("PAYMENT_QR_IMAGE", required=False, default="payment_qr.png")

BOT_VERSION = "12.0.0"
FREE_DAILY_LIMIT = 3  # 3 free lookups per day combined
TELEGRAM_SAFE_LIMIT = 3900
COOLDOWN_SECONDS = 3

# ==================== SUPABASE CLIENT ====================
class _SupabaseResult:
    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count

class _SupabaseTableQuery:
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
        self.params[str(column)] = "eq." + str(value)
        return self

    def limit(self, n):
        self.params["limit"] = str(int(n))
        return self

    def range(self, start, end):
        self.params["offset"] = str(int(start))
        self.params["limit"] = str(int(end) - int(start) + 1)
        return self

    def order(self, column, desc=False):
        direction = "desc" if desc else "asc"
        self.params["order"] = f"{column}.{direction}"
        return self

    def execute(self):
        if not self.client.url or not self.client.key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
        url = f"{self.client.url}/rest/v1/{self.table}"
        headers = dict(self.client.headers)
        headers.update(self.headers)
        response = requests.request(
            self.method, url, params=self.params,
            json=self.payload, headers=headers, timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase REST error {response.status_code}: {response.text[:500]}")
        try:
            data = response.json() if response.text else []
        except Exception:
            data = []
        count = None
        content_range = response.headers.get("content-range") or response.headers.get("Content-Range")
        if content_range and "/" in content_range:
            try:
                total = content_range.split("/")[-1]
                count = None if total == "*" else int(total)
            except Exception:
                count = None
        if count is None and isinstance(data, list):
            count = len(data)
        return _SupabaseResult(data=data, count=count)

class _SupabaseLiteClient:
    def __init__(self, url, key):
        self.url = str(url or "").rstrip("/")
        self.key = str(key or "")
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def table(self, name):
        return _SupabaseTableQuery(self, name)

def create_client(url, key):
    return _SupabaseLiteClient(url, key)

Client = _SupabaseLiteClient

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)
SUPABASE_KEY = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

user_states = {}
user_cooldown = {}
temp_data = {}
active_sessions = set()
active_sessions_lock = threading.Lock()
IST = timezone(timedelta(hours=5, minutes=30))

# ==================== HELPER FUNCTIONS ====================
def escape_html(text):
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))

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
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📱 NUMBER INFO"),
        KeyboardButton("💬 TG TO NUMBER")
    )
    keyboard.add(
        KeyboardButton("💎 MY CREDITS"),
        KeyboardButton("🛒 BUY CREDITS")
    )
    keyboard.add(
        KeyboardButton("📢 SUPPORT"),
        KeyboardButton("🚀 UNLIMITED")
    )
    return keyboard

def get_main_keyboard_for_user(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📱 NUMBER INFO"),
        KeyboardButton("💬 TG TO NUMBER")
    )
    keyboard.add(
        KeyboardButton("💎 MY CREDITS"),
        KeyboardButton("🛒 BUY CREDITS")
    )
    keyboard.add(
        KeyboardButton("📢 SUPPORT"),
        KeyboardButton("🚀 UNLIMITED")
    )
    if str(user_id) == str(ADMIN_ID):
        keyboard.add(KeyboardButton("🛠 ADMIN"))
    return keyboard

def get_cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add(KeyboardButton("❌ CANCEL"))
    return keyboard

def get_channel_join_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for channel in REQUIRED_CHANNELS:
        markup.add(InlineKeyboardButton(f"📢 {channel['name']}", url=channel['link']))
    markup.add(InlineKeyboardButton("✅ I HAVE JOINED", callback_data="check_join"))
    return markup

def cancel_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ CANCEL", callback_data="cancel"))
    return markup

def credit_packs_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("₹50", callback_data="plan_credits_50"),
        InlineKeyboardButton("₹100", callback_data="plan_credits_100"),
        InlineKeyboardButton("₹200", callback_data="plan_credits_200"),
        InlineKeyboardButton("₹500", callback_data="plan_credits_500")
    )
    markup.add(InlineKeyboardButton("🚀 UNLIMITED 30D - ₹999", callback_data="plan_unlimited_999"))
    markup.add(InlineKeyboardButton("🔙 BACK", callback_data="main_menu"))
    return markup

def lookup_result_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔍 NEW SEARCH", callback_data="back_to_lookup"),
        InlineKeyboardButton("🏠 MENU", callback_data="main_menu")
    )
    return markup

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
        chunks = []
        lines = inner.split("\n")
        current = ""
        first_chunk = True
        
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
                    body, chat_id, message_id,
                    reply_markup=markup, parse_mode=parse_mode,
                    disable_web_page_preview=True
                ))
            else:
                sent_messages.append(bot.send_message(
                    chat_id, body,
                    reply_markup=markup, parse_mode=parse_mode,
                    disable_web_page_preview=True
                ))
        except Exception as e:
            print(f"Long message send error: {e}")
            try:
                plain = re.sub(r"<[^>]+>", "", body)
                if is_first:
                    sent_messages.append(bot.edit_message_text(
                        plain, chat_id, message_id,
                        reply_markup=markup, disable_web_page_preview=True
                    ))
                else:
                    sent_messages.append(bot.send_message(
                        chat_id, plain,
                        reply_markup=markup, disable_web_page_preview=True
                    ))
            except Exception as e2:
                print(f"Fallback send failed: {e2}")
    return sent_messages

def safe_edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.edit_message_text(
            text, chat_id, message_id,
            reply_markup=reply_markup, parse_mode=parse_mode,
            disable_web_page_preview=True
        )
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return None
        try:
            plain = re.sub(r"<[^>]+>", "", str(text))
            return bot.edit_message_text(
                plain, chat_id, message_id,
                reply_markup=reply_markup, disable_web_page_preview=True
            )
        except Exception as e2:
            print(f"safe_edit_message failed: {e} / fallback: {e2}")
            return None

def is_active_session(user_id):
    with active_sessions_lock:
        return user_id in active_sessions

def add_active_session(user_id):
    with active_sessions_lock:
        active_sessions.add(user_id)

def remove_active_session(user_id):
    with active_sessions_lock:
        active_sessions.discard(user_id)

# ==================== USER FUNCTIONS ====================
def get_user(telegram_user_id):
    try:
        response = supabase.table("telegram_users").select("*").eq("telegram_user_id", telegram_user_id).execute()
        if response.data and len(response.data) > 0:
            user = response.data[0]
            supabase.table("telegram_users").update({
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }).eq("telegram_user_id", telegram_user_id).execute()
            return user
        else:
            new_user = {
                "telegram_user_id": telegram_user_id,
                "credits": 0,
                "total_searches": 0,
                "daily_free_used": 0,
                "daily_reset_date": datetime.now(IST).strftime("%Y-%m-%d"),
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "is_banned": False
            }
            result = supabase.table("telegram_users").insert(new_user).execute()
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
    except Exception as e:
        print(f"Supabase get_user error: {e}")
        return None

def normalize_indian_mobile(value):
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits if re.match(r"^[6-9]\d{9}$", digits) else None

def add_credits(telegram_user_id, amount):
    try:
        response = supabase.table("telegram_users").select("credits").eq("telegram_user_id", telegram_user_id).execute()
        if not response.data or len(response.data) == 0:
            return 0
        current_credits = response.data[0].get('credits', 0)
        new_credits = current_credits + amount
        update_result = supabase.table("telegram_users").update({
            "credits": new_credits,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("telegram_user_id", telegram_user_id).execute()
        if update_result.data and len(update_result.data) > 0:
            return update_result.data[0].get('credits', new_credits)
        return new_credits
    except Exception as e:
        print(f"Add credits error: {e}")
        return 0

def deduct_credits(telegram_user_id, amount=1):
    try:
        user = get_user(telegram_user_id)
        if not user:
            return False
        
        # Check unlimited
        unlimited_expiry = user.get('unlimited_expiry')
        if unlimited_expiry:
            try:
                if isinstance(unlimited_expiry, str):
                    expiry_date = datetime.fromisoformat(unlimited_expiry.replace('Z', '+00:00'))
                else:
                    expiry_date = unlimited_expiry
                if expiry_date > datetime.now(timezone.utc):
                    return True
            except Exception:
                pass
        
        credits = int(user.get('credits', 0) or 0)
        if credits >= amount:
            supabase.table("telegram_users").update({
                "credits": credits - amount,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("telegram_user_id", telegram_user_id).execute()
            return True
        return False
    except Exception as e:
        print(f"Deduct credits error: {e}")
        return False

def increment_total_searches(telegram_user_id):
    try:
        user = get_user(telegram_user_id)
        if user:
            new_total = user.get('total_searches', 0) + 1
            supabase.table("telegram_users").update({
                "total_searches": new_total,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("telegram_user_id", telegram_user_id).execute()
            return True
    except Exception as e:
        print(f"Increment searches error: {e}")
    return False

def get_total_credits(telegram_user_id):
    try:
        user = get_user(telegram_user_id)
        return user.get('credits', 0) if user else 0
    except Exception as e:
        print(f"Get total credits error: {e}")
        return 0

def get_active_unlimited(user):
    unlimited_expiry_raw = user.get('unlimited_expiry') if user else None
    if not unlimited_expiry_raw:
        return False, None
    try:
        expiry_date = datetime.fromisoformat(str(unlimited_expiry_raw).replace('Z', '+00:00'))
        if expiry_date > datetime.now(timezone.utc):
            return True, str(unlimited_expiry_raw)
    except Exception:
        pass
    return False, None

def get_daily_free_remaining(user):
    """Get remaining free lookups for today"""
    if not user:
        return FREE_DAILY_LIMIT
    
    today = datetime.now(IST).strftime("%Y-%m-%d")
    reset_date = user.get('daily_reset_date', '')
    
    if reset_date != today:
        # Reset daily counter
        try:
            supabase.table("telegram_users").update({
                "daily_free_used": 0,
                "daily_reset_date": today,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("telegram_user_id", user.get('telegram_user_id')).execute()
        except Exception as e:
            print(f"Reset daily free error: {e}")
        return FREE_DAILY_LIMIT
    
    used = int(user.get('daily_free_used', 0) or 0)
    return max(0, FREE_DAILY_LIMIT - used)

def use_daily_free(telegram_user_id):
    """Increment daily free usage"""
    try:
        user = get_user(telegram_user_id)
        if not user:
            return False
        
        today = datetime.now(IST).strftime("%Y-%m-%d")
        reset_date = user.get('daily_reset_date', '')
        
        if reset_date != today:
            # New day - reset and use 1
            supabase.table("telegram_users").update({
                "daily_free_used": 1,
                "daily_reset_date": today,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("telegram_user_id", telegram_user_id).execute()
        else:
            used = int(user.get('daily_free_used', 0) or 0)
            supabase.table("telegram_users").update({
                "daily_free_used": used + 1,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("telegram_user_id", telegram_user_id).execute()
        return True
    except Exception as e:
        print(f"Use daily free error: {e}")
        return False

def ban_user(telegram_user_id):
    try:
        supabase.table("telegram_users").update({
            "is_banned": True,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("telegram_user_id", telegram_user_id).execute()
        return True
    except Exception as e:
        print(f"Ban user error: {e}")
        return False

def unban_user(telegram_user_id):
    try:
        supabase.table("telegram_users").update({
            "is_banned": False,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("telegram_user_id", telegram_user_id).execute()
        return True
    except Exception as e:
        print(f"Unban user error: {e}")
        return False

def get_stats():
    try:
        users_resp = supabase.table("telegram_users").select("*", count="exact").execute()
        total_users = users_resp.count
        searches_resp = supabase.table("telegram_users").select("total_searches").execute()
        total_searches = sum(u.get('total_searches', 0) for u in searches_resp.data)
        credits_resp = supabase.table("telegram_users").select("credits").execute()
        total_credits = sum(u.get('credits', 0) for u in credits_resp.data)
        banned_resp = supabase.table("telegram_users").select("*", count="exact").eq("is_banned", True).execute()
        banned_users = banned_resp.count
        revenue_resp = supabase.table("payment_claims").select("amount").eq("status", "success").execute()
        total_revenue = sum(p.get('amount', 0) for p in revenue_resp.data)
        return {
            'total_users': total_users,
            'total_searches': total_searches,
            'total_credits': total_credits,
            'banned_users': banned_users,
            'total_revenue': total_revenue,
        }
    except Exception as e:
        print(f"Get stats error: {e}")
        return {
            'total_users': 0, 'total_searches': 0, 'total_credits': 0,
            'banned_users': 0, 'total_revenue': 0,
        }

def get_all_users_batch(limit=1000, offset=0):
    try:
        response = supabase.table("telegram_users").select("telegram_user_id").eq("is_banned", False).range(offset, offset + limit - 1).execute()
        return [row['telegram_user_id'] for row in response.data]
    except Exception as e:
        print(f"Get users batch error: {e}")
        return []

def get_total_users_count():
    try:
        response = supabase.table("telegram_users").select("*", count="exact").eq("is_banned", False).execute()
        return response.count or 0
    except Exception as e:
        print(f"Get total users error: {e}")
        return 0

# ==================== LOOKUP API ====================
def call_lookup_api(service, query):
    """Call the lookup API and return JSON response"""
    try:
        url = f"{LOOKUP_API_BASE}?service={service}&spell={query}"
        print(f"[LOOKUP] Service: {service}, Query: {query}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 16) TraceXBot/12.0.0",
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
            data = response.json()
            return data
        except Exception:
            return {"raw_response": content, "success": True}
            
    except requests.exceptions.Timeout:
        return {"error": "timeout", "success": False}
    except requests.exceptions.ConnectionError:
        return {"error": "connection_error", "success": False}
    except Exception as e:
        return {"error": f"exception_{e}", "success": False}

def has_valid_results(result):
    if not isinstance(result, dict):
        return False
    if result.get('error'):
        return False
    
    # Check for common success indicators
    if result.get('success') == True:
        return True
    
    # Check for data fields
    valid_fields = ['name', 'mobile', 'phone', 'address', 'circle', 'operator', 
                    'telegram_id', 'username', 'first_name', 'last_name', 'data', 'result']
    for field in valid_fields:
        value = result.get(field)
        if value and str(value).strip() and str(value).strip().lower() not in ['none', 'null', 'n/a', '']:
            return True
    
    # Check nested data
    for key, value in result.items():
        if isinstance(value, dict) and value:
            return True
        elif isinstance(value, list) and value:
            return True
    
    return False

# ==================== PAYMENT FUNCTIONS ====================
def create_payment_claim(plan_id, telegram_user_id, telegram_username):
    try:
        plan = PLAN_CONFIG.get(plan_id)
        if not plan:
            return None
        tx_code = "TX" + uuid.uuid4().hex[:12].upper()
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "payment_id": tx_code,
            "telegram_user_id": str(telegram_user_id),
            "telegram_username": str(telegram_username or "no_username"),
            "plan_id": plan_id,
            "amount": plan["amount"],
            "credits": plan.get("credits", 0),
            "payment_for": "unlimited" if "unlimited" in plan_id else "credits",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        supabase.table("payment_claims").insert(payload).execute()
        return tx_code
    except Exception as e:
        print(f"Create payment claim error: {e}")
        return None

def verify_utr(utr, expected_amount):
    """Verify UTR payment with API"""
    try:
        url = f"{UTR_VERIFY_API}?utr={utr}"
        print(f"[UTR] Verifying: {utr}")
        response = requests.get(url, timeout=30)
        print(f"[UTR] Status: {response.status_code}")
        
        if response.status_code != 200:
            return False, f"API error: HTTP {response.status_code}", None
        
        try:
            data = response.json()
        except Exception:
            return False, "Invalid JSON response", None
        
        # Check if payment successful
        status = str(data.get('status', '')).lower()
        amount = data.get('amount', 0)
        
        # Convert amount to float if string
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            amount = 0
        
        if status not in ['success', 'completed', 'paid', 'verified']:
            return False, f"Payment not successful. Status: {status}", data
        
        # Check amount matches exactly
        if amount != float(expected_amount):
            return False, f"Amount mismatch. Expected: ₹{expected_amount}, Got: ₹{amount}", data
        
        return True, "Payment verified", data
        
    except requests.exceptions.Timeout:
        return False, "Verification timeout", None
    except Exception as e:
        return False, f"Verification error: {e}", None

def fulfill_payment(claim):
    """Fulfill payment after UTR verification"""
    try:
        telegram_user_id = claim.get("telegram_user_id")
        plan_id = claim.get("plan_id")
        plan = PLAN_CONFIG.get(plan_id)
        
        if not telegram_user_id or not plan:
            return False, "Invalid claim data"
        
        if plan.get("unlimited_minutes", 0) > 0:
            # Unlimited plan
            minutes = plan["unlimited_minutes"]
            user = get_user(int(telegram_user_id))
            now_dt = datetime.now(timezone.utc)
            start_from = now_dt
            current_expiry = user.get("unlimited_expiry") if user else None
            if current_expiry:
                try:
                    expiry_dt = datetime.fromisoformat(str(current_expiry).replace("Z", "+00:00"))
                    if expiry_dt > now_dt:
                        start_from = expiry_dt
                except Exception:
                    pass
            new_expiry = start_from + timedelta(minutes=minutes)
            supabase.table("telegram_users").update({
                "unlimited_expiry": new_expiry.isoformat(),
                "updated_at": now_dt.isoformat()
            }).eq("telegram_user_id", int(telegram_user_id)).execute()
            return True, f"Unlimited activated until {new_expiry.strftime('%Y-%m-%d %H:%M')} IST"
        else:
            # Credits
            credits = int(plan.get("credits", 0))
            if credits <= 0:
                return False, "No credits in plan"
            new_total = add_credits(int(telegram_user_id), credits)
            return True, f"Added {credits} credits. Total: {new_total}"
            
    except Exception as e:
        print(f"Fulfill payment error: {e}")
        return False, str(e)

def process_utr_submission(user_id, utr, tx_code):
    """Process UTR submission and verify"""
    try:
        utr = str(utr or "").strip()
        tx_code = str(tx_code or "").strip()
        
        # Validate UTR format (typically 12 digits)
        if not re.match(r'^\d{12}$', utr):
            return False, "Invalid UTR. Must be 12 digits.", None
        
        # Check if UTR already used
        try:
            existing = supabase.table("payment_claims").select("*").eq("utr", utr).execute()
            if existing.data and len(existing.data) > 0:
                return False, "This UTR has already been used.", None
        except Exception as e:
            print(f"UTR check error: {e}")
        
        # Get claim
        claim_resp = None
        for field in ["payment_id", "session_id"]:
            try:
                claim_resp = supabase.table("payment_claims").select("*").eq(field, tx_code).limit(1).execute()
                if claim_resp.data:
                    break
            except Exception:
                pass
        
        if not claim_resp or not claim_resp.data:
            return False, "Transaction not found.", None
        
        claim = claim_resp.data[0]
        
        if str(claim.get("status") or "").lower() == "success":
            return False, "Payment already verified.", claim
        
        expected_amount = float(claim.get("amount", 0))
        
        # Verify UTR
        success, message, api_data = verify_utr(utr, expected_amount)
        
        if not success:
            return False, message, claim
        
        # Mark UTR as used and update claim
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("payment_claims").update({
            "utr": utr,
            "status": "success",
            "updated_at": now,
            "raw_response": api_data
        }).eq("id", claim.get("id")).execute()
        
        # Fulfill payment
        ok, detail = fulfill_payment(claim)
        
        if ok:
            # Notify user
            try:
                bot.send_message(
                    int(claim.get("telegram_user_id")),
                    f"✅ *Payment Verified!*\n\n{detail}\n\n🧾 `{tx_code}`\nUTR: `{utr}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"User notify error: {e}")
            
            # Notify admin
            try:
                bot.send_message(
                    ADMIN_CHANNEL_ID,
                    f"✅ *Payment Verified*\n\n"
                    f"👤 `{claim.get('telegram_user_id')}`\n"
                    f"📦 `{claim.get('plan_id')}`\n"
                    f"💰 ₹{expected_amount}\n"
                    f"🧾 UTR: `{utr}`",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Admin notify error: {e}")
        
        return ok, detail, claim
        
    except Exception as e:
        print(f"Process UTR error: {e}")
        return False, str(e), None

def send_payment_qr(chat_id, user_id, username, plan_id):
    plan = PLAN_CONFIG.get(plan_id)
    if not plan:
        bot.send_message(chat_id, "❌ Invalid plan.", reply_markup=get_main_keyboard_for_user(user_id))
        return
    
    tx_code = create_payment_claim(plan_id, user_id, username)
    if not tx_code:
        bot.send_message(chat_id, f"❌ Failed. Contact @{ADMIN_USERNAME}")
        return
    
    caption = f"""💳 *Payment Required*
━━━━━━━━━━━━━━━━━━
📦 `{plan['label']}`
💰 Amount: *₹{plan['amount']}*
🧾 ID: `{tx_code}`

Scan QR and pay exact amount.

After payment, send the UTR number (12 digits).
━━━━━━━━━━━━━━━━━━
📞 @{ADMIN_USERNAME}"""
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📸 SEND UTR", callback_data=f"submit_utr_{tx_code}"))
    markup.add(InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu"))
    
    qr_path = PAYMENT_QR_IMAGE
    if not os.path.isabs(qr_path):
        qr_path = os.path.join(os.getcwd(), qr_path)
    
    try:
        if os.path.exists(qr_path):
            with open(qr_path, "rb") as img:
                bot.send_photo(chat_id, img, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, caption + "\n\n⚠️ QR file missing.", reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Send QR error: {e}")
        bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="Markdown")

# ==================== CHANNEL CHECK ====================
def is_channel_member(user_id, channel_username):
    if str(user_id) == str(ADMIN_ID):
        return True
    if not channel_username:
        return True  # Can't check without username
    try:
        member = bot.get_chat_member(channel_username, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Channel check error for {channel_username}: {e}")
        return False

def check_all_channels(user_id):
    if str(user_id) == str(ADMIN_ID):
        return True, []
    
    missing = []
    for channel in REQUIRED_CHANNELS:
        if channel['username']:
            if not is_channel_member(user_id, channel['username']):
                missing.append(channel)
        # For private channels without username, we can't verify - assume joined
    
    return len(missing) == 0, missing

def send_join_required(chat_id, missing_channels=None):
    if missing_channels is None:
        all_joined, missing_channels = check_all_channels(chat_id)
        if all_joined:
            return True
    
    if missing_channels:
        channel_list = "\n".join([f"• {ch['name']}" for ch in missing_channels])
        message = f"""🔒 *Join Required*

Join these channels to use the bot:

{channel_list}

After joining, tap ✅ button below."""
        
        bot.send_message(
            chat_id, message,
            reply_markup=get_channel_join_markup(),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        return False
    return True

# ==================== LOOKUP PROCESSOR ====================
def process_lookup(message):
    """Unified lookup handler for both services"""
    user_id = message.from_user.id
    query_input = str(message.text or "").strip()

    if query_input == "❌ CANCEL" or query_input == "/cancel":
        user_states.pop(user_id, None)
        remove_active_session(user_id)
        bot.reply_to(message, "❌ Cancelled.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        return

    state = user_states.get(user_id)
    if not (isinstance(state, dict) and state.get("state") == "awaiting_lookup"):
        return

    service_key = state.get("service")
    user_states.pop(user_id, None)

    service = LOOKUP_SERVICES.get(service_key)
    if not service:
        bot.reply_to(message, "❌ Invalid service.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        return

    # Validate query
    query_clean = query_input
    if service["query_type"] == "mobile":
        phone = normalize_indian_mobile(query_input)
        if not phone:
            bot.reply_to(message, f"❌ *Invalid number!*\n\nEnter 10-digit mobile number.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
            return
        query_clean = phone
    elif service["query_type"] == "username":
        query_clean = query_input.lstrip('@')

    if is_active_session(user_id):
        bot.reply_to(message, "⏳ *Search in progress...*", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        return

    if user_id in user_cooldown:
        if time.time() - user_cooldown[user_id] < COOLDOWN_SECONDS:
            wait_time = int(COOLDOWN_SECONDS - (time.time() - user_cooldown[user_id]))
            bot.reply_to(message, f"⏳ *Wait {wait_time}s*", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
            return

    add_active_session(user_id)
    loading_msg = None

    try:
        user = get_user(user_id)
        unlimited_active, unlimited_expiry = get_active_unlimited(user)
        daily_free_remaining = get_daily_free_remaining(user)
        total_credits = get_total_credits(user_id)
        cost = service.get("cost", 1)

        # Check access: free daily, unlimited, or credits
        use_free = False
        if not unlimited_active:
            if daily_free_remaining > 0:
                use_free = True
            elif total_credits < cost:
                bot.reply_to(message, f"""❌ *Free limit reached*

Daily free: 0/3 used

💎 Credits: `{total_credits}`
Need: `{cost}` credits

Buy credits or unlimited plan.""",
                reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
                return

        user_cooldown[user_id] = time.time()
        loading_msg = bot.reply_to(message, f"{service['emoji']} *Searching...*", parse_mode='Markdown')

        time.sleep(0.5)

        # Call API
        result = call_lookup_api(service_key, query_clean)

        # Check result
        if not result or result.get('error'):
            output = f"""<b>❌ Error</b>
━━━━━━━━━━━━━━━━━━
Query: <code>{escape_html(query_clean)}</code>

{format_json_for_telegram(result or {"error": "No response"})}

💎 Credits NOT deducted"""
            safe_edit_message(message.chat.id, loading_msg.message_id, output, parse_mode='HTML')
            return

        # Check if valid results
        if has_valid_results(result):
            # Deduct credit or use free
            if unlimited_active:
                pass  # No deduction
            elif use_free:
                use_daily_free(user_id)
            else:
                if not deduct_credits(user_id, cost):
                    safe_edit_message(message.chat.id, loading_msg.message_id, "❌ <b>Failed to deduct credit.</b>", parse_mode='HTML')
                    return
            
            increment_total_searches(user_id)
            
            # Format result
            updated_total = get_total_credits(user_id)
            new_free_remaining = get_daily_free_remaining(get_user(user_id))
            
            json_output = format_json_for_telegram(result)
            
            output = f"""<b>{service['emoji']} {service['name'].upper()}</b>
━━━━━━━━━━━━━━━━━━

🔎 Query: <code>{escape_html(query_clean)}</code>

📄 <b>Result:</b>
{json_output}

━━━━━━━━━━━━━━━━━━"""
            
            if unlimited_active:
                output += f"\n🚀 Unlimited Active"
            elif use_free:
                output += f"\n🎁 Free: {new_free_remaining}/3 remaining"
            else:
                output += f"\n💎 Used: {cost} | Left: {updated_total}"
            
            output += footer()
            
            send_or_edit_long_message(
                message.chat.id,
                loading_msg.message_id,
                output,
                reply_markup=lookup_result_markup(),
                parse_mode='HTML'
            )
        else:
            # No valid data - don't deduct
            output = f"""<b>{service['emoji']} {service['name'].upper()}</b>
━━━━━━━━━━━━━━━━━━

🔎 Query: <code>{escape_html(query_clean)}</code>

📄 <b>Response:</b>
{format_json_for_telegram(result)}

━━━━━━━━━━━━━━━━━━
💎 Credits NOT deducted"""
            
            send_or_edit_long_message(
                message.chat.id,
                loading_msg.message_id,
                output,
                parse_mode='HTML'
            )

    except Exception as e:
        print(f"process_lookup error: {e}")
        try:
            if loading_msg:
                safe_edit_message(
                    message.chat.id,
                    loading_msg.message_id,
                    f"❌ <b>Search failed!</b>\n\nError: <code>{escape_html(str(e)[:100])}</code>",
                    parse_mode='HTML'
                )
            else:
                bot.reply_to(message, "❌ *Search failed!*", parse_mode='Markdown')
        except Exception as inner:
            print(f"Error notify: {inner}")
    finally:
        remove_active_session(user_id)

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    
    user = get_user(user_id)
    if user and user.get('is_banned'):
        bot.reply_to(message, f"🚫 *Banned*\n\nContact: @{ADMIN_USERNAME}", parse_mode='Markdown')
        return
    
    all_joined, missing = check_all_channels(user_id)
    if not all_joined and str(user_id) != str(ADMIN_ID):
        send_join_required(message.chat.id, missing)
        return
    
    if not user:
        user = get_user(user_id)
    
    total_credits = get_total_credits(user_id)
    unlimited_active, unlimited_expiry = get_active_unlimited(user)
    daily_free = get_daily_free_remaining(user)
    
    unlimited_text = ""
    if unlimited_active:
        unlimited_text = f"\n🚀 Unlimited: Active"
    
    welcome_msg = f"""🚀 *TRACEX LOOKUP*

👋 *{first_name}*

💎 Credits: `{total_credits}`{unlimited_text}
🎁 Free today: `{daily_free}/3`

━━━━━━━━━━━━━━━━
📋 *Services:*

📱 Number Info — Free (3/day)
💬 TG to Number — Free (3/day)

After free limit:
💎 1 credit per lookup

━━━━━━━━━━━━━━━━
🌐 {WEBSITE_URL}
👨‍💻 @{ADMIN_USERNAME}

👇 Choose a service"""
    
    bot.send_message(message.chat.id, welcome_msg, reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown', disable_web_page_preview=True)

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    temp_data.pop(user_id, None)
    remove_active_session(user_id)
    bot.reply_to(message, "❌ Cancelled.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')

@bot.message_handler(commands=['resetcooldown'])
def reset_cooldown(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    user_cooldown.clear()
    with active_sessions_lock:
        active_sessions.clear()
    bot.reply_to(message, "✅ Cooldowns cleared!")

@bot.message_handler(content_types=['text'])
def text_handler(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user and user.get('is_banned'):
        bot.reply_to(message, f"🚫 *Banned*\n\nContact: @{ADMIN_USERNAME}", parse_mode='Markdown')
        return
    
    all_joined, missing = check_all_channels(user_id)
    if not all_joined and str(user_id) != str(ADMIN_ID):
        send_join_required(message.chat.id, missing)
        return
    
    text = message.text.strip()
    
    # Check states
    state = user_states.get(user_id)
    if isinstance(state, dict):
        if state.get("state") == "awaiting_lookup":
            process_lookup(message)
            return
        elif state.get("state") == "awaiting_utr":
            # Handle UTR submission
            tx_code = state.get("tx_code")
            user_states.pop(user_id, None)
            
            if text == "❌ CANCEL" or text == "/cancel":
                bot.reply_to(message, "❌ Cancelled.", reply_markup=get_main_keyboard_for_user(user_id))
                return
            
            ok, msg, claim = process_utr_submission(user_id, text, tx_code)
            if ok:
                bot.reply_to(message, f"✅ *Verified!*\n\n{msg}", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
            else:
                bot.reply_to(message, f"❌ *Failed*\n\n{msg}\n\nTry again or contact @{ADMIN_USERNAME}", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
            return
        elif state.get("state") == "admin_add":
            process_admin_add(message)
            return
        elif state.get("state") == "admin_remove":
            process_admin_remove(message)
            return
        elif state.get("state") == "admin_ban":
            process_admin_ban(message)
            return
        elif state.get("state") == "admin_unban":
            process_admin_unban(message)
            return
    
    # Service buttons
    if text == "📱 NUMBER INFO":
        user_states[user_id] = {"state": "awaiting_lookup", "service": "number"}
        bot.reply_to(message, "📱 *Number Info*\n\nSend 10-digit mobile number.\n\nExample: `9876543210`\n\nType ❌ CANCEL to abort",
                    reply_markup=get_cancel_keyboard(), parse_mode='Markdown')
    elif text == "💬 TG TO NUMBER":
        user_states[user_id] = {"state": "awaiting_lookup", "service": "telegram"}
        bot.reply_to(message, "💬 *Telegram to Number*\n\nSend Telegram username.\n\nExample: `username`\n\nType ❌ CANCEL to abort",
                    reply_markup=get_cancel_keyboard(), parse_mode='Markdown')
    elif text == "💎 MY CREDITS":
        total_credits = get_total_credits(user_id)
        unlimited_active, unlimited_expiry = get_active_unlimited(user)
        daily_free = get_daily_free_remaining(user)
        
        unlimited_text = ""
        if unlimited_active:
            unlimited_text = "\n🚀 Unlimited: Active"
        
        msg = f"""💎 *My Credits*

💰 Credits: `{total_credits}`{unlimited_text}
🎁 Free today: `{daily_free}/3`
🔎 Total searches: `{user.get('total_searches', 0) if user else 0}`

━━━━━━━━━━━━━━━━
🌐 {WEBSITE_URL}"""
        bot.reply_to(message, msg, parse_mode='Markdown')
    elif text == "🛒 BUY CREDITS":
        msg = f"""💎 *Credit Store*

*Credit Packs:*
• ₹50 → 50 credits
• ₹100 → 100 credits
• ₹200 → 200 credits
• ₹500 → 500 credits

*Unlimited:*
🚀 ₹999 → 30 Days Unlimited

━━━━━━━━━━━━━━━━
1 Credit = ₹1
Credits never expire."""
        bot.reply_to(message, msg, reply_markup=credit_packs_markup(), parse_mode='Markdown')
    elif text == "🚀 UNLIMITED":
        msg = f"""🚀 *Unlimited Plan*

*30 Days Unlimited*
💰 Price: ₹999

✅ Unlimited lookups
✅ No daily limits
✅ All services included

━━━━━━━━━━━━━━━━
Tap below to buy."""
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 BUY ₹999", callback_data="plan_unlimited_999"))
        markup.add(InlineKeyboardButton("🔙 BACK", callback_data="main_menu"))
        bot.reply_to(message, msg, reply_markup=markup, parse_mode='Markdown')
    elif text == "📢 SUPPORT":
        msg = f"""📢 *Support*

👨‍💻 @{ADMIN_USERNAME}
🌐 {WEBSITE_URL}

For issues, contact admin."""
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("👨‍💻 CONTACT ADMIN", url=f"https://t.me/{ADMIN_USERNAME}"))
        markup.add(InlineKeyboardButton("🌐 WEBSITE", url=WEBSITE_URL))
        bot.reply_to(message, msg, reply_markup=markup, parse_mode='Markdown')
    elif text == "🛠 ADMIN":
        if str(user_id) != str(ADMIN_ID):
            bot.reply_to(message, "❌ Unauthorized!", reply_markup=get_main_keyboard_for_user(user_id))
            return
        show_admin_panel(message)
    elif text == "❌ CANCEL":
        user_states.pop(user_id, None)
        temp_data.pop(user_id, None)
        remove_active_session(user_id)
        bot.reply_to(message, "❌ Cancelled.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
    else:
        bot.reply_to(message, "❌ Unknown command.\n\nUse /start for menu.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')

# ==================== CALLBACK HANDLERS ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    if user and user.get('is_banned'):
        bot.answer_callback_query(call.id, "You are banned!", show_alert=True)
        return
    
    if call.data == "check_join":
        all_joined, missing = check_all_channels(user_id)
        if all_joined or str(user_id) == str(ADMIN_ID):
            bot.answer_callback_query(call.id, "✅ All channels joined!", show_alert=True)
            try:
                bot.edit_message_text("✅ *Verified!*\n\nUse /start to open menu.", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard_for_user(user_id), parse_mode="Markdown")
            except Exception:
                bot.send_message(call.message.chat.id, "✅ Verified! Use /start")
        else:
            bot.answer_callback_query(call.id, f"Missing: {', '.join([ch['name'] for ch in missing])}", show_alert=True)
            send_join_required(call.message.chat.id, missing)
        return
    
    all_joined, missing = check_all_channels(user_id)
    if not all_joined and str(user_id) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "Join all channels first!", show_alert=True)
        send_join_required(call.message.chat.id, missing)
        return
    
    if call.data == "main_menu":
        try:
            bot.edit_message_text("🏠 *Main Menu*", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        except Exception:
            bot.send_message(call.message.chat.id, "🏠 *Main Menu*", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    elif call.data == "cancel":
        user_states.pop(user_id, None)
        temp_data.pop(user_id, None)
        remove_active_session(user_id)
        bot.answer_callback_query(call.id, "Cancelled")
        try:
            bot.edit_message_text("❌ Cancelled.", call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        except Exception:
            pass
    elif call.data == "back_to_lookup":
        bot.send_message(call.message.chat.id, "👇 Choose a service.", reply_markup=get_main_keyboard_for_user(user_id), parse_mode='Markdown')
        bot.answer_callback_query(call.id)
    elif call.data.startswith("plan_"):
        plan_id = call.data.replace("plan_", "")
        handle_plan_selection(call, plan_id)
    elif call.data.startswith("submit_utr_"):
        tx_code = call.data.replace("submit_utr_", "")
        user_states[user_id] = {"state": "awaiting_utr", "tx_code": tx_code}
        bot.send_message(call.message.chat.id, f"📸 *Send UTR Number*\n\n🧾 ID: `{tx_code}`\n\nSend the 12-digit UTR from your payment.", reply_markup=cancel_button(), parse_mode='Markdown')
        bot.answer_callback_query(call.id, "Send UTR now")
    elif call.data.startswith("adminverify_"):
        if str(user_id) != str(ADMIN_ID):
            bot.answer_callback_query(call.id, "Unauthorized!", show_alert=True)
            return
        tx_code = call.data.replace("adminverify_", "")
        # Manual verify for admin
        bot.answer_callback_query(call.id, "Manual verify - use /verify", show_alert=True)
    elif call.data.startswith("adminreject_"):
        if str(user_id) != str(ADMIN_ID):
            bot.answer_callback_query(call.id, "Unauthorized!", show_alert=True)
            return
        tx_code = call.data.replace("adminreject_", "")
        # Manual reject
        bot.answer_callback_query(call.id, "Use /reject TXCODE", show_alert=True)
    elif call.data in ["admin_add", "admin_remove", "admin_ban", "admin_unban"]:
        if str(user_id) != str(ADMIN_ID):
            return
        handle_admin_action(call)
    elif call.data == "admin_stats":
        if str(user_id) != str(ADMIN_ID):
            return
        show_admin_stats(call.message)
        bot.answer_callback_query(call.id)
    elif call.data == "admin_back":
        if str(user_id) != str(ADMIN_ID):
            return
        show_admin_panel(call.message)
        bot.answer_callback_query(call.id)

def handle_plan_selection(call, plan_id):
    user_id = call.from_user.id
    username = call.from_user.username or "no_username"
    plan = PLAN_CONFIG.get(plan_id)
    
    if not plan:
        bot.answer_callback_query(call.id, "Invalid plan.", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, "Sending QR...")
    send_payment_qr(call.message.chat.id, user_id, username, plan_id)

# ==================== ADMIN FUNCTIONS ====================
def show_admin_panel(message):
    stats = get_stats()
    msg = f"""🛠 *Admin Panel*

📊 *Stats:*
👥 Users: `{stats['total_users']}`
🔍 Searches: `{stats['total_searches']}`
💎 Credits: `{stats['total_credits']}`
💰 Revenue: ₹{stats['total_revenue']}
🚫 Banned: `{stats['banned_users']}`"""
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ ADD", callback_data="admin_add"),
        InlineKeyboardButton("➖ REMOVE", callback_data="admin_remove")
    )
    markup.add(
        InlineKeyboardButton("🚫 BAN", callback_data="admin_ban"),
        InlineKeyboardButton("✅ UNBAN", callback_data="admin_unban")
    )
    markup.add(InlineKeyboardButton("📊 STATS", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("🔙 BACK", callback_data="main_menu"))
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode='Markdown')

def show_admin_stats(message):
    stats = get_stats()
    msg = f"""📊 *Detailed Stats*

👥 Total Users: `{stats['total_users']}`
🔍 Total Searches: `{stats['total_searches']}`
💎 Total Credits: `{stats['total_credits']}`
💰 Total Revenue: ₹{stats['total_revenue']}
🚫 Banned Users: `{stats['banned_users']}`
📅 {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}"""
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 BACK", callback_data="admin_back"))
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode='Markdown')

def handle_admin_action(call):
    user_id = call.from_user.id
    
    if call.data == "admin_add":
        user_states[user_id] = {"state": "admin_add"}
        bot.send_message(call.message.chat.id, "➕ *Add Credits*\n\nFormat: `user_id credits`\n\nExample: `123456789 50`\n\nType /cancel to abort", parse_mode='Markdown')
    elif call.data == "admin_remove":
        user_states[user_id] = {"state": "admin_remove"}
        bot.send_message(call.message.chat.id, "➖ *Remove Credits*\n\nFormat: `user_id credits`\n\nExample: `123456789 10`\n\nType /cancel to abort", parse_mode='Markdown')
    elif call.data == "admin_ban":
        user_states[user_id] = {"state": "admin_ban"}
        bot.send_message(call.message.chat.id, "🚫 *Ban User*\n\nSend user ID:\n\nExample: `123456789`\n\nType /cancel to abort", parse_mode='Markdown')
    elif call.data == "admin_unban":
        user_states[user_id] = {"state": "admin_unban"}
        bot.send_message(call.message.chat.id, "✅ *Unban User*\n\nSend user ID:\n\nExample: `123456789`\n\nType /cancel to abort", parse_mode='Markdown')
    
    bot.answer_callback_query(call.id)

def process_admin_add(message):
    user_id = message.from_user.id
    if str(user_id) != str(ADMIN_ID):
        return
    user_states.pop(user_id, None)
    
    if message.text == "/cancel":
        bot.reply_to(message, "Cancelled", reply_markup=get_main_keyboard_for_user(user_id))
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            raise ValueError("Missing values")
        target_user = int(parts[0])
        credits = int(parts[1])
        new_total = add_credits(target_user, credits)
        bot.reply_to(message, f"✅ Added {credits} credits to `{target_user}`\nTotal: `{new_total}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid format!", parse_mode='Markdown')

def process_admin_remove(message):
    user_id = message.from_user.id
    if str(user_id) != str(ADMIN_ID):
        return
    user_states.pop(user_id, None)
    
    if message.text == "/cancel":
        bot.reply_to(message, "Cancelled", reply_markup=get_main_keyboard_for_user(user_id))
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            raise ValueError("Missing values")
        target_user = int(parts[0])
        credits = int(parts[1])
        
        user = get_user(target_user)
        if not user:
            bot.reply_to(message, "❌ User not found.", parse_mode='Markdown')
            return
        
        current = int(user.get('credits', 0) or 0)
        new_credits = max(0, current - credits)
        supabase.table("telegram_users").update({"credits": new_credits}).eq("telegram_user_id", target_user).execute()
        bot.reply_to(message, f"✅ Removed {credits} credits from `{target_user}`\nTotal: `{new_credits}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid format!", parse_mode='Markdown')

def process_admin_ban(message):
    user_id = message.from_user.id
    if str(user_id) != str(ADMIN_ID):
        return
    user_states.pop(user_id, None)
    
    if message.text == "/cancel":
        bot.reply_to(message, "Cancelled")
        return
    
    try:
        target_user = int(message.text.strip())
        ban_user(target_user)
        bot.reply_to(message, f"✅ Banned `{target_user}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid user ID!", parse_mode='Markdown')

def process_admin_unban(message):
    user_id = message.from_user.id
    if str(user_id) != str(ADMIN_ID):
        return
    user_states.pop(user_id, None)
    
    if message.text == "/cancel":
        bot.reply_to(message, "Cancelled")
        return
    
    try:
        target_user = int(message.text.strip())
        unban_user(target_user)
        bot.reply_to(message, f"✅ Unbanned `{target_user}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid user ID!", parse_mode='Markdown')

@bot.message_handler(commands=['verify'])
def verify_command(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /verify TXCODE")
            return
        tx_code = parts[1].strip()
        # Manual verify
        claim_resp = supabase.table("payment_claims").select("*").eq("payment_id", tx_code).limit(1).execute()
        if not claim_resp.data:
            bot.reply_to(message, "❌ Not found")
            return
        claim = claim_resp.data[0]
        if claim.get("status") == "success":
            bot.reply_to(message, "⚠️ Already verified")
            return
        ok, detail = fulfill_payment(claim)
        if ok:
            supabase.table("payment_claims").update({"status": "success"}).eq("id", claim.get("id")).execute()
            bot.reply_to(message, f"✅ {detail}")
        else:
            bot.reply_to(message, f"❌ {detail}")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ==================== FLASK ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "TraceX Bot v12.0.0 - Running!"

def keep_alive():
    def run():
        port = int(os.getenv("PORT", "8080"))
        app.run(host='0.0.0.0', port=port, use_reloader=False)
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()

# ==================== START ====================
if __name__ == "__main__":
    print("=" * 50)
    print(f"TraceX Lookup v{BOT_VERSION}")
    print(f"Admin: @{ADMIN_USERNAME}")
    print("=" * 50)
    print("📋 Services:")
    for key, svc in LOOKUP_SERVICES.items():
        print(f"   • {svc['emoji']} {svc['name']}")
    print(f"🎁 Free: {FREE_DAILY_LIMIT}/day")
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
    
    def signal_handler(sig, frame):
        print("\n🛑 Stopped")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    
    while True:
        try:
            bot.infinity_polling(timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
