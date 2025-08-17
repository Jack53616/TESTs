# -*- coding: utf-8 -*-
"""
Telegram bot (Render-ready) — Monthly subscription only + i18n + players + admin balance + search
- i18n: ar/en/tr/es/fr (covered for all used keys)
- Subscription: **monthly only**
- Admin: /genkey (monthly only), /gensub (monthly only or +days), /addbal, /takebal, /setbal, /players (with search), /pfind <id>, /delwebsite
- Help is localized and correct per role
- Users browser: /players with paging, per-user view, edit label/country, search by ID
- Stats localized (not hardcoded English)
- Withdraw approve/deny gated by admin
- JSON writes are atomic; DB fallback kept if provided
- Webhook via Flask with /healthz
"""
import os, json, logging, random, string, re, html as _html, tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from flask import Flask, request

import telebot
from telebot import types

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

# ---------- ENV ----------
API_TOKEN     = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL   = os.getenv("WEBHOOK_URL", "").rstrip("/")
ADMIN_ID      = int(os.getenv("ADMIN_ID", "1262317603"))
ADMIN_IDS    = {ADMIN_ID}
try:
    _ids_env = os.getenv("ADMIN_IDS", "").strip()
    if _ids_env:
        ADMIN_IDS |= {int(x) for x in _ids_env.replace(' ', '').split(',') if x}
except Exception:
    pass
DATABASE_URL  = os.getenv("DATABASE_URL", "").strip()
WEBSITE_URL   = os.getenv("WEBSITE_URL", "").strip()
PORT          = int(os.getenv("PORT", "10000"))

if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=True)
app = Flask(__name__)

# ---------- Storage Layer ----------
USE_DB = bool(DATABASE_URL)
if USE_DB:
    try:
        from db_kv import init_db, get_json as db_get_json, set_json as db_set_json
        init_db()
        log.info("DB storage enabled")
    except Exception as e:
        log.error("Failed to init DB storage, fallback to files: %s", e)
        USE_DB = False

DATA_FILES = {
    "settings": "settings.json",

    "users": "users.json",
    "withdraw_requests": "withdraw_requests.json",
    "withdraw_log": "withdraw_log.json",
    "trades": "trades.json",
    "stats": "stats.json",
    "keys": "keys.json",
}

SETTINGS_FILE = "settings.json"

def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically to avoid corruption."""
    d = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(d)
    os.replace(tmp, path)

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(data: dict) -> None:
    _atomic_write_json(SETTINGS_FILE, data)

def get_website_url() -> str:
    s = load_settings()
    return s.get("WEBSITE_URL") or WEBSITE_URL

def load_json(name: str) -> Any:
    key = name
    if USE_DB:
        try:
            return db_get_json(key)
        except Exception as e:
            log.error("DB get_json error for key %s: %s", key, e)
    path = DATA_FILES.get(name.replace(".json",""), name)
    if not path.endswith(".json"):
        path = name
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_json(name: str, data: Any) -> None:
    key = name
    if USE_DB:
        try:
            db_set_json(key, data)
            return
        except Exception as e:
            log.error("DB set_json error for key %s: %s", key, e)
    path = DATA_FILES.get(name.replace(".json",""), name)
    if not path.endswith(".json"):
        path = name
    _atomic_write_json(path, data)

def _now() -> datetime:
    return datetime.now()

def _now_str() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")

def load_daily_text_for(uid: str) -> str:
    """Return per-user daily if exists, else global daily file/json."""
    users = load_json("users.json") or {}
    u = users.get(uid, {})
    if isinstance(u, dict) and u.get("daily"):
        return str(u.get("daily", "")).strip()
    # global file
    if os.path.exists("daily_trade.txt"):
        try:
            return open("daily_trade.txt", "r", encoding="utf-8").read().strip()
        except Exception:
            pass
    trades = load_json("trades.json") or {}
    return (trades or {}).get("daily", "")

def save_daily_text(text: str) -> None:
    with open("daily_trade.txt", "w", encoding="utf-8") as f:
        f.write((text or "").strip())

# ---------- Subscription Keys (Monthly only) ----------
DURATIONS = {
    "monthly": 30
}

def _key_store() -> Dict[str, Any]:
    return load_json("keys.json") or {}

def _save_keys(data: Dict[str, Any]) -> None:
    save_json("keys.json", data)

def is_sub_active(uid: str) -> bool:
    users = load_json("users.json") or {}
    sub = (users.get(uid, {}) or {}).get("sub")
    if not sub: return False
    exp = sub.get("expire_at")
    if exp is None:  # shouldn't happen with monthly-only, but allow
        return True
    try:
        return datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") > _now()
    except Exception:
        return False

def sub_remaining_str(uid: str) -> str:
    """Return remaining time string: 3d 4h 12m 05s / 0s."""
    users = load_json("users.json") or {}
    sub = (users.get(uid, {}) or {}).get("sub")
    if not sub:
        return "0s"
    exp = sub.get("expire_at")
    if exp is None:
        return "∞"
    try:
        exp_dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return "0s"
    delta = exp_dt - _now()
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "0s"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s  = divmod(rem, 60)
    parts: List[str] = []
    if d: parts.append(f"{d}d")
    if h or d: parts.append(f"{h}h")
    if m or h or d: parts.append(f"{m}m")
    parts.append(f"{s:02d}s")
    return " ".join(parts)

def build_lang_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🇸🇦 العربية", callback_data="set_lang_ar"),
           types.InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en"))
    kb.add(types.InlineKeyboardButton("🇹🇷 Türkçe", callback_data="set_lang_tr"),
           types.InlineKeyboardButton("🇪🇸 Español", callback_data="set_lang_es"))
    kb.add(types.InlineKeyboardButton("🇫🇷 Français", callback_data="set_lang_fr"))
    return kb

# ---------- i18n ----------
LANGS = ["ar", "en", "tr", "es", "fr"]
TEXT: Dict[str, Dict[str, Any]] = {
    "ar": {
        "welcome": "👋 أهلاً بك في بوت التداول\n\n💰 رصيدك: {balance}$\n⏳ ينتهي الاشتراك بعد: {remain}\n🆔 آيديك: {user_id}",
        "need_key": "🔑 الرجاء إدخال مفتاح الاشتراك لتفعيل البوت.\nالنوع المتاح: شهري فقط",
        "key_ok": "✅ تم تفعيل اشتراكك (شهري). ينتهي في: {exp}\nاستخدم /start لفتح القائمة.",
        "key_ok_life": "✅ تم التفعيل.\nاستخدم /start لفتح القائمة.",
        "key_invalid": "❌ مفتاح غير صالح أو مستخدم مسبقاً. حاول مرة أخرى.",
        "key_expired": "⛔ انتهى اشتراكك. الرجاء إدخال مفتاح جديد (شهري).",
        "btn_daily": "📈 صفقة اليوم",
        "btn_withdraw": "💸 سحب",
        "btn_wstatus": "💼 معاملات السحب",
        "btn_stats": "📊 الإحصائيات",
        "btn_lang": "🌐 اللغة",
        "btn_deposit": "💳 الإيداع",
        "btn_website": "🌍 موقعنا",
        "btn_support": "📞 تواصل مع الدعم",
        "btn_buy": "🛒 شراء اشتراك",
        "help_title": "🛠 الأوامر المتاحة:",
        "help_public": [
            "/start - القائمة الرئيسية",
            "/help - عرض المساعدة",
            "/id - آيديك",
            "/balance - رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw - السحب",
            "/mystats - إحصائياتي",
            "/players - قائمة اللاعبين",
            "/pfind <user_id> - فتح لاعب مباشرة"
        ],
        "help_admin": [
            "/genkey monthly [count] - توليد مفاتيح (شهري فقط)",
            "/gensub <user_id> monthly | +days <n> - منح/تمديد اشتراك",
            "/setwebsite <URL> - ضبط رابط الموقع",
            "/delwebsite - حذف رابط الموقع",
            "/addbal <user_id> <amount> - زيادة رصيد",
            "/takebal <user_id> <amount> - تنزيل رصيد",
            "/setbal <user_id> <amount> - ضبط الرصيد",
            "/setdaily <user_id> - ضبط صفقة اليوم للمستخدم",
            "/cleardaily <user_id> - مسح صفقة اليوم للمستخدم"
        ],
        "daily_none": "لا يوجد صفقة اليوم حالياً.",
        "cleardaily_ok": "🧹 تم مسح صفقة اليوم.",
        "withdraw_enter": "❌ الصيغة: /withdraw 50",
        "withdraw_invalid": "❌ مبلغ غير صالح.",
        "withdraw_insufficient": "الرصيد غير كافٍ. رصيدك: {bal}$",
        "withdraw_created": "✅ تم إنشاء طلب سحب #{req_id} بقيمة {amount}$.",
        "lang_menu_title": "اختر لغتك:",
        "lang_saved": "✅ تم ضبط اللغة العربية.",
        "lang_updated_to": "✅ تم تحديث اللغة.",
        "choose_withdraw_amount": "اختر مبلغ السحب:",
        "requests_waiting": "طلباتك قيد الانتظار:",
        "no_requests": "لا توجد طلبات قيد الانتظار.",
        # deposit
        "deposit_choose": "اختر طريقة الإيداع:",
        "deposit_cash": "💵 كاش",
        "deposit_paypal": "🅿️ باي بال",
        "deposit_bank": "🏦 تحويل بنكي",
        "deposit_mc": "💳 ماستركارد",
        "deposit_visa": "💳 فيزا",
        "deposit_msg": "لإتمام الدفع عبر {method}، يرجى التواصل مباشرة معنا. اضغط الزر أدناه:",
        "contact_us": "📩 تواصل معنا",
        # website & support
        "website_msg": "🔥 زر لزيارة موقعنا:",
        "website_not_set": "ℹ️ لم يتم ضبط رابط الموقع بعد.",
        "support_msg": "للتواصل مع الدعم اضغط الزر:",
        "delwebsite_ok": "🗑️ تم حذف رابط الموقع.",
        # stats i18n
        "stats_title": "📊 إحصائياتك",
        "stats_wins": "✅ الأرباح: {sum}$ (عدد: {count})",
        "stats_losses": "❌ الخسائر: {sum}$ (عدد: {count})",
        "stats_net": "⚖️ الصافي: {net}$",
        "stats_no_data": "لا توجد عمليات حتى الآن.",
        "stats_line_win": "{at} — ربح +{amount}$",
        "stats_line_loss": "{at} — خسارة -{amount}$",
        # admin replies
        "admin_only": "⚠️ هذا الأمر للأدمن فقط.",
        "genkey_ok": "✅ تم توليد {n} مفتاح (شهري).\nأول مفتاح:\n<code>{first}</code>",
        "delkey_ok": "🗑️ تم حذف المفتاح.",
        "delkey_not_found": "❌ المفتاح غير موجود.",
        "delsub_ok": "🗑️ تم حذف اشتراك المستخدم {uid}.",
        "delsub_not_found": "ℹ️ لا يوجد اشتراك محفوظ لهذا المستخدم.",
        "subinfo_none": "ℹ️ لا يوجد اشتراك.",
        "subinfo_line": "📄 النوع: {t}\n🕒 الانتهاء: {exp}",
        "setwebsite_ok": "✅ تم ضبط رابط الموقع.",
        "setwebsite_usage": "الصيغة: /setwebsite <URL>",
        "gensub_ok": "✅ تم ضبط اشتراك المستخدم {uid}: {t} حتى {exp}.",
        "gensub_usage": "الصيغة: /gensub <user_id> monthly | +days <n>",
        # withdraw admin
        "admin_w_title": "🧾 طلبات السحب (قيد الانتظار)",
        "admin_w_none": "لا يوجد طلبات بانتظار الموافقة.",
        "admin_w_item": "#{id} — المستخدم {uid} — {amount}$ — {at}",
        "admin_w_approve": "✅ تمت الموافقة على طلب #{id}.",
        "admin_w_denied": "❌ تم رفض طلب #{id} وتمت إعادة المبلغ.",
        # buttons common
        "approve_btn": "✅ موافقة",
        "deny_btn": "❌ رفض",
        "prev_btn": "⬅️ السابق",
        "next_btn": "التالي ➡️",
        "back_btn": "🔙 رجوع",
        # players module
        "players_title": "قائمة اللاعبين:",
        "players_empty": "لا يوجد مستخدمون بعد.",
        "players_page": "صفحة {cur}/{total}",
        "players_search_btn": "🔎 بحث بالآيدي",
        "players_search_prompt": "أرسل آيدي اللاعب أو '-' للإلغاء.",
        "players_search_not_found": "الآيدي غير موجود. جرّب رقمًا آخر.",
        "players_item_fmt": "{id} — {label}",
        "player_view_title": "👤 المستخدم {id} — {label}",
        "player_balance": "💰 الرصيد: {bal}$",
        "player_stats": "📊 الإحصائيات: win={win}$ | loss={loss}$ | net={net}$",
        "player_country": "🗺️ البلد: {country}",
        "player_sub": "⏳ اشتراك: {remain}",
        "edit_label_btn": "✏️ الاسم",
        "edit_country_btn": "🌍 البلد",
        "label_prompt": "أرسل الاسم الجديد للمستخدم {uid}. اكتب '-' لإزالة الاسم.",
        "label_set_ok": "تم ضبط الاسم: {uid} — {label}",
        "label_removed": "تم إزالة الاسم للمستخدم {uid}.",
        "country_prompt": "أرسل اسم البلد للمستخدم {uid}. اكتب '-' لإزالة البلد.",
        "country_set_ok": "تم ضبط البلد للمستخدم {uid}: {country}",
        "country_removed": "تم إزالة البلد للمستخدم {uid}.",
        # balances
        "usage_addbal": "الصيغة: /addbal <user_id> <amount>",
        "usage_takebal": "الصيغة: /takebal <user_id> <amount>",
        "usage_setbal": "الصيغة: /setbal <user_id> <amount>",
        "user_not_found": "المستخدم غير موجود.",
        "invalid_amount": "مبلغ غير صالح.",
        "bal_added_ok": "✅ تمت إضافة {amount}$ للمستخدم {uid}. الرصيد الجديد: {bal}$",
        "bal_taken_ok": "✅ تم خصم {amount}$ من المستخدم {uid}. الرصيد الجديد: {bal}$",
        "bal_set_ok": "✅ تم ضبط رصيد المستخدم {uid} إلى {bal}$",
        "balance_linked_msg": "✅ تم ربط البوت بحسابك التداول ورصيدك {bal}$"
    },
    "en": {
        "welcome": "👋 Welcome to the trading bot\n\n💰 Your balance: {balance}$\n⏳ Subscription ends in: {remain}\n🆔 Your ID: {user_id}",
        "need_key": "🔑 Please enter your subscription key to activate the bot.\nAvailable type: monthly only",
        "key_ok": "✅ Your subscription (monthly) is activated. Expires at: {exp}\nUse /start to open the menu.",
        "key_ok_life": "✅ Activated.\nUse /start to open the menu.",
        "key_invalid": "❌ Invalid or already used key. Try again.",
        "key_expired": "⛔ Your subscription has expired. Please enter a new (monthly) key.",
        "btn_daily": "📈 Daily trade",
        "btn_withdraw": "💸 Withdraw",
        "btn_wstatus": "💼 Withdrawal requests",
        "btn_stats": "📊 Stats",
        "btn_lang": "🌐 Language",
        "btn_deposit": "💳 Deposit",
        "btn_website": "🌍 Website",
        "btn_support": "📞 Contact support",
        "btn_buy": "🛒 Buy subscription",
        "help_title": "🛠 Available commands:",
        "help_public": [
            "/start - Main menu",
            "/help - Show help",
            "/id - Show your ID",
            "/balance - Your balance",
            "/daily - Daily trade",
            "/withdraw - Withdraw",
            "/mystats - My stats",
            "/players - Players list",
            "/pfind <user_id> - Open a player directly"
        ],
        "help_admin": [
            "/genkey monthly [count] - generate keys (monthly only)",
            "/gensub <user_id> monthly | +days <n> - grant/extend subscription",
            "/setwebsite <URL> - set website URL",
            "/delwebsite - delete website URL",
            "/addbal <user_id> <amount> - add balance",
            "/takebal <user_id> <amount> - take balance",
            "/setbal <user_id> <amount> - set balance",
            "/setdaily <user_id> - set user's daily",
            "/cleardaily <user_id> - clear user's daily"
        ],
        "daily_none": "No daily trade yet.",
        "cleardaily_ok": "🧹 Daily trade cleared.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Invalid amount.",
        "withdraw_insufficient": "Insufficient balance. Your balance: {bal}$",
        "withdraw_created": "✅ Withdrawal request #{req_id} created for {amount}$.",
        "lang_menu_title": "Choose your language:",
        "lang_saved": "✅ Language set to English.",
        "lang_updated_to": "✅ Language updated.",
        "choose_withdraw_amount": "Choose withdraw amount:",
        "requests_waiting": "Your pending requests:",
        "no_requests": "No pending requests.",
        "deposit_choose": "Choose a deposit method:",
        "deposit_cash": "💵 Cash",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Bank Transfer",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "To complete payment via {method}, please contact us directly. Tap below:",
        "contact_us": "📩 Contact us",
        "website_msg": "🔥 Tap to visit our website:",
        "website_not_set": "ℹ️ Website URL is not set yet.",
        "support_msg": "Tap below to contact support:",
        "delwebsite_ok": "🗑️ Website URL removed.",
        "stats_title": "📊 Your statistics",
        "stats_wins": "✅ Wins: {sum}$ (count: {count})",
        "stats_losses": "❌ Losses: {sum}$ (count: {count})",
        "stats_net": "⚖️ Net: {net}$",
        "stats_no_data": "No operations yet.",
        "stats_line_win": "{at} — Win +{amount}$",
        "stats_line_loss": "{at} — Loss -{amount}$",
        "admin_only": "⚠️ Admins only.",
        "genkey_ok": "✅ Generated {n} key(s) (monthly).\nFirst key:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Key deleted.",
        "delkey_not_found": "❌ Key not found.",
        "delsub_ok": "🗑️ Subscription removed for user {uid}.",
        "delsub_not_found": "ℹ️ No subscription recorded for this user.",
        "subinfo_none": "ℹ️ No subscription.",
        "subinfo_line": "📄 Type: {t}\n🕒 Expires: {exp}",
        "setwebsite_ok": "✅ Website URL saved.",
        "setwebsite_usage": "Usage: /setwebsite <URL>",
        "gensub_ok": "✅ Subscription set for {uid}: {t} until {exp}.",
        "gensub_usage": "Usage: /gensub <user_id> monthly | +days <n>",
        "admin_w_title": "🧾 Pending withdrawal requests",
        "admin_w_none": "No pending requests.",
        "admin_w_item": "#{id} — user {uid} — {amount}$ — {at}",
        "admin_w_approve": "✅ Request #{id} approved.",
        "admin_w_denied": "❌ Request #{id} denied and amount returned.",
        "approve_btn": "✅ Approve",
        "deny_btn": "❌ Deny",
        "prev_btn": "⬅️ Prev",
        "next_btn": "Next ➡️",
        "back_btn": "🔙 Back",
        "players_title": "Players list:",
        "players_empty": "No users yet.",
        "players_page": "Page {cur}/{total}",
        "players_search_btn": "🔎 Search by ID",
        "players_search_prompt": "Send the player ID, or '-' to cancel.",
        "players_search_not_found": "ID not found. Try another.",
        "players_item_fmt": "{id} — {label}",
        "player_view_title": "👤 User {id} — {label}",
        "player_balance": "💰 Balance: {bal}$",
        "player_stats": "📊 Stats: win={win}$ | loss={loss}$ | net={net}$",
        "player_country": "🗺️ Country: {country}",
        "player_sub": "⏳ Subscription: {remain}",
        "edit_label_btn": "✏️ Label",
        "edit_country_btn": "🌍 Country",
        "label_prompt": "Send new label for user {uid}. Send '-' to remove.",
        "label_set_ok": "Label set: {uid} — {label}",
        "label_removed": "Label removed for user {uid}.",
        "country_prompt": "Send country for user {uid}. Send '-' to remove.",
        "country_set_ok": "Country set for user {uid}: {country}",
        "country_removed": "Country removed for user {uid}.",
        "usage_addbal": "Usage: /addbal <user_id> <amount>",
        "usage_takebal": "Usage: /takebal <user_id> <amount>",
        "usage_setbal": "Usage: /setbal <user_id> <amount>",
        "user_not_found": "User not found.",
        "invalid_amount": "Invalid amount.",
        "bal_added_ok": "✅ Added {amount}$ to {uid}. New balance: {bal}$",
        "bal_taken_ok": "✅ Taken {amount}$ from {uid}. New balance: {bal}$",
        "bal_set_ok": "✅ Balance set to {bal}$ for {uid}",
        "balance_linked_msg": "✅ Your bot is linked to your trading account. Balance: {bal}$"
    },
    "tr": {
        "welcome": "👋 Trading botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n⏳ Abonelik bitimine: {remain}\n🆔 ID: {user_id}",
        "need_key": "🔑 Botu etkinleştirmek için abonelik anahtarını gir.\nMevcut tür: sadece aylık",
        "key_ok": "✅ Aboneliğin (aylık) aktif. Bitiş: {exp}\nMenü için /start.",
        "key_ok_life": "✅ Etkinleştirildi.\nMenü için /start.",
        "key_invalid": "❌ Geçersiz ya da kullanılmış anahtar. Tekrar dene.",
        "key_expired": "⛔ Aboneliğin bitti. Yeni (aylık) anahtar gir.",
        "btn_daily": "📈 Günün işlemi",
        "btn_withdraw": "💸 Çekim",
        "btn_wstatus": "💼 Çekim talepleri",
        "btn_stats": "📊 İstatistikler",
        "btn_lang": "🌐 Dil",
        "btn_deposit": "💳 Yatırma",
        "btn_website": "🌍 Web sitemiz",
        "btn_support": "📞 Destek",
        "btn_buy": "🛒 Abonelik satın al",
        "help_title": "🛠 Komutlar:",
        "help_public": [
            "/start - Ana menü",
            "/help - Yardım",
            "/id - ID'n",
            "/balance - Bakiye",
            "/daily - Günün işlemi",
            "/withdraw - Çekim",
            "/mystats - İstatistiklerim",
            "/players - Oyuncu listesi",
            "/pfind <user_id> - Oyuncuyu aç"
        ],
        "help_admin": [
            "/genkey monthly [count] - anahtar üret (sadece aylık)",
            "/gensub <user_id> monthly | +days <n> - abonelik ver/uzat",
            "/setwebsite <URL> - web sitesi ayarla",
            "/delwebsite - web sitesini sil",
            "/addbal <user_id> <amount> - bakiye ekle",
            "/takebal <user_id> <amount> - bakiye düş",
            "/setbal <user_id> <amount> - bakiyeyi ayarla",
            "/setdaily <user_id> - kullanıcının günlük işlemi",
            "/cleardaily <user_id> - günlük işlemi sil"
        ],
        "daily_none": "Henüz günlük işlem yok.",
        "cleardaily_ok": "🧹 Günlük işlem temizlendi.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Geçersiz tutar.",
        "withdraw_insufficient": "Yetersiz bakiye. Bakiyen: {bal}$",
        "withdraw_created": "✅ #{req_id} numaralı çekim talebi {amount}$ için oluşturuldu.",
        "lang_menu_title": "Dilini seç:",
        "lang_saved": "✅ Dil Türkçe olarak ayarlandı.",
        "lang_updated_to": "✅ Dil güncellendi.",
        "choose_withdraw_amount": "Çekim tutarını seç:",
        "requests_waiting": "Bekleyen taleplerin:",
        "no_requests": "Bekleyen talep yok.",
        "deposit_choose": "Bir yatırma yöntemi seç:",
        "deposit_cash": "💵 Nakit",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Havale",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "{method} ile ödeme için lütfen doğrudan bizimle iletişime geçin.",
        "contact_us": "📩 Bizimle iletişim",
        "website_msg": "🔥 Web sitemizi ziyaret etmek için:",
        "website_not_set": "ℹ️ Website URL henüz ayarlı değil.",
        "support_msg": "Destek için aşağı dokun:",
        "delwebsite_ok": "🗑️ Web sitesi bağlantısı silindi.",
        "stats_title": "📊 İstatistiklerin",
        "stats_wins": "✅ Kazançlar: {sum}$ (adet: {count})",
        "stats_losses": "❌ Kayıplar: {sum}$ (adet: {count})",
        "stats_net": "⚖️ Net: {net}$",
        "stats_no_data": "Henüz işlem yok.",
        "stats_line_win": "{at} — Kazanç +{amount}$",
        "stats_line_loss": "{at} — Kayıp -{amount}$",
        "admin_only": "⚠️ Sadece admin.",
        "genkey_ok": "✅ {n} anahtar üretildi (aylık).\nİlk anahtar:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Anahtar silindi.",
        "delkey_not_found": "❌ Anahtar bulunamadı.",
        "delsub_ok": "🗑️ {uid} kullanıcısının aboneliği silindi.",
        "delsub_not_found": "ℹ️ Bu kullanıcı için abonelik bulunmuyor.",
        "subinfo_none": "ℹ️ Abonelik yok.",
        "subinfo_line": "📄 Tür: {t}\n🕒 Bitiş: {exp}",
        "setwebsite_ok": "✅ Website kaydedildi.",
        "setwebsite_usage": "Kullanım: /setwebsite <URL>",
        "gensub_ok": "✅ {uid} için abonelik ayarlandı: {t} — {exp}.",
        "gensub_usage": "Kullanım: /gensub <user_id> monthly | +days <n>",
        "admin_w_title": "🧾 Bekleyen çekim talepleri",
        "admin_w_none": "Bekleyen talep yok.",
        "admin_w_item": "#{id} — kullanıcı {uid} — {amount}$ — {at}",
        "admin_w_approve": "✅ #{id} talebi onaylandı.",
        "admin_w_denied": "❌ #{id} talebi reddedildi ve tutar iade edildi.",
        "approve_btn": "✅ Onayla",
        "deny_btn": "❌ Reddet",
        "prev_btn": "⬅️ Önceki",
        "next_btn": "Sonraki ➡️",
        "back_btn": "🔙 Geri",
        "players_title": "Oyuncu listesi:",
        "players_empty": "Henüz kullanıcı yok.",
        "players_page": "Sayfa {cur}/{total}",
        "players_search_btn": "🔎 ID ile ara",
        "players_search_prompt": "Oyuncu ID'si gönder veya '-' ile iptal.",
        "players_search_not_found": "ID bulunamadı. Başka bir tane dene.",
        "players_item_fmt": "{id} — {label}",
        "player_view_title": "👤 Kullanıcı {id} — {label}",
        "player_balance": "💰 Bakiye: {bal}$",
        "player_stats": "📊 İstatistik: win={win}$ | loss={loss}$ | net={net}$",
        "player_country": "🗺️ Ülke: {country}",
        "player_sub": "⏳ Abonelik: {remain}",
        "edit_label_btn": "✏️ İsim",
        "edit_country_btn": "🌍 Ülke",
        "label_prompt": "{uid} için yeni isim gönder. Kaldırmak için '-' gönder.",
        "label_set_ok": "İsim ayarlandı: {uid} — {label}",
        "label_removed": "{uid} için isim kaldırıldı.",
        "country_prompt": "{uid} için ülke gönder. Kaldırmak için '-' gönder.",
        "country_set_ok": "{uid} için ülke ayarlandı: {country}",
        "country_removed": "{uid} için ülke kaldırıldı.",
        "usage_addbal": "Kullanım: /addbal <user_id> <amount>",
        "usage_takebal": "Kullanım: /takebal <user_id> <amount>",
        "usage_setbal": "Kullanım: /setbal <user_id> <amount>",
        "user_not_found": "Kullanıcı bulunamadı.",
        "invalid_amount": "Geçersiz tutar.",
        "bal_added_ok": "✅ {uid} kullanıcısına {amount}$ eklendi. Yeni bakiye: {bal}$",
        "bal_taken_ok": "✅ {uid} kullanıcısından {amount}$ düşüldü. Yeni bakiye: {bal}$",
        "bal_set_ok": "✅ {uid} için bakiye {bal}$ olarak ayarlandı",
        "balance_linked_msg": "✅ Bot hesabınla eşlendi. Bakiyen: {bal}$"
    },
    "es": {
        "welcome": "👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n⏳ La suscripción termina en: {remain}\n🆔 Tu ID: {user_id}",
        "need_key": "🔑 Ingresa tu clave de suscripción para activar el bot.\nTipo disponible: solo mensual",
        "key_ok": "✅ Tu suscripción (mensual) está activa. Expira: {exp}\nUsa /start para abrir el menú.",
        "key_ok_life": "✅ Activado.\nUsa /start para abrir el menú.",
        "key_invalid": "❌ Clave inválida o ya usada. Intenta de nuevo.",
        "key_expired": "⛔ Tu suscripción expiró. Ingresa una nueva clave (mensual).",
        "btn_daily": "📈 Operación del día",
        "btn_withdraw": "💸 Retirar",
        "btn_wstatus": "💼 Solicitudes de retiro",
        "btn_stats": "📊 Estadísticas",
        "btn_lang": "🌐 Idioma",
        "btn_deposit": "💳 Depósito",
        "btn_website": "🌍 Sitio web",
        "btn_support": "📞 Contactar soporte",
        "btn_buy": "🛒 Comprar suscripción",
        "help_title": "🛠 Comandos:",
        "help_public": [
            "/start - Menú principal",
            "/help - Ayuda",
            "/id - Tu ID",
            "/balance - Tu saldo",
            "/daily - Operación del día",
            "/withdraw - Retiro",
            "/mystats - Mis estadísticas",
            "/players - Lista de usuarios",
            "/pfind <user_id> - Abrir usuario"
        ],
        "help_admin": [
            "/genkey monthly [count] - generar claves (solo mensual)",
            "/gensub <user_id> monthly | +days <n> - otorgar/extender suscripción",
            "/setwebsite <URL> - guardar sitio web",
            "/delwebsite - eliminar sitio web",
            "/addbal <user_id> <amount> - agregar saldo",
            "/takebal <user_id> <amount> - quitar saldo",
            "/setbal <user_id> <amount> - fijar saldo",
            "/setdaily <user_id> - fijar operación diaria",
            "/cleardaily <user_id> - borrar operación diaria"
        ],
        "daily_none": "Aún no hay operación del día.",
        "cleardaily_ok": "🧹 Operación del día eliminada.",
        "withdraw_enter": "❌ Formato: /withdraw 50",
        "withdraw_invalid": "❌ Monto inválido.",
        "withdraw_insufficient": "Saldo insuficiente. Tu saldo: {bal}$",
        "withdraw_created": "✅ Solicitud #{req_id} creada por {amount}$.",
        "lang_menu_title": "Elige tu idioma:",
        "lang_saved": "✅ Idioma configurado a español.",
        "lang_updated_to": "✅ Idioma actualizado.",
        "choose_withdraw_amount": "Elige el monto a retirar:",
        "requests_waiting": "Tus solicitudes pendientes:",
        "no_requests": "No hay solicitudes pendientes.",
        "deposit_choose": "Elige un método de depósito:",
        "deposit_cash": "💵 Efectivo",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Transferencia bancaria",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "Para pagar con {method}, contáctanos directamente.",
        "contact_us": "📩 Contáctanos",
        "website_msg": "🔥 Visita nuestro sitio:",
        "website_not_set": "ℹ️ La URL del sitio no está configurada.",
        "support_msg": "Pulsa abajo para contactar soporte:",
        "delwebsite_ok": "🗑️ URL del sitio eliminada.",
        "stats_title": "📊 Tus estadísticas",
        "stats_wins": "✅ Ganancias: {sum}$ (conteo: {count})",
        "stats_losses": "❌ Pérdidas: {sum}$ (conteo: {count})",
        "stats_net": "⚖️ Neto: {net}$",
        "stats_no_data": "Aún no hay operaciones.",
        "stats_line_win": "{at} — Ganancia +{amount}$",
        "stats_line_loss": "{at} — Pérdida -{amount}$",
        "admin_only": "⚠️ Solo administradores.",
        "genkey_ok": "✅ {n} clave(s) generadas (mensual).\nPrimera clave:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Clave eliminada.",
        "delkey_not_found": "❌ Clave no encontrada.",
        "delsub_ok": "🗑️ Suscripción eliminada para el usuario {uid}.",
        "delsub_not_found": "ℹ️ No hay suscripción registrada.",
        "subinfo_none": "ℹ️ Sin suscripción.",
        "subinfo_line": "📄 Tipo: {t}\n🕒 Expira: {exp}",
        "setwebsite_ok": "✅ URL del sitio guardada.",
        "setwebsite_usage": "Uso: /setwebsite <URL>",
        "gensub_ok": "✅ Suscripción para {uid}: {t} hasta {exp}.",
        "gensub_usage": "Uso: /gensub <user_id> monthly | +days <n>",
        "admin_w_title": "🧾 Solicitudes de retiro pendientes",
        "admin_w_none": "No hay solicitudes pendientes.",
        "admin_w_item": "#{id} — usuario {uid} — {amount}$ — {at}",
        "admin_w_approve": "✅ Solicitud #{id} aprobada.",
        "admin_w_denied": "❌ Solicitud #{id} rechazada y monto devuelto.",
        "approve_btn": "✅ Aprobar",
        "deny_btn": "❌ Rechazar",
        "prev_btn": "⬅️ Anterior",
        "next_btn": "Siguiente ➡️",
        "back_btn": "🔙 Atrás",
        "players_title": "Lista de usuarios:",
        "players_empty": "Aún no hay usuarios.",
        "players_page": "Página {cur}/{total}",
        "players_search_btn": "🔎 Buscar por ID",
        "players_search_prompt": "Envía el ID del usuario o '-' para cancelar.",
        "players_search_not_found": "ID no encontrado. Prueba otro.",
        "players_item_fmt": "{id} — {label}",
        "player_view_title": "👤 Usuario {id} — {label}",
        "player_balance": "💰 Saldo: {bal}$",
        "player_stats": "📊 Estadísticas: win={win}$ | loss={loss}$ | net={net}$",
        "player_country": "🗺️ País: {country}",
        "player_sub": "⏳ Suscripción: {remain}",
        "edit_label_btn": "✏️ Nombre",
        "edit_country_btn": "🌍 País",
        "label_prompt": "Envía el nombre para {uid}. '-' para eliminar.",
        "label_set_ok": "Nombre guardado: {uid} — {label}",
        "label_removed": "Nombre eliminado para {uid}.",
        "country_prompt": "Envía el país para {uid}. '-' para eliminar.",
        "country_set_ok": "País guardado para {uid}: {country}",
        "country_removed": "País eliminado para {uid}.",
        "usage_addbal": "Uso: /addbal <user_id> <amount>",
        "usage_takebal": "Uso: /takebal <user_id> <amount>",
        "usage_setbal": "Uso: /setbal <user_id> <amount>",
        "user_not_found": "Usuario no encontrado.",
        "invalid_amount": "Monto inválido.",
        "bal_added_ok": "✅ Agregado {amount}$ a {uid}. Nuevo saldo: {bal}$",
        "bal_taken_ok": "✅ Quitado {amount}$ de {uid}. Nuevo saldo: {bal}$",
        "bal_set_ok": "✅ Saldo fijado en {bal}$ para {uid}",
        "balance_linked_msg": "✅ Bot vinculado a tu cuenta de trading. Saldo: {bal}$"
    },
    "fr": {
        "welcome": "👋 Bienvenue dans le bot de trading\n\n💰 Votre solde : {balance}$\n⏳ L’abonnement se termine dans : {remain}\n🆔 Votre ID : {user_id}",
        "need_key": "🔑 Saisissez votre clé d’abonnement pour activer le bot.\nType disponible : mensuel uniquement",
        "key_ok": "✅ Votre abonnement (mensuel) est activé. Expire : {exp}\nUtilisez /start pour ouvrir le menu.",
        "key_ok_life": "✅ Activé.\nUtilisez /start pour ouvrir le menu.",
        "key_invalid": "❌ Clé invalide ou déjà utilisée. Réessayez.",
        "key_expired": "⛔ Votre abonnement a expiré. Veuillez saisir une nouvelle clé (mensuelle).",
        "btn_daily": "📈 Trade du jour",
        "btn_withdraw": "💸 Retrait",
        "btn_wstatus": "💼 Demandes de retrait",
        "btn_stats": "📊 Statistiques",
        "btn_lang": "🌐 Langue",
        "btn_deposit": "💳 Dépôt",
        "btn_website": "🌍 Site web",
        "btn_support": "📞 Support",
        "btn_buy": "🛒 Acheter un abonnement",
        "help_title": "🛠 Commandes :",
        "help_public": [
            "/start - Menu principal",
            "/help - Aide",
            "/id - Votre ID",
            "/balance - Votre solde",
            "/daily - Trade du jour",
            "/withdraw - Retrait",
            "/mystats - Mes statistiques",
            "/players - Liste des utilisateurs",
            "/pfind <user_id> - Ouvrir un utilisateur"
        ],
        "help_admin": [
            "/genkey monthly [count] - générer des clés (mensuel uniquement)",
            "/gensub <user_id> monthly | +days <n> - accorder/prolonger l’abonnement",
            "/setwebsite <URL> - définir l’URL du site",
            "/delwebsite - supprimer l’URL du site",
            "/addbal <user_id> <amount> - ajouter du solde",
            "/takebal <user_id> <amount> - retirer du solde",
            "/setbal <user_id> <amount> - définir le solde",
            "/setdaily <user_id> - définir le trade du jour (utilisateur)",
            "/cleardaily <user_id> - effacer le trade du jour (utilisateur)"
        ],
        "daily_none": "Aucun trade du jour pour le moment.",
        "cleardaily_ok": "🧹 Trade du jour effacé.",
        "withdraw_enter": "❌ Format : /withdraw 50",
        "withdraw_invalid": "❌ Montant invalide.",
        "withdraw_insufficient": "Solde insuffisant. Votre solde : {bal}$",
        "withdraw_created": "✅ Demande #{req_id} créée pour {amount}$.",
        "lang_menu_title": "Sélectionnez votre langue :",
        "lang_saved": "✅ Langue définie sur le français.",
        "lang_updated_to": "✅ Langue mise à jour.",
        "choose_withdraw_amount": "Choisissez le montant du retrait :",
        "requests_waiting": "Vos demandes en attente :",
        "no_requests": "Aucune demande en attente.",
        "deposit_choose": "Choisissez une méthode de dépôt :",
        "deposit_cash": "💵 Espèces",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Virement bancaire",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "Pour payer via {method}, contactez-nous directement.",
        "contact_us": "📩 Nous contacter",
        "website_msg": "🔥 Visitez notre site :",
        "website_not_set": "ℹ️ L’URL du site n’est pas encore définie.",
        "support_msg": "Appuyez ci-dessous pour contacter le support :",
        "delwebsite_ok": "🗑️ URL du site supprimée.",
        "stats_title": "📊 Vos statistiques",
        "stats_wins": "✅ Gains : {sum}$ (nombre : {count})",
        "stats_losses": "❌ Pertes : {sum}$ (nombre : {count})",
        "stats_net": "⚖️ Net : {net}$",
        "stats_no_data": "Aucune opération pour le moment.",
        "stats_line_win": "{at} — Gain +{amount}$",
        "stats_line_loss": "{at} — Perte -{amount}$",
        "admin_only": "⚠️ Réservé aux administrateurs.",
        "genkey_ok": "✅ {n} clé(s) générée(s) (mensuel).\nPremière clé :\n<code>{first}</code>",
        "delkey_ok": "🗑️ Clé supprimée.",
        "delkey_not_found": "❌ Clé introuvable.",
        "delsub_ok": "🗑️ Abonnement supprimé pour l’utilisateur {uid}.",
        "delsub_not_found": "ℹ️ Aucun abonnement enregistré pour cet utilisateur.",
        "subinfo_none": "ℹ️ Aucun abonnement.",
        "subinfo_line": "📄 Type : {t}\n🕒 Expire : {exp}",
        "setwebsite_ok": "✅ URL du site enregistrée.",
        "setwebsite_usage": "Utilisation : /setwebsite <URL>",
        "gensub_ok": "✅ Abonnement défini pour {uid} : {t} jusqu’à {exp}.",
        "gensub_usage": "Utilisation : /gensub <user_id> monthly | +days <n>",
        "admin_w_title": "🧾 Demandes de retrait en attente",
        "admin_w_none": "Aucune demande en attente.",
        "admin_w_item": "#{id} — utilisateur {uid} — {amount}$ — {at}",
        "admin_w_approve": "✅ Demande #{id} approuvée.",
        "admin_w_denied": "❌ Demande #{id} refusée et montant renvoyé.",
        "approve_btn": "✅ Approuver",
        "deny_btn": "❌ Refuser",
        "prev_btn": "⬅️ Préc.",
        "next_btn": "Suiv. ➡️",
        "back_btn": "🔙 Retour",
        "players_title": "Liste des utilisateurs :",
        "players_empty": "Aucun utilisateur pour le moment.",
        "players_page": "Page {cur}/{total}",
        "players_search_btn": "🔎 Rechercher par ID",
        "players_search_prompt": "Envoyez l’ID utilisateur, ou '-' pour annuler.",
        "players_search_not_found": "ID introuvable. Essayez un autre.",
        "players_item_fmt": "{id} — {label}",
        "player_view_title": "👤 Utilisateur {id} — {label}",
        "player_balance": "💰 Solde : {bal}$",
        "player_stats": "📊 Statistiques : win={win}$ | loss={loss}$ | net={net}$",
        "player_country": "🗺️ Pays : {country}",
        "player_sub": "⏳ Abonnement : {remain}",
        "edit_label_btn": "✏️ Nom",
        "edit_country_btn": "🌍 Pays",
        "label_prompt": "Envoyez le nom pour {uid}. '-' pour supprimer.",
        "label_set_ok": "Nom défini : {uid} — {label}",
        "label_removed": "Nom supprimé pour {uid}.",
        "country_prompt": "Envoyez le pays pour {uid}. '-' pour supprimer.",
        "country_set_ok": "Pays défini pour {uid} : {country}",
        "country_removed": "Pays supprimé pour {uid}.",
        "usage_addbal": "Utilisation : /addbal <user_id> <amount>",
        "usage_takebal": "Utilisation : /takebal <user_id> <amount>",
        "usage_setbal": "Utilisation : /setbal <user_id> <amount>",
        "user_not_found": "Utilisateur introuvable.",
        "invalid_amount": "Montant invalide.",
        "bal_added_ok": "✅ Ajouté {amount}$ à {uid}. Nouveau solde : {bal}$",
        "bal_taken_ok": "✅ Retiré {amount}$ de {uid}. Nouveau solde : {bal}$",
        "bal_set_ok": "✅ Solde défini à {bal}$ pour {uid}",
        "balance_linked_msg": "✅ Bot lié à votre compte de trading. Solde : {bal}$"
    }
}

def _status_label(code: str, lang: str) -> str:
    labels = {
        "ar": {"pending":"بانتظار الموافقة","approved":"مقبولة","denied":"مرفوضة","canceled":"ملغاة"},
        "en": {"pending":"Pending","approved":"Approved","denied":"Denied","canceled":"Canceled"},
        "tr": {"pending":"Beklemede","approved":"Onaylandı","denied":"Reddedildi","canceled":"İptal"},
        "es": {"pending":"Pendiente","approved":"Aprobada","denied":"Rechazada","canceled":"Cancelada"},
        "fr": {"pending":"En attente","approved":"Approuvée","denied":"Refusée","canceled":"Annulée"}
    }
    m = labels.get(lang, labels["en"])
    return m.get(code, code)

# ---------- Users & i18n helpers ----------
def get_lang(uid: str) -> str:
    users = load_json("users.json") or {}
    lang = (users.get(uid, {}) or {}).get("lang", "en")
    return lang if lang in LANGS else "en"

def set_lang(uid: str, lang: str) -> None:
    users = load_json("users.json") or {}
    users.setdefault(uid, {"balance": 0, "role": "user", "created_at": _now_str(), "lang": "en"})
    users[uid]["lang"] = lang if lang in LANGS else "en"
    save_json("users.json", users)

def T(user_uid: str, key: str, **kwargs) -> str:
    lang = get_lang(user_uid)
    s = TEXT.get(lang, TEXT["en"]).get(key, "")
    try:
        return s.format(**kwargs)
    except Exception:
        return s

# ---------- Users ----------
def ensure_user(chat_id: int) -> str:
    uid = str(chat_id)
    users = load_json("users.json") or {}
    if uid not in users:
        users[uid] = {
            "balance": 0,
            "role": "admin" if chat_id in ADMIN_IDS else "user",
            "created_at": _now_str(),
            "lang": "en"
        }
        save_json("users.json", users)
    else:
        if chat_id in ADMIN_IDS and users.get(uid, {}).get("role") != "admin":
            users[uid]["role"] = "admin"
            save_json("users.json", users)
    return uid

def is_admin(uid: str) -> bool:
    try:
        if int(uid) in ADMIN_IDS:
            return True
    except Exception:
        pass
    users = load_json("users.json") or {}
    return (users.get(uid, {}) or {}).get("role") == "admin"

# ---------- Menus ----------
def main_menu_markup(uid: str) -> types.InlineKeyboardMarkup:
    tt = TEXT[get_lang(uid)]
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton(tt["btn_daily"], callback_data="daily_trade"),
          types.InlineKeyboardButton(tt["btn_withdraw"], callback_data="withdraw_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_wstatus"], callback_data="withdraw_status"),
          types.InlineKeyboardButton(tt["btn_stats"], callback_data="stats"))
    m.add(types.InlineKeyboardButton(tt["btn_deposit"], callback_data="deposit"),
          types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_website"], callback_data="website"),
          types.InlineKeyboardButton(tt["btn_support"], callback_data="support"))
    return m

def show_main_menu(chat_id: int):
    uid = ensure_user(chat_id)
    users = load_json("users.json") or {}
    balance = (users.get(uid, {}) or {}).get("balance", 0)
    remain = sub_remaining_str(uid)
    bot.send_message(
        chat_id,
        T(uid, "welcome", balance=balance, user_id=uid, remain=remain),
        reply_markup=main_menu_markup(uid)
    )

# ---------- Subscription flow ----------
def require_active_or_ask(chat_id: int) -> bool:
    uid = ensure_user(chat_id)
    if is_sub_active(uid):
        users = load_json("users.json") or {}
        if users.get(uid, {}).get("await_key"):
            users[uid]["await_key"] = False
            save_json("users.json", users)
        return True

    users = load_json("users.json") or {}
    users.setdefault(uid, {})
    users[uid]["await_key"] = True
    save_json("users.json", users)

    show_need_key_prompt(chat_id, uid)
    return False

def show_need_key_prompt(chat_id: int, uid: str):
    tt = TEXT[get_lang(uid)]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport"))
    kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    msg = T(uid, "key_expired") if (load_json("users.json") or {}).get(uid, {}).get("sub") else T(uid, "need_key")
    bot.send_message(chat_id, msg, reply_markup=kb)

def _rand_key(n=4) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def generate_keys(k_type: str, count: int) -> List[str]:
    if k_type != "monthly":
        raise ValueError("Only 'monthly' keys are allowed")
    keys = _key_store()
    out: List[str] = []
    for _ in range(count):
        while True:
            k = f"MO-{_rand_key()}-{_rand_key()}-{_rand_key()}"
            if k not in keys:
                break
        keys[k] = {"type": k_type, "created_at": _now_str()}
        out.append(k)
    _save_keys(keys)
    return out

def activate_key_for_user(uid: str, key: str) -> Optional[str]:
    keys = _key_store()
    meta = keys.get(key)
    if not meta or meta.get("used_by"):
        return None

    ktype = meta.get("type")
    if ktype != "monthly":
        return None

    days = DURATIONS.get(ktype, 30)
    users = load_json("users.json") or {}
    users.setdefault(uid, {})

    exp_dt = _now() + timedelta(days=days)
    exp = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
    users[uid]["sub"] = {"type": ktype, "expire_at": exp, "key": key}
    users[uid]["await_key"] = False
    keys[key]["used_by"] = uid
    keys[key]["used_at"] = _now_str()
    _save_keys(keys)
    save_json("users.json", users)
    return T(uid, "key_ok", stype=ktype, exp=exp)

# ---------- Commands ----------
@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    show_main_menu(message.chat.id)

@bot.message_handler(commands=["lang"])
def cmd_lang(message: types.Message):
    uid = ensure_user(message.chat.id)
    return bot.reply_to(message, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=build_lang_kb())

@bot.message_handler(commands=["help"])
def cmd_help(message: types.Message):
    uid = ensure_user(message.chat.id)
    tt = TEXT[get_lang(uid)]
    is_adm = is_admin(uid)
    lines = [f"<b>{tt['help_title']}</b>"]
    lines.extend(tt["help_public"])
    if is_adm:
        lines.append("")
        lines.extend(tt["help_admin"])
    bot.send_message(message.chat.id, "\n".join(f"• {x}" if not x.startswith("<b>") else x for x in lines))

@bot.message_handler(commands=["id"])
def cmd_id(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    bot.reply_to(message, f"<b>ID</b> <code>{message.from_user.id}</code>")

@bot.message_handler(commands=["balance"])
def cmd_balance(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    users = load_json("users.json") or {}
    bal = (users.get(uid, {}) or {}).get("balance", 0)
    bot.reply_to(message, f"💰 {bal}$")

@bot.message_handler(commands=["daily"])
def cmd_daily(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    daily = load_daily_text_for(uid) or TEXT[get_lang(uid)]["daily_none"]
    bot.reply_to(message, daily if isinstance(daily, str) else str(daily))

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        return open_withdraw_menu(message.chat.id, uid)
    try:
        amount = int(parts[1])
    except Exception:
        return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_invalid"])
    return create_withdraw_request(message.chat.id, uid, amount)

@bot.message_handler(commands=["wlist"])
def cmd_wlist(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    return _wlist_send_page(message.chat.id, 1)

# --- WEBSITE ---
@bot.message_handler(commands=["setwebsite"])
def cmd_setwebsite(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not re.match(r"^https?://", parts[1].strip()):
        return bot.reply_to(message, T(uid, "setwebsite_usage"))
    s = load_settings()
    s["WEBSITE_URL"] = parts[1].strip()
    save_settings(s)
    return bot.reply_to(message, T(uid, "setwebsite_ok"))

@bot.message_handler(commands=["delwebsite"])
def cmd_delwebsite(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    s = load_settings()
    if "WEBSITE_URL" in s:
        s.pop("WEBSITE_URL", None)
        save_settings(s)
    return bot.reply_to(message, T(uid, "delwebsite_ok"))

# --- GENSUB (monthly only or +days) ---
@bot.message_handler(commands=["gensub"])
def cmd_gensub(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return bot.reply_to(message, T(uid_admin, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, T(uid_admin, "gensub_usage"))
    target = parts[1].strip()
    mode = parts[2].lower().strip()
    users = load_json("users.json") or {}
    users.setdefault(target, {"balance": 0, "role": "user", "created_at": _now_str(), "lang": "en"})
    sub = users[target].get("sub", {})
    now = _now()
    if mode == "monthly":
        exp_dt = now + timedelta(days=DURATIONS["monthly"])
        exp_str = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
        users[target]["sub"] = {"type": "monthly", "expire_at": exp_str, "key": "MANUAL"}
    elif mode == "+days":
        if len(parts) < 4:
            return bot.reply_to(message, T(uid_admin, "gensub_usage"))
        try:
            add_days = int(parts[3])
        except Exception:
            return bot.reply_to(message, T(uid_admin, "gensub_usage"))
        if sub and sub.get("expire_at"):
            try:
                base = datetime.strptime(sub["expire_at"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                base = now
        else:
            base = now
        new_exp = (base + timedelta(days=add_days)).strftime("%Y-%m-%d %H:%M:%S")
        users[target]["sub"] = {"type": "monthly", "expire_at": new_exp, "key": "MANUAL"}
    else:
        return bot.reply_to(message, T(uid_admin, "gensub_usage"))
    save_json("users.json", users)
    exp_show = users[target]["sub"].get("expire_at","—") or "—"
    return bot.reply_to(message, T(uid_admin, "gensub_ok", uid=target, t=users[target]["sub"].get("type","-"), exp=exp_show))

# --- GENKEY monthly only ---
@bot.message_handler(commands=["genkey"])
def cmd_genkey(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /genkey monthly [count]")
    ktype = parts[1].lower()
    if ktype != "monthly":
        return bot.reply_to(message, "Usage: /genkey monthly [count]")
    try:
        count = int(parts[2]) if len(parts) > 2 else 1
        if count < 1 or count > 100:
            raise ValueError()
    except Exception:
        return bot.reply_to(message, "count must be 1..100")
    keys = generate_keys(ktype, count)
    if count == 1:
        return bot.reply_to(message, T(uid, "genkey_ok", n=count, t=ktype, first=keys[0]))
    else:
        txt = "\n".join(keys)
        try:
            bot.reply_to(message, T(uid, "genkey_ok", n=count, t=ktype, first=keys[0]))
            bot.send_document(message.chat.id, ("keys.txt", txt.encode("utf-8")))
        except Exception:
            bot.reply_to(message, "Generated keys:\n" + ("\n".join(f"<code>{k}</code>" for k in keys)))

@bot.message_handler(commands=["delkey"])
def cmd_delkey(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /delkey <KEY>")
    key = parts[1].strip()
    keys = _key_store()
    if key in keys:
        del keys[key]
        _save_keys(keys)
        return bot.reply_to(message, T(uid, "delkey_ok"))
    return bot.reply_to(message, T(uid, "delkey_not_found"))

@bot.message_handler(commands=["delsub"])
def cmd_delsub(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /delsub <USER_ID>")
    target = parts[1]
    users = load_json("users.json") or {}
    if target in users and "sub" in users[target]:
        users[target].pop("sub", None)
        save_json("users.json", users)
        return bot.reply_to(message, T(uid, "delsub_ok", uid=target))
    return bot.reply_to(message, T(uid, "delsub_not_found"))

@bot.message_handler(commands=["subinfo"])
def cmd_subinfo(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split()
    target = parts[1] if len(parts) > 1 else uid
    users = load_json("users.json") or {}
    sub = (users.get(target, {}) or {}).get("sub")
    if not sub:
        return bot.reply_to(message, T(uid, "subinfo_none"))
    t = sub.get("type", "-")
    exp = sub.get("expire_at", "—")
    return bot.reply_to(message, T(uid, "subinfo_line", t=t, exp=exp))

# ---------- Withdraw Helpers ----------
def open_withdraw_menu(chat_id: int, uid: str):
    tt = TEXT[get_lang(uid)]
    mm = types.InlineKeyboardMarkup()
    for amount in [10, 20, 30, 50, 100]:
        mm.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
    mm.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    mm.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    bot.send_message(chat_id, tt["choose_withdraw_amount"], reply_markup=mm)

def create_withdraw_request(chat_id: int, uid: str, amount: int):
    if amount <= 0:
        return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_invalid"])
    users = load_json("users.json") or {}
    bal = (users.get(uid, {}) or {}).get("balance", 0)
    if bal < amount:
        return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_insufficient"].format(bal=bal))

    # Create request first
    withdraw_requests = load_json("withdraw_requests.json") or {}
    req_id = str(len(withdraw_requests) + 1)
    withdraw_requests[req_id] = {
        "user_id": uid, "amount": amount, "status": "pending",
        "created_at": _now_str()
    }
    save_json("withdraw_requests.json", withdraw_requests)

    # Then deduct balance
    users.setdefault(uid, {"balance": 0})
    users[uid]["balance"] = bal - amount
    save_json("users.json", users)
    return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_created"].format(req_id=req_id, amount=amount))

# ---------- Language callbacks ----------
@bot.callback_query_handler(func=lambda c: c.data=="lang_menu")
def cb_lang_menu(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    try: bot.answer_callback_query(call.id)
    except Exception: pass
    bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=build_lang_kb())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("set_lang_"))
def cb_set_lang(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    code = (call.data or "").split("_")[-1]
    if code in ("ar","en","tr","es","fr"):
        set_lang(uid, code)
    try:
        bot.answer_callback_query(call.id, text=TEXT[get_lang(uid)]["lang_updated_to"])
    except Exception:
        pass
    if not is_sub_active(uid):
        show_need_key_prompt(call.message.chat.id, uid)
    else:
        show_main_menu(call.message.chat.id)

# ---------- Stats command (localized) ----------
@bot.message_handler(commands=["mystats"])
def cmd_mystats(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not require_active_or_ask(message.chat.id):
        return
    txt = _stats_text(uid, uid)
    mm = types.InlineKeyboardMarkup()
    tt = TEXT[get_lang(uid)]
    mm.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"),
           types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    return bot.send_message(message.chat.id, txt, reply_markup=mm)

# ---------- Players (replace users) ----------
PAGE_SIZE = 10
_pending_label: Dict[int, Tuple[str,int]] = {}
_pending_country: Dict[int, Tuple[str,int]] = {}
_pending_player_search: Dict[int, int] = {}

def list_user_ids() -> List[int]:
    users = load_json("users.json") or {}
    for uid,u in users.items():
        if "label" not in u: u["label"] = None
        if "country" not in u: u["country"] = None
    save_json("users.json", users)
    return sorted([int(x) for x in users.keys()])

def _user_label(uid: str) -> str:
    users = load_json("users.json") or {}
    return (users.get(uid, {}) or {}).get("label") or "(no name)"

def _sub_remaining(uid: str) -> str:
    try:
        return sub_remaining_str(uid)
    except Exception:
        return "—"

@bot.message_handler(commands=["players", "users"])
def cmd_players(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return
    show_players_page(message.chat.id, 1)

def show_players_page(chat_id: int, page: int=1):
    admin_uid = ensure_user(chat_id)
    tt = TEXT[get_lang(admin_uid)]
    ids = list_user_ids()
    if not ids:
        return bot.send_message(chat_id, tt["players_empty"])
    start = (page-1)*PAGE_SIZE
    chunk = ids[start:start+PAGE_SIZE]
    kb = types.InlineKeyboardMarkup()
    for i in chunk:
        sid = str(i)
        label = _html.escape(_user_label(sid))
        kb.add(types.InlineKeyboardButton(tt["players_item_fmt"].format(id=sid, label=label),
                                          callback_data=f"players:view:{sid}:{page}"))
    # search + nav
    nav = []
    if page>1: nav.append(types.InlineKeyboardButton(tt["prev_btn"], callback_data=f"players:page:{page-1}"))
    if start+PAGE_SIZE < len(ids): nav.append(types.InlineKeyboardButton(tt["next_btn"], callback_data=f"players:page:{page+1}"))
    if nav: kb.row(*nav)
    kb.add(types.InlineKeyboardButton(tt["players_search_btn"], callback_data=f"players:search:{page}"))
    bot.send_message(chat_id, tt["players_title"], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:page:"))
def cb_players_page(c: types.CallbackQuery):
    admin_uid = ensure_user(c.from_user.id)
    if not is_admin(admin_uid):
        return bot.answer_callback_query(c.id)
    tt = TEXT[get_lang(admin_uid)]
    page = int((c.data or "").split(":")[-1])
    ids = list_user_ids()
    start = (page-1)*PAGE_SIZE
    chunk = ids[start:start+PAGE_SIZE]
    kb = types.InlineKeyboardMarkup()
    for i in chunk:
        sid = str(i)
        label = _html.escape(_user_label(sid))
        kb.add(types.InlineKeyboardButton(tt["players_item_fmt"].format(id=sid, label=label),
                                          callback_data=f"players:view:{sid}:{page}"))
    nav = []
    if page>1: nav.append(types.InlineKeyboardButton(tt["prev_btn"], callback_data=f"players:page:{page-1}"))
    if start+PAGE_SIZE < len(ids): nav.append(types.InlineKeyboardButton(tt["next_btn"], callback_data=f"players:page:{page+1}"))
    if nav: kb.row(*nav)
    kb.add(types.InlineKeyboardButton(tt["players_search_btn"], callback_data=f"players:search:{page}"))
    try:
        bot.edit_message_text(tt["players_title"], c.message.chat.id, c.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(c.message.chat.id, tt["players_title"], reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:view:"))
def cb_player_view(c: types.CallbackQuery):
    admin_uid = ensure_user(c.from_user.id)
    if not is_admin(admin_uid):
        return bot.answer_callback_query(c.id)
    _,_,sid,page = c.data.split(":")
    uid = sid
    users = load_json("users.json") or {}
    u = users.get(uid, {}) or {}
    bal = float(u.get("balance", 0))
    stats = _get_stats()
    st = stats.get(uid, {"total_win":0.0,"total_loss":0.0})
    win = float(st.get("total_win",0.0)); loss=float(st.get("total_loss",0.0)); net=win-loss
    country = _html.escape(u.get("country") or "—")
    remain = _sub_remaining(uid)
    label = _html.escape(u.get("label") or "(no name)")

    tt = TEXT[get_lang(admin_uid)]
    txt = (f"{tt['player_view_title'].format(id=uid, label=label)}\n"
           f"{tt['player_balance'].format(bal=bal):s}\n"
           f"{tt['player_stats'].format(win=f'{win:.2f}', loss=f'{loss:.2f}', net=f'{net:.2f}'):s}\n"
           f"{tt['player_country'].format(country=country):s}\n"
           f"{tt['player_sub'].format(remain=remain):s}")

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton(tt["edit_label_btn"], callback_data=f"players:label:{uid}:{page}"),
        types.InlineKeyboardButton(tt["edit_country_btn"], callback_data=f"players:country:{uid}:{page}")
    )
    kb.row(types.InlineKeyboardButton(tt["back_btn"], callback_data=f"players:page:{page}"))
    try:
        bot.edit_message_text(txt, c.message.chat.id, c.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(c.message.chat.id, txt, reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:label:"))
def cb_player_label(c: types.CallbackQuery):
    admin_uid = ensure_user(c.from_user.id)
    if not is_admin(admin_uid):
        return bot.answer_callback_query(c.id)
    _,_,uid,page = c.data.split(":")
    _pending_label[c.from_user.id] = (uid, int(page))
    bot.answer_callback_query(c.id, T(admin_uid, "label_prompt", uid=uid))
    bot.send_message(c.message.chat.id, T(admin_uid, "label_prompt", uid=uid))

@bot.message_handler(func=lambda m: m.from_user.id in _pending_label)
def on_admin_label(m: types.Message):
    uid, page = _pending_label.pop(m.from_user.id)
    admin_uid = ensure_user(m.from_user.id)
    users = load_json("users.json") or {}
    u = users.setdefault(uid, {})
    val = (m.text or "").strip()
    if val == "-" or val == "":
        u["label"] = None
        msg = T(admin_uid, "label_removed", uid=uid)
    else:
        u["label"] = val[:32]
        msg = T(admin_uid, "label_set_ok", uid=uid, label=_html.escape(u['label']))
    save_json("users.json", users)
    bot.reply_to(m, msg)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:country:"))
def cb_player_country(c: types.CallbackQuery):
    admin_uid = ensure_user(c.from_user.id)
    if not is_admin(admin_uid):
        return bot.answer_callback_query(c.id)
    _,_,uid,page = c.data.split(":")
    _pending_country[c.from_user.id] = (uid, int(page))
    bot.answer_callback_query(c.id, T(admin_uid, "country_prompt", uid=uid))
    bot.send_message(c.message.chat.id, T(admin_uid, "country_prompt", uid=uid))

@bot.message_handler(func=lambda m: m.from_user.id in _pending_country)
def on_admin_country(m: types.Message):
    uid, page = _pending_country.pop(m.from_user.id)
    admin_uid = ensure_user(m.from_user.id)
    users = load_json("users.json") or {}
    u = users.setdefault(uid, {})
    val = (m.text or "").strip()
    if val == "-" or val == "":
        u["country"] = None
        msg = T(admin_uid, "country_removed", uid=uid)
    else:
        u["country"] = val[:32]
        msg = T(admin_uid, "country_set_ok", uid=uid, country=_html.escape(u['country']))
    save_json("users.json", users)
    bot.reply_to(m, msg)

# --- Players search ---
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:search:"))
def cb_players_search(c: types.CallbackQuery):
    admin_uid = ensure_user(c.from_user.id)
    if not is_admin(admin_uid):
        return bot.answer_callback_query(c.id)
    page = int((c.data or "players:search:1").split(":")[-1])
    _pending_player_search[c.from_user.id] = page
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, T(admin_uid, "players_search_prompt"))

@bot.message_handler(func=lambda m: m.from_user.id in _pending_player_search)
def on_players_search(m: types.Message):
    admin_uid = ensure_user(m.from_user.id)
    page = _pending_player_search.get(m.from_user.id, 1)
    txt = (m.text or "").strip()
    if txt == "-":
        _pending_player_search.pop(m.from_user.id, None)
        return show_players_page(m.chat.id, page)
    if not txt.isdigit():
        return bot.reply_to(m, T(admin_uid, "players_search_not_found"))
    uid = txt
    users = load_json("users.json") or {}
    if uid not in users:
        return bot.reply_to(m, T(admin_uid, "players_search_not_found"))
    # open view
    c = types.SimpleNamespace()
    c.from_user = types.SimpleNamespace(id=m.from_user.id)
    c.message = types.SimpleNamespace(chat=m.chat, message_id=m.message_id)
    c.data = f"players:view:{uid}:{page}"
    return cb_player_view(c)

# ---------- Balances (admin) ----------
def _parse_amount(s: str) -> Optional[float]:
    try:
        v = float(s)
        if v <= 0 or v > 1_000_000:
            return None
        return round(v, 2)
    except Exception:
        return None

def _notify_balance(uid: str):
    users = load_json("users.json") or {}
    bal = float((users.get(uid, {}) or {}).get("balance", 0))
    try:
        bot.send_message(int(uid), T(uid, "balance_linked_msg", bal=f"{bal:.2f}"))
    except Exception:
        pass

@bot.message_handler(commands=["addbal"])
def cmd_addbal(message: types.Message):
    admin_uid = ensure_user(message.chat.id)
    if not is_admin(admin_uid):
        return bot.reply_to(message, T(admin_uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, T(admin_uid, "usage_addbal"))
    uid = parts[1]
    amount = _parse_amount(parts[2])
    users = load_json("users.json") or {}
    if amount is None:
        return bot.reply_to(message, T(admin_uid, "invalid_amount"))
    if uid not in users:
        return bot.reply_to(message, T(admin_uid, "user_not_found"))
    users[uid]["balance"] = float(users[uid].get("balance", 0)) + amount
    save_json("users.json", users)
    bot.reply_to(message, T(admin_uid, "bal_added_ok", uid=uid, amount=f"{amount:.2f}", bal=f"{users[uid]['balance']:.2f}"))
    _notify_balance(uid)

@bot.message_handler(commands=["takebal"])
def cmd_takebal(message: types.Message):
    admin_uid = ensure_user(message.chat.id)
    if not is_admin(admin_uid):
        return bot.reply_to(message, T(admin_uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, T(admin_uid, "usage_takebal"))
    uid = parts[1]
    amount = _parse_amount(parts[2])
    users = load_json("users.json") or {}
    if amount is None:
        return bot.reply_to(message, T(admin_uid, "invalid_amount"))
    if uid not in users:
        return bot.reply_to(message, T(admin_uid, "user_not_found"))
    users[uid]["balance"] = max(0.0, float(users[uid].get("balance", 0)) - amount)
    save_json("users.json", users)
    bot.reply_to(message, T(admin_uid, "bal_taken_ok", uid=uid, amount=f"{amount:.2f}", bal=f"{users[uid]['balance']:.2f}"))
    _notify_balance(uid)

@bot.message_handler(commands=["setbal"])
def cmd_setbal(message: types.Message):
    admin_uid = ensure_user(message.chat.id)
    if not is_admin(admin_uid):
        return bot.reply_to(message, T(admin_uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, T(admin_uid, "usage_setbal"))
    uid = parts[1]
    amount = _parse_amount(parts[2])
    users = load_json("users.json") or {}
    if amount is None:
        return bot.reply_to(message, T(admin_uid, "invalid_amount"))
    if uid not in users:
        return bot.reply_to(message, T(admin_uid, "user_not_found"))
    users[uid]["balance"] = amount
    save_json("users.json", users)
    bot.reply_to(message, T(admin_uid, "bal_set_ok", uid=uid, bal=f"{users[uid]['balance']:.2f}"))
    _notify_balance(uid)

# ---------- General callbacks (non-players) ----------
@bot.callback_query_handler(func=lambda call: call.data=="go_back")
def cb_go_back(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    try:
        if not is_sub_active(uid):
            show_need_key_prompt(call.message.chat.id, uid)
        else:
            show_main_menu(call.message.chat.id)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data in ("daily_trade","withdraw_menu","withdraw_status","deposit","website","support") or call.data.startswith(("withdraw_","dep_","cancel_","wapp_","wden_")))
def callbacks(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    tt = TEXT[get_lang(uid)]
    data = call.data or ""
    try: bot.answer_callback_query(call.id)
    except Exception: pass

    if data == "daily_trade":
        daily = load_daily_text_for(uid) or tt["daily_none"]
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"),
               types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
        return bot.send_message(call.message.chat.id, daily if isinstance(daily, str) else str(daily), reply_markup=mm)

    if data == "withdraw_menu":
        return open_withdraw_menu(call.message.chat.id, uid)

    if data == "withdraw_status":
        withdraw_requests = load_json("withdraw_requests.json") or {}
        mm = types.InlineKeyboardMarkup()
        found = False
        for req_id, req in withdraw_requests.items():
            if req.get("user_id") == uid and req.get("status") == "pending":
                mm.add(types.InlineKeyboardButton(f"❌ cancel {req.get('amount',0)}$", callback_data=f"cancel_{req_id}"))
                found = True
        mm.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
        msg = tt["requests_waiting"] if found else tt["no_requests"]
        return bot.send_message(call.message.chat.id, msg, reply_markup=mm)

    if data.startswith("withdraw_"):
        try:
            amount = int(data.split("_", 1)[1])
        except Exception:
            amount = 0
        return create_withdraw_request(call.message.chat.id, uid, amount)

    if data.startswith("wapp_") or data.startswith("wden_"):
        # Admin gate
        if not is_admin(uid):
            return
        rid = data.split("_",1)[1]
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req = withdraw_requests.get(rid)
        if not req or req.get("status") != "pending":
            return bot.send_message(call.message.chat.id, "Already processed or not found.")
        if data.startswith("wapp_"):
            req["status"] = "approved"
            logbook = load_json("withdraw_log.json") or {}
            logbook[str(len(logbook)+1)] = {**req, "processed_at": _now_str(), "action": "approved"}
            save_json("withdraw_log.json", logbook)
            save_json("withdraw_requests.json", withdraw_requests)
            try:
                bot.send_message(int(req.get("user_id")), f"✅ تم قبول طلب السحب #{rid} بقيمة {req.get('amount')}$")
            except Exception:
                pass
            return bot.send_message(call.message.chat.id, T(uid, "admin_w_approve", id=rid))
        else:
            users = load_json("users.json") or {}
            u = users.setdefault(req.get("user_id"), {"balance":0})
            u["balance"] = float(u.get("balance",0)) + float(req.get("amount",0))
            save_json("users.json", users)
            req["status"] = "denied"
            logbook = load_json("withdraw_log.json") or {}
            logbook[str(len(logbook)+1)] = {**req, "processed_at": _now_str(), "action": "denied"}
            save_json("withdraw_log.json", logbook)
            save_json("withdraw_requests.json", withdraw_requests)
            try:
                bot.send_message(int(req.get("user_id")), f"❌ تم رفض طلب السحب #{rid} وتمت إعادة المبلغ.")
            except Exception:
                pass
            return bot.send_message(call.message.chat.id, T(uid, "admin_w_denied", id=rid))

    if data.startswith("dep_"):
        method_map = {
            "dep_cash": tt["deposit_cash"],
            "dep_paypal": tt["deposit_paypal"],
            "dep_bank": tt["deposit_bank"],
            "dep_mc": tt["deposit_mc"],
            "dep_visa": tt["deposit_visa"],
        }
        method = method_map.get(data, "Payment")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["contact_us"], url="https://t.me/qlsupport"))
        kb.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="deposit"))
        return bot.send_message(call.message.chat.id, tt["deposit_msg"].format(method=method), reply_markup=kb)

    if data == "deposit":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["deposit_cash"], callback_data="dep_cash"))
        kb.add(types.InlineKeyboardButton(tt["deposit_paypal"], callback_data="dep_paypal"))
        kb.add(types.InlineKeyboardButton(tt["deposit_bank"], callback_data="dep_bank"))
        kb.add(types.InlineKeyboardButton(tt["deposit_mc"], callback_data="dep_mc"))
        kb.add(types.InlineKeyboardButton(tt["deposit_visa"], callback_data="dep_visa"))
        kb.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
        return bot.send_message(call.message.chat.id, tt["deposit_choose"], reply_markup=kb)

    if data == "website":
        url_site = get_website_url()
        if url_site:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(tt["btn_website"], url=url_site))
            return bot.send_message(call.message.chat.id, tt["website_msg"], reply_markup=kb)
        else:
            return bot.send_message(call.message.chat.id, tt["website_not_set"])

    if data == "support":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["contact_us"], url="https://t.me/qlsupport"))
        return bot.send_message(call.message.chat.id, tt["support_msg"], reply_markup=kb)

# ---------- Fallback key activation ----------
KEY_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

@bot.message_handler(func=lambda m: bool(m.text) and not m.text.strip().startswith(("/", "／", "⁄")))
def maybe_activate_key(message: types.Message):
    uid = ensure_user(message.chat.id)
    users = load_json("users.json") or {}
    if (users.get(uid, {}) or {}).get("await_key"):
        key = (message.text or "").strip().upper().replace(" ", "")
        if KEY_RE.match(key):
            resp = activate_key_for_user(uid, key)
            if resp:
                try: bot.reply_to(message, resp)
                except Exception: pass
                try: show_main_menu(message.chat.id)
                except Exception: pass
                return
        try: bot.reply_to(message, TEXT[get_lang(uid)]["key_invalid"])
        except Exception: pass
        try: show_need_key_prompt(message.chat.id, uid)
        except Exception: pass
        return
    return

# ---------- Stats storage ----------
def _get_stats(): return load_json("stats.json") or {}
def _save_stats(d): save_json("stats.json", d)
def _add_stat(user_id: str, kind: str, amount: float):
    stats = _get_stats()
    u = stats.setdefault(user_id, {"total_win": 0.0, "total_loss": 0.0, "history": []})
    if kind == "win": u["total_win"] = float(u.get("total_win", 0.0)) + float(amount)
    else: u["total_loss"] = float(u.get("total_loss", 0.0)) + float(amount)
    u["history"].insert(0, {"ts": datetime.utcnow().isoformat(timespec="seconds")+"Z","kind":kind,"amount":float(amount)})
    u["history"] = u["history"][:100]
    _save_stats(stats); return u

def _stats_text(uid_viewer: str, target_uid: str):
    tt = TEXT[get_lang(uid_viewer)]
    stats = _get_stats()
    u = stats.get(target_uid, {"total_win": 0.0, "total_loss": 0.0, "history": []})
    win_sum = float(u.get("total_win", 0.0))
    loss_sum = float(u.get("total_loss", 0.0))
    hist = u.get("history", []) or []
    win_cnt = sum(1 for h in hist if (h or {}).get("kind") == "win")
    loss_cnt = sum(1 for h in hist if (h or {}) .get("kind") == "loss")
    net = win_sum - loss_sum
    return (
        f"{tt['stats_title']}\n"
        f"{tt['stats_wins'].format(sum=f'{win_sum:.2f}', count=win_cnt)}\n"
        f"{tt['stats_losses'].format(sum=f'{loss_sum:.2f}', count=loss_cnt)}\n"
        f"{tt['stats_net'].format(net=f'{net:.2f}')}"
    )

# ---------- Health & Webhook ----------
@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

@app.route(f"/{API_TOKEN}", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200
    try:
        raw = request.get_data().decode("utf-8")
        if not raw:
            return "OK", 200
        update = telebot.types.Update.de_json(raw)
        bot.process_new_updates([update])
    except Exception as e:
        log.error("Webhook error: %s", e)
    return "OK", 200

from threading import Thread
def start_polling():
    try: bot.remove_webhook()
    except Exception: pass
    log.info("Starting polling...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

if WEBHOOK_URL:
    try: bot.remove_webhook()
    except Exception: pass
    url = f"{WEBHOOK_URL}/{API_TOKEN}"
    try:
        bot.set_webhook(url=url, allowed_updates=["message","callback_query","my_chat_member","chat_member","edited_message"])
        log.info("Webhook set to: %s", url)
    except Exception as e:
        log.error("set_webhook failed: %s", e)
    app.run(host="0.0.0.0", port=PORT)
else:
    Thread(target=start_polling, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
