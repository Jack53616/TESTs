
# -*- coding: utf-8 -*-
"""
Refactored Telegram bot for Render (Webhook) or local (Polling).
- Clean i18n (ar/en/tr/es/fr)
- Main menu (daily / withdraw / withdraw status / stats / language)
- Withdraw via buttons or /withdraw <amount>
- Optional Postgres key-value storage when DATABASE_URL is set (db_kv.py)
- JSON file storage fallback (users.json, withdraw_requests.json, trades.json, daily_trade.txt)
"""
import os, json, logging
from datetime import datetime
from typing import Dict, Any
from flask import Flask, request

import telebot
from telebot import types

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

# ---------- ENV ----------
API_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "1262317603"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=True)
app = Flask(__name__)

# ---------- Storage Layer ----------
USE_DB = bool(DATABASE_URL)
if USE_DB:
    try:
        from db_kv import init_db, get_json as db_get_json, set_json as db_set_json
        init_db()  # create table if not exists
        log.info("DB storage enabled")
    except Exception as e:
        log.error("Failed to init DB storage, fallback to files: %s", e)
        USE_DB = False

DATA_FILES = {
    "users": "users.json",
    "withdraw_requests": "withdraw_requests.json",
    "withdraw_log": "withdraw_log.json",
    "trades": "trades.json",
}
def load_json(name: str) -> Any:
    """Load from DB (if enabled) else local JSON file; name is key or filename."""
    key = name
    if USE_DB:
        try:
            return db_get_json(key)
        except Exception as e:
            log.error("DB get_json error for key %s: %s", key, e)
    # file fallback
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
    # file fallback
    path = DATA_FILES.get(name.replace(".json",""), name)
    if not path.endswith(".json"):
        path = name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_daily_text() -> str:
    if os.path.exists("daily_trade.txt"):
        try:
            return open("daily_trade.txt", "r", encoding="utf-8").read().strip()
        except Exception:
            pass
    trades = load_json("trades.json") or {}
    return trades.get("daily", "")

def save_daily_text(text: str) -> None:
    with open("daily_trade.txt", "w", encoding="utf-8") as f:
        f.write(text.strip())

# ---------- i18n ----------
LANGS = ["ar", "en", "tr", "es", "fr"]
TEXT: Dict[str, Dict[str, Any]] = {
    "ar": {
        "welcome": "👋 أهلاً بك في بوت التداول\n\n💰 رصيدك: {balance}$\n🆔 آيديك: {uid}",
        "btn_daily": "📈 صفقة اليوم",
        "btn_withdraw": "💸 سحب",
        "btn_wstatus": "💼 معاملات السحب",
        "btn_stats": "📊 الإحصائيات",
        "btn_lang": "🌐 اللغة",
        "help_title": "🛠 الأوامر المتاحة:",
        "help_public": [
            "/start - القائمة الرئيسية",
            "/id - عرض آيديك",
            "/balance - رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw <amount> - طلب سحب (مثال: /withdraw 50)"
        ],
        "daily_none": "لا يوجد صفقة اليوم حالياً.",
        "withdraw_enter": "❌ الصيغة: /withdraw 50",
        "withdraw_invalid": "❌ مبلغ غير صالح.",
        "withdraw_insufficient": "الرصيد غير كافٍ. رصيدك: {bal}$",
        "withdraw_created": "✅ تم إنشاء طلب سحب #{req_id} بقيمة {amount}$.",
        "lang_menu_title": "اختر لغتك:",
        "lang_saved": "✅ تم ضبط اللغة العربية.",
        "choose_withdraw_amount": "اختر مبلغ السحب:",
        "requests_waiting": "طلباتك قيد الانتظار:",
        "no_requests": "لا توجد طلبات قيد الانتظار."
    },
    "en": {
        "welcome": "👋 Welcome to the trading bot\n\n💰 Your balance: {balance}$\n🆔 Your ID: {uid}",
        "btn_daily": "📈 Daily trade",
        "btn_withdraw": "💸 Withdraw",
        "btn_wstatus": "💼 Withdrawal requests",
        "btn_stats": "📊 Stats",
        "btn_lang": "🌐 Language",
        "help_title": "🛠 Available commands:",
        "help_public": [
            "/start - Main menu",
            "/id - Show your ID",
            "/balance - Your balance",
            "/daily - Daily trade",
            "/withdraw <amount> - Request withdrawal"
        ],
        "daily_none": "No daily trade yet.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Invalid amount.",
        "withdraw_insufficient": "Insufficient balance. Your balance: {bal}$",
        "withdraw_created": "✅ Withdrawal request #{req_id} created for {amount}$.",
        "lang_menu_title": "Choose your language:",
        "lang_saved": "✅ Language set to English.",
        "choose_withdraw_amount": "Choose withdraw amount:",
        "requests_waiting": "Your pending requests:",
        "no_requests": "No pending requests."
    },
    "tr": {
        "welcome": "👋 Trading botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n🆔 ID: {uid}",
        "btn_daily": "📈 Günün işlemi",
        "btn_withdraw": "💸 Çekim",
        "btn_wstatus": "💼 Çekim talepleri",
        "btn_stats": "📊 İstatistikler",
        "btn_lang": "🌐 Dil",
        "help_title": "🛠 Kullanılabilir komutlar:",
        "help_public": [
            "/start - Ana menü",
            "/id - ID'ni göster",
            "/balance - Bakiyen",
            "/daily - Günün işlemi",
            "/withdraw <tutar> - Çekim isteği"
        ],
        "daily_none": "Henüz günlük işlem yok.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Geçersiz tutar.",
        "withdraw_insufficient": "Yetersiz bakiye. Bakiyen: {bal}$",
        "withdraw_created": "✅ #{req_id} numaralı çekim talebi {amount}$ için oluşturuldu.",
        "lang_menu_title": "Dilini seç:",
        "lang_saved": "✅ Dil Türkçe olarak ayarlandı.",
        "choose_withdraw_amount": "Çekim tutarını seç:",
        "requests_waiting": "Bekleyen taleplerin:",
        "no_requests": "Bekleyen talep yok."
    },
    "es": {
        "welcome": "👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n🆔 Tu ID: {uid}",
        "btn_daily": "📈 Operación del día",
        "btn_withdraw": "💸 Retirar",
        "btn_wstatus": "💼 Solicitudes de retiro",
        "btn_stats": "📊 Estadísticas",
        "btn_lang": "🌐 Idioma",
        "help_title": "🛠 Comandos disponibles:",
        "help_public": [
            "/start - Menú principal",
            "/id - Mostrar tu ID",
            "/balance - Tu saldo",
            "/daily - Operación del día",
            "/withdraw <monto> - Solicitar retiro"
        ],
        "daily_none": "Aún no hay operación del día.",
        "withdraw_enter": "❌ Formato: /withdraw 50",
        "withdraw_invalid": "❌ Monto inválido.",
        "withdraw_insufficient": "Saldo insuficiente. Tu saldo: {bal}$",
        "withdraw_created": "✅ Solicitud #{req_id} creada por {amount}$.",
        "lang_menu_title": "Elige tu idioma:",
        "lang_saved": "✅ Idioma configurado a español.",
        "choose_withdraw_amount": "Elige el monto a retirar:",
        "requests_waiting": "Tus solicitudes pendientes:",
        "no_requests": "No hay solicitudes pendientes."
    },
    "fr": {
        "welcome": "👋 Bienvenue dans le bot de trading\n\n💰 Votre solde : {balance}$\n🆔 Votre ID : {uid}",
        "btn_daily": "📈 Trade du jour",
        "btn_withdraw": "💸 Retrait",
        "btn_wstatus": "💼 Demandes de retrait",
        "btn_stats": "📊 Statistiques",
        "btn_lang": "🌐 Langue",
        "help_title": "🛠 Commandes disponibles :",
        "help_public": [
            "/start - Menu principal",
            "/id - Afficher votre ID",
            "/balance - Votre solde",
            "/daily - Trade du jour",
            "/withdraw <montant> - Demande de retrait"
        ],
        "daily_none": "Aucun trade du jour pour le moment.",
        "withdraw_enter": "❌ Format : /withdraw 50",
        "withdraw_invalid": "❌ Montant invalide.",
        "withdraw_insufficient": "Solde insuffisant. Votre solde : {bal}$",
        "withdraw_created": "✅ Demande #{req_id} créée pour {amount}$.",
        "lang_menu_title": "Sélectionnez votre langue :",
        "lang_saved": "✅ Langue définie sur le français.",
        "choose_withdraw_amount": "Choisissez le montant du retrait :",
        "requests_waiting": "Vos demandes en attente :",
        "no_requests": "Aucune demande en attente."
    }
}

def get_lang(uid: str) -> str:
    users = load_json("users.json") or {}
    lang = (users.get(uid, {}) or {}).get("lang", "ar")
    return lang if lang in LANGS else "ar"

def set_lang(uid: str, lang: str) -> None:
    users = load_json("users.json") or {}
    users.setdefault(uid, {"balance": 0, "role": "user", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    users[uid]["lang"] = lang if lang in LANGS else "ar"
    save_json("users.json", users)

def T(uid: str, key: str, **kwargs) -> str:
    lang = get_lang(uid)
    s = TEXT.get(lang, TEXT["ar"]).get(key, "")
    try:
        return s.format(**kwargs)
    except Exception:
        return s

# ---------- Users & Roles ----------
def ensure_user(chat_id: int) -> str:
    uid = str(chat_id)
    users = load_json("users.json") or {}
    if uid not in users:
        users[uid] = {"balance": 0, "role": "admin" if chat_id == int(os.getenv("ADMIN_ID","1262317603")) else "user",
                      "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      "lang": "ar"}
        save_json("users.json", users)
    return uid

def is_admin(uid: str) -> bool:
    users = load_json("users.json") or {}
    return (users.get(uid, {}) or {}).get("role") == "admin"

def main_menu_markup(uid: str) -> telebot.types.InlineKeyboardMarkup:
    tt = TEXT[get_lang(uid)]
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton(tt["btn_daily"], callback_data="daily_trade"),
          types.InlineKeyboardButton(tt["btn_withdraw"], callback_data="withdraw_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_wstatus"], callback_data="withdraw_status"),
          types.InlineKeyboardButton(tt["btn_stats"], callback_data="stats"))
    m.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    return m

def show_main_menu(chat_id: int):
    uid = ensure_user(chat_id)
    users = load_json("users.json") or {}
    balance = (users.get(uid, {}) or {}).get("balance", 0)
    bot.send_message(chat_id, T(uid, "welcome", balance=balance, uid=uid), reply_markup=main_menu_markup(uid))

# ---------- Commands ----------
@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message):
    ensure_user(message.chat.id)
    show_main_menu(message.chat.id)
    log.info("START for %s", message.from_user.id)

@bot.message_handler(commands=["help"])
def cmd_help(message: types.Message):
    uid = ensure_user(message.chat.id)
    tt = TEXT[get_lang(uid)]
    lines = [tt["help_title"], *tt["help_public"]]
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["id"])
def cmd_id(message: types.Message):
    bot.reply_to(message, f"<b>ID</b> <code>{message.from_user.id}</code>")

@bot.message_handler(commands=["balance"])
def cmd_balance(message: types.Message):
    uid = ensure_user(message.chat.id)
    users = load_json("users.json") or {}
    bal = (users.get(uid, {}) or {}).get("balance", 0)
    bot.reply_to(message, f"💰 {bal}$")

@bot.message_handler(commands=["daily"])
def cmd_daily(message: types.Message):
    uid = ensure_user(message.chat.id)
    daily = load_daily_text() or TEXT[get_lang(uid)]["daily_none"]
    bot.reply_to(message, daily if isinstance(daily, str) else str(daily))

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message: types.Message):
    uid = ensure_user(message.chat.id)
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        return open_withdraw_menu(message.chat.id, uid)
    try:
        amount = int(parts[1])
    except Exception:
        return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_invalid"])
    return create_withdraw_request(message.chat.id, uid, amount)

# ---------- Withdraw Helpers ----------
def open_withdraw_menu(chat_id: int, uid: str):
    mm = types.InlineKeyboardMarkup()
    for amount in [10, 20, 30, 50, 100]:
        mm.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
    mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"))
    mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
    bot.send_message(chat_id, TEXT[get_lang(uid)]["choose_withdraw_amount"], reply_markup=mm)

def create_withdraw_request(chat_id: int, uid: str, amount: int):
    if amount <= 0:
        return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_invalid"])
    users = load_json("users.json") or {}
    bal = (users.get(uid, {}) or {}).get("balance", 0)
    if bal < amount:
        return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_insufficient"].format(bal=bal))
    users.setdefault(uid, {"balance": 0})
    users[uid]["balance"] = bal - amount
    save_json("users.json", users)

    withdraw_requests = load_json("withdraw_requests.json") or {}
    req_id = str(len(withdraw_requests) + 1)
    withdraw_requests[req_id] = {
        "user_id": uid, "amount": amount, "status": "بانتظار الموافقة",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json("withdraw_requests.json", withdraw_requests)
    return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_created"].format(req_id=req_id, amount=amount))

# ---------- Callbacks ----------
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    data = call.data or ""
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "go_back":
        return show_main_menu(call.message.chat.id)

    if data == "lang_menu":
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton("العربية 🇸🇦", callback_data="set_lang_ar"),
               types.InlineKeyboardButton("English 🇬🇧", callback_data="set_lang_en"))
        mm.add(types.InlineKeyboardButton("Türkçe 🇹🇷", callback_data="set_lang_tr"),
               types.InlineKeyboardButton("Español 🇪🇸", callback_data="set_lang_es"))
        mm.add(types.InlineKeyboardButton("Français 🇫🇷", callback_data="set_lang_fr"))
        return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=mm)

    if data.startswith("set_lang_"):
        lang = data.split("_")[-1]
        set_lang(uid, lang)
        bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_saved"])
        return show_main_menu(call.message.chat.id)

    if data == "daily_trade":
        daily = load_daily_text() or TEXT[get_lang(uid)]["daily_none"]
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"),
               types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, daily if isinstance(daily, str) else str(daily), reply_markup=mm)

    if data == "withdraw_menu":
        return open_withdraw_menu(call.message.chat.id, uid)

    if data == "withdraw_status":
        withdraw_requests = load_json("withdraw_requests.json") or {}
        mm = types.InlineKeyboardMarkup()
        found = False
        for req_id, req in withdraw_requests.items():
            if req["user_id"] == uid and req["status"] == "بانتظار الموافقة":
                mm.add(types.InlineKeyboardButton(f"❌ cancel {req['amount']}$", callback_data=f"cancel_{req_id}"))
                found = True
        mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        msg = TEXT[get_lang(uid)]["requests_waiting"] if found else TEXT[get_lang(uid)]["no_requests"]
        return bot.send_message(call.message.chat.id, msg, reply_markup=mm)

    if data.startswith("withdraw_"):
        try:
            amount = int(data.split("_")[1])
        except Exception:
            amount = 0
        return create_withdraw_request(call.message.chat.id, uid, amount)

    if data.startswith("cancel_"):
        req_id = data.split("_")[1]
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req = withdraw_requests.get(req_id)
        if req and req["user_id"] == uid and req["status"] == "بانتظار الموافقة":
            users = load_json("users.json") or {}
            users.setdefault(uid, {"balance": 0})
            users[uid]["balance"] = users[uid].get("balance", 0) + int(req["amount"])
            save_json("users.json", users)
            req["status"] = "ملغاة"
            save_json("withdraw_requests.json", withdraw_requests)
            return bot.send_message(call.message.chat.id, f"❎ Canceled request #{req_id}")
        return bot.send_message(call.message.chat.id, "Nothing to cancel.")

    if data == "stats":
        users = load_json("users.json") or {}
        wreq = load_json("withdraw_requests.json") or {}
        msg = f"👥 Users: {len(users)}\n💼 Withdraw requests: {len(wreq)}"
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, msg, reply_markup=mm)

# ---------- Admin (minimal) ----------
@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid): return
    text = (message.text or "").split(" ", 1)
    if len(text) < 2: return bot.reply_to(message, "Usage: /setdaily <text>")
    save_daily_text(text[1].strip())
    bot.reply_to(message, "✅ Daily trade updated.")

@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid): return
    parts = (message.text or "").split()
    if len(parts) < 3: return bot.reply_to(message, "Usage: /addbalance <user_id> <amount>")
    target, amount = parts[1], int(parts[2])
    users = load_json("users.json") or {}
    users.setdefault(target, {"balance": 0})
    users[target]["balance"] = users[target].get("balance", 0) + amount
    save_json("users.json", users)
    bot.reply_to(message, f"✅ New balance for {target}: {users[target]['balance']}$")


# ---------- Fallback command router (handles weird slashes/RTL) ----------
ZERO_WIDTH = "\u200f\u200e\u2066\u2067\u2068\u2069\u200b\uFEFF"
def norm_text(txt: str) -> str:
    if not txt: return ""
    t = txt.strip()
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    return t.replace("／","/").replace("⁄","/")

def dispatch_command(message: types.Message):
    raw = norm_text(message.text or "")
    cmd = raw.split()[0].lower()
    log.info("DISPATCH raw=%r parsed_cmd=%s", raw, cmd)
    if cmd in ("/start", "start"):
        return cmd_start(message)
    if cmd in ("/help", "help"):
        return cmd_help(message)
    if cmd in ("/id", "id"):
        return cmd_id(message)
    if cmd in ("/balance", "balance"):
        return cmd_balance(message)
    if cmd.startswith("/daily") or cmd=="daily":
        return cmd_daily(message)
    if cmd.startswith("/withdraw") or cmd=="withdraw":
        return cmd_withdraw(message)
    # ignore others
    return

@bot.message_handler(func=lambda m: bool(m.text and m.text.strip().startswith(("/", "／", "⁄"))))
def any_command_like(message: types.Message):
    try:
        return dispatch_command(message)
    except Exception as e:
        log.error("fallback dispatch error: %s", e)
# ---------- Webhook & Server ----------
@app.get("/")
def health():
    return "OK", 200

@app.route(f"/{API_TOKEN}", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200
    try:
        raw = request.get_data().decode("utf-8")
        if not raw: return "OK", 200
        update = telebot.types.Update.de_json(raw)
        bot.process_new_updates([update])
    except Exception as e:
        log.error("Webhook error: %s", e)
    return "OK", 200

if WEBHOOK_URL:
    try:
        bot.remove_webhook()
    except Exception:
        pass
    url = f"{WEBHOOK_URL}/{API_TOKEN}"
    try:
        bot.set_webhook(url=url, allowed_updates=[
            "message","callback_query","my_chat_member","chat_member","edited_message"
        ])
        log.info("Webhook set to: %s", url)
    except Exception as e:
        log.error("set_webhook failed: %s", e)

if __name__ == "__main__":
    log.info("Running locally with polling...")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
