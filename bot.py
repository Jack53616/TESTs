import os
import json
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ========= ENV =========
API_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # e.g., https://your-app.onrender.com
USE_DB = bool(os.environ.get("DATABASE_URL"))

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# ========= تخزين (اختياري Postgres) =========
if USE_DB:
    from db_kv import init_db, get_json, set_json
    init_db()

def load_json(filename):
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt", "")
        default = {} if filename.endswith(".json") else ""
        return get_json(key, default=default)
    else:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    return json.load(f) if filename.endswith(".json") else f.read()
                except Exception:
                    return {} if filename.endswith(".json") else ""
        return {} if filename.endswith(".json") else ""

def save_json(filename, data):
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt", "")
        set_json(key, data)
    else:
        with open(filename, "w", encoding="utf-8") as f:
            if filename.endswith(".json"):
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(data))

# ========= حِزم اللغات =========
LANGS = ["en", "ar", "tr", "es", "fr", "de", "ru"]
TEXT = {
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
            "/withdraw <amount> - Request withdrawal",
            "/mystatus - Check my role"
        ],
        "help_staff_title": "— Staff commands —",
        "help_staff": [
            "/addbalance <user_id> <amount> - Add balance",
            "/setdaily <text> - Set daily trade"
        ],
        "help_admin_title": "— Admin commands —",
        "help_admin": [
            "/setbalance <user_id> <amount> - Set balance",
            "/broadcast <text> - Broadcast",
            "/promote <user_id> - Promote to staff",
            "/demote <user_id> - Remove from staff"
        ],
        "daily_none": "No daily trade yet.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Invalid amount.",
        "withdraw_insufficient": "Insufficient balance. Your balance: {bal}$",
        "withdraw_created": "✅ Withdrawal request #{req_id} created for {amount}$.",
        "lang_menu_title": "Choose your language:",
        "lang_saved": "✅ Language set to English.",
        "choose_withdraw_amount": "🔢 Choose withdrawal amount:",
        "no_requests": "🚫 No requests now.",
        "requests_waiting": "💼 Your pending requests:",
        "cannot_cancel": "⚠️ Cannot cancel this request.",
        "canceled": "❌ Request canceled. {amount}$ returned.",
        "approved_done": "👌 Done.",
        "rejected_done": "🚫 Rejected and refunded.",
        "stats_none": "📊 No trades yet.",
        "stats_header": "📊 Your stats:\n\n",
        "stats_total": "\n✅ Total profit: {total}$",
        "enter_custom_withdraw": "💬 Send the amount you want to withdraw:",
        "min_withdraw": "❌ Minimum is 10$.",
        "not_enough": "❌ Not enough balance.",
        "enter_number": "❌ Please enter a valid number.",
    },
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
            "/id - يظهر آيديك",
            "/balance - يظهر رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw <amount> - طلب سحب",
            "/mystatus - فحص صلاحياتي"
        ],
        "help_staff_title": "— أوامر الطاقم —",
        "help_staff": [
            "/addbalance <user_id> <amount> - زيادة رصيد",
            "/setdaily <نص الصفقة> - ضبط صفقة اليوم"
        ],
        "help_admin_title": "— أوامر المدير —",
        "help_admin": [
            "/setbalance <user_id> <amount> - ضبط رصيد",
            "/broadcast <نص> - إرسال للكل",
            "/promote <user_id> - ترقية لطاقم",
            "/demote <user_id> - إزالة من الطاقم"
        ],
        "daily_none": "لا توجد صفقة يومية حالياً.",
        "withdraw_enter": "❌ الصيغة: /withdraw 50",
        "withdraw_invalid": "❌ المبلغ غير صالح.",
        "withdraw_insufficient": "رصيدك غير كافٍ. رصيدك: {bal}$",
        "withdraw_created": "✅ تم إنشاء طلب السحب #{req_id} بقيمة {amount}$.",
        "lang_menu_title": "اختر لغتك:",
        "lang_saved": "✅ تم تعيين لغتك إلى العربية.",
        "choose_withdraw_amount": "🔢 اختر المبلغ للسحب:",
        "no_requests": "🚫 لا توجد طلبات حالياً.",
        "requests_waiting": "💼 طلباتك بانتظار الموافقة:",
        "cannot_cancel": "⚠️ لا يمكن إلغاء الطلب.",
        "canceled": "❌ تم إلغاء الطلب واستعادة {amount}$.",
        "approved_done": "👌 تم التنفيذ.",
        "rejected_done": "🚫 تم الرفض وإرجاع الرصيد.",
        "stats_none": "📊 لا توجد صفقات مسجلة.",
        "stats_header": "📊 إحصائياتك:\n\n",
        "stats_total": "\n✅ إجمالي الربح: {total}$",
        "enter_custom_withdraw": "💬 اكتب المبلغ الذي تريد سحبه:",
        "min_withdraw": "❌ الحد الأدنى 10$.",
        "not_enough": "❌ لا يوجد رصيد كافٍ.",
        "enter_number": "❌ أدخل رقم صحيح.",
    },
    "tr": {
        "welcome": "👋 Ticaret botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n🆔 Kimliğin: {uid}",
        "btn_daily": "📈 Günlük işlem",
        "btn_withdraw": "💸 Çekim",
        "btn_wstatus": "💼 Çekim talepleri",
        "btn_stats": "📊 İstatistikler",
        "btn_lang": "🌐 Dil",
        "help_title": "🛠 Komutlar:",
        "help_public": [
            "/start - Ana menü",
            "/id - Kimliğini göster",
            "/balance - Bakiyen",
            "/daily - Günlük işlem",
            "/withdraw <tutar> - Çekim talebi",
            "/mystatus - Rolümü kontrol et"
        ],
        "help_staff_title": "— Görevli komutları —",
        "help_staff": [
            "/addbalance <user_id> <tutar> - Bakiye ekle",
            "/setdaily <metin> - Günlük işlemi ayarla"
        ],
        "help_admin_title": "— Yönetici komutları —",
        "help_admin": [
            "/setbalance <user_id> <tutar> - Bakiyeyi ayarla",
            "/broadcast <metin> - Duyuru",
            "/promote <user_id> - Görevli yap",
            "/demote <user_id> - Görevli kaldır"
        ],
        "daily_none": "Henüz günlük işlem yok.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Geçersiz tutar.",
        "withdraw_insufficient": "Yetersiz bakiye. Bakiyen: {bal}$",
        "withdraw_created": "✅ #{req_id} numaralı çekim talebi {amount}$ için oluşturuldu.",
        "lang_menu_title": "Dilini seç:",
        "lang_saved": "✅ Dilin Türkçe olarak ayarlandı.",
        "choose_withdraw_amount": "🔢 Çekim tutarını seç:",
        "no_requests": "🚫 Talep yok.",
        "requests_waiting": "💼 Bekleyen taleplerin:",
        "cannot_cancel": "⚠️ Bu talep iptal edilemez.",
        "canceled": "❌ Talep iptal edildi. {amount}$ iade edildi.",
        "approved_done": "👌 Tamamlandı.",
        "rejected_done": "🚫 Reddedildi ve iade edildi.",
        "stats_none": "📊 Kayıtlı işlem yok.",
        "stats_header": "📊 İstatistiklerin:\n\n",
        "stats_total": "\n✅ Toplam kâr: {total}$",
        "enter_custom_withdraw": "💬 Çekmek istediğin tutarı yaz:",
        "min_withdraw": "❌ En az 10$.",
        "not_enough": "❌ Bakiye yetersiz.",
        "enter_number": "❌ Lütfen geçerli bir sayı gir.",
    },
    "es": {
        "welcome": "👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n🆔 Tu ID: {uid}",
        "btn_daily": "📈 Operación diaria",
        "btn_withdraw": "💸 Retiro",
        "btn_wstatus": "💼 Solicitudes de retiro",
        "btn_stats": "📊 Estadísticas",
        "btn_lang": "🌐 Idioma",
        "help_title": "🛠 Comandos disponibles:",
        "help_public": [
            "/start - Menú principal",
            "/id - Mostrar tu ID",
            "/balance - Tu saldo",
            "/daily - Operación diaria",
            "/withdraw <monto> - Solicitar retiro",
            "/mystatus - Ver mi rol"
        ],
        "help_staff_title": "— Comandos de staff —",
        "help_staff": [
            "/addbalance <user_id> <monto> - Agregar saldo",
            "/setdaily <texto> - Fijar operación diaria"
        ],
        "help_admin_title": "— Comandos de admin —",
        "help_admin": [
            "/setbalance <user_id> <monto> - Fijar saldo",
            "/broadcast <texto> - Difusión",
            "/promote <user_id> - Promover a staff",
            "/demote <user_id> - Quitar de staff"
        ],
        "daily_none": "Aún no hay operación diaria.",
        "withdraw_enter": "❌ Formato: /withdraw 50",
        "withdraw_invalid": "❌ Monto inválido.",
        "withdraw_insufficient": "Saldo insuficiente. Tu saldo: {bal}$",
        "withdraw_created": "✅ Solicitud de retiro #{req_id} creada por {amount}$.",
        "lang_menu_title": "Elige tu idioma:",
        "lang_saved": "✅ Idioma cambiado a Español.",
        "choose_withdraw_amount": "🔢 Elige el monto a retirar:",
        "no_requests": "🚫 No hay solicitudes.",
        "requests_waiting": "💼 Tus solicitudes pendientes:",
        "cannot_cancel": "⚠️ No se puede cancelar esta solicitud.",
        "canceled": "❌ Solicitud cancelada. Se devolvieron {amount}$.",
        "approved_done": "👌 Hecho.",
        "rejected_done": "🚫 Rechazado y reembolsado.",
        "stats_none": "📊 No hay operaciones.",
        "stats_header": "📊 Tus estadísticas:\n\n",
        "stats_total": "\n✅ Ganancia total: {total}$",
        "enter_custom_withdraw": "💬 Escribe el monto que quieres retirar:",
        "min_withdraw": "❌ El mínimo es 10$.",
        "not_enough": "❌ Saldo insuficiente.",
        "enter_number": "❌ Ingresa un número válido.",
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
            "/withdraw <montant> - Demande de retrait",
            "/mystatus - Vérifier mon rôle"
        ],
        "help_staff_title": "— Commandes équipe —",
        "help_staff": [
            "/addbalance <user_id> <montant> - Ajouter du solde",
            "/setdaily <texte> - Définir le trade du jour",
            "/daily - Voir le trade du jour",
            "/withdraw <montant> - Créer une demande de retrait"
        ],
        "help_admin_title": "— Commandes admin —",
        "help_admin": [
            "/setbalance <user_id> <montant> - Définir le solde",
            "/broadcast <texte> - Diffusion",
            "/promote <user_id> - Promouvoir",
            "/demote <user_id> - Rétrograder"
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
    },
"de": {
        "welcome": "👋 Willkommen beim Trading-Bot\n\n💰 Dein Guthaben: {balance}$\n🆔 Deine ID: {uid}",
        "btn_daily": "📈 Tages-Trade",
        "btn_withdraw": "💸 Auszahlen",
        "btn_wstatus": "💼 Auszahlungsanträge",
        "btn_stats": "📊 Statistiken",
        "btn_lang": "🌐 Sprache",
        "help_title": "🛠 Verfügbare Befehle:",
        "help_public": [
            "/start - Hauptmenü",
            "/id - Zeige deine ID",
            "/balance - Dein Guthaben",
            "/daily - Tages-Trade",
            "/withdraw <Betrag> - Auszahlung anfordern",
            "/mystatus - Meine Rolle prüfen"
        ],
        "help_staff_title": "— Mitarbeiter-Befehle —",
        "help_staff": [
            "/addbalance <user_id> <betrag> - Guthaben hinzufügen",
            "/setdaily <Text> - Tages-Trade setzen"
        ],
        "help_admin_title": "— Admin-Befehle —",
        "help_admin": [
            "/setbalance <user_id> <betrag> - Guthaben setzen",
            "/broadcast <Text> - Rundsendung",
            "/promote <user_id> - Zum Staff befördern",
            "/demote <user_id> - Aus Staff entfernen"
        ],
        "daily_none": "Noch kein Tages-Trade.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Ungültiger Betrag.",
        "withdraw_insufficient": "Unzureichendes Guthaben. Dein Guthaben: {bal}$",
        "withdraw_created": "✅ Auszahlungsantrag #{req_id} über {amount}$ erstellt.",
        "lang_menu_title": "Wähle deine Sprache:",
        "lang_saved": "✅ Sprache auf Deutsch gestellt.",
        "choose_withdraw_amount": "🔢 Auszahlungsbetrag wählen:",
        "no_requests": "🚫 Keine Anträge.",
        "requests_waiting": "💼 Deine offenen Anträge:",
        "cannot_cancel": "⚠️ Antrag kann nicht storniert werden.",
        "canceled": "❌ Antrag storniert. {amount}$ erstattet.",
        "approved_done": "👌 Erledigt.",
        "rejected_done": "🚫 Abgelehnt und erstattet.",
        "stats_none": "📊 Keine Trades vorhanden.",
        "stats_header": "📊 Deine Statistiken:\n\n",
        "stats_total": "\n✅ Gesamtgewinn: {total}$",
        "enter_custom_withdraw": "💬 Gib den gewünschten Auszahlungsbetrag ein:",
        "min_withdraw": "❌ Minimum ist 10$.",
        "not_enough": "❌ Guthaben nicht ausreichend.",
        "enter_number": "❌ Bitte eine gültige Zahl eingeben.",
    },
    "ru": {
        "welcome": "👋 Добро пожаловать в трейдинг-бот\n\n💰 Ваш баланс: {balance}$\n🆔 Ваш ID: {uid}",
        "btn_daily": "📈 Сделка дня",
        "btn_withdraw": "💸 Вывод",
        "btn_wstatus": "💼 Заявки на вывод",
        "btn_stats": "📊 Статистика",
        "btn_lang": "🌐 Язык",
        "help_title": "🛠 Доступные команды:",
        "help_public": [
            "/start - Главное меню",
            "/id - Показать ваш ID",
            "/balance - Ваш баланс",
            "/daily - Сделка дня",
            "/withdraw <сумма> - Запрос на вывод",
            "/mystatus - Моя роль"
        ],
        "help_staff_title": "— Команды персонала —",
        "help_staff": [
            "/addbalance <user_id> <сумма> - Пополнить баланс",
            "/setdaily <текст> - Установить сделку дня"
        ],
        "help_admin_title": "— Команды админа —",
        "help_admin": [
            "/setbalance <user_id> <сумма> - Установить баланс",
            "/broadcast <текст> - Рассылка",
            "/promote <user_id> - Повысить до персонала",
            "/demote <user_id> - Снять с персонала"
        ],
        "daily_none": "Сделка дня пока отсутствует.",
        "withdraw_enter": "❌ Формат: /withdraw 50",
        "withdraw_invalid": "❌ Неверная сумма.",
        "withdraw_insufficient": "Недостаточно средств. Ваш баланс: {bal}$",
        "withdraw_created": "✅ Заявка на вывод #{req_id} создана на сумму {amount}$.",
        "lang_menu_title": "Выберите язык:",
        "lang_saved": "✅ Язык переключён на русский.",
        "choose_withdraw_amount": "🔢 Выберите сумму вывода:",
        "no_requests": "🚫 Заявок нет.",
        "requests_waiting": "💼 Ваши ожидающие заявки:",
        "cannot_cancel": "⚠️ Нельзя отменить эту заявку.",
        "canceled": "❌ Заявка отменена. Возвращено {amount}$.",
        "approved_done": "👌 Готово.",
        "rejected_done": "🚫 Отклонено и возвращено.",
        "stats_none": "📊 Сделок пока нет.",
        "stats_header": "📊 Ваша статистика:\n\n",
        "stats_total": "\n✅ Общая прибыль: {total}$",
        "enter_custom_withdraw": "💬 Укажите сумму для вывода:",
        "min_withdraw": "❌ Минимум 10$.",
        "not_enough": "❌ Недостаточно средств.",
        "enter_number": "❌ Введите корректное число.",
    },
}

def get_lang(uid: str) -> str:
    users = load_json("users.json") or {}
    lang = (users.get(uid, {}) or {}).get("lang", "en")
    return lang if lang in LANGS else "en"

def set_lang(uid: str, lang: str):
    users = load_json("users.json") or {}
    users.setdefault(uid, {"balance": 0})
    users[uid]["lang"] = lang if lang in LANGS else "en"
    save_json("users.json", users)

def T(uid: str, key: str, **kwargs) -> str:
    lang = get_lang(uid)
    s = TEXT.get(lang, TEXT["en"]).get(key, "")
    try:
        return s.format(**kwargs)
    except Exception:
        return s

# ========= Webhook =========
if WEBHOOK_BASE:
    try:
        bot.remove_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(
            url=f"{WEBHOOK_BASE}/{API_TOKEN}",
            allowed_updates=["message","callback_query","my_chat_member","chat_member","edited_message"]
        )
        print("Webhook set to:", f"{WEBHOOK_BASE}/{API_TOKEN}")
    except Exception as e:
        print("Failed to set webhook:", e)

# ========= صلاحيات =========
def _load_staff_set():
    data = load_json("staff.json") or {}
    ids = data.get("ids", [])
    try:
        return set(int(x) for x in ids)
    except Exception:
        return set()

def _save_staff_set(s):
    save_json("staff.json", {"ids": list(sorted(s))})

def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) == ADMIN_ID
    except Exception:
        return False

def is_staff(user_id: int) -> bool:
    return is_admin(user_id) or (int(user_id) in _load_staff_set())

# ========= واجهة =========
def ensure_user(chat_id: int) -> str:
    uid = str(chat_id)
    users = load_json("users.json") or {}
    if uid not in users:
        users[uid] = {"balance": 0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "lang": "en"}
        save_json("users.json", users)
    return uid

def main_menu_markup(uid: str):
    tt = TEXT[get_lang(uid)]
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton(tt["btn_daily"], callback_data="daily_trade"),
          types.InlineKeyboardButton(tt["btn_withdraw"], callback_data="withdraw_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_wstatus"], callback_data="withdraw_status"),
          types.InlineKeyboardButton(tt["btn_stats"], callback_data="stats"))
    m.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    return m

def show_main_menu(chat_id: int):
    uid = str(chat_id)
    users = load_json("users.json") or {}
    balance = users.get(uid, {}).get("balance", 0)
    bot.send_message(chat_id, T(uid, "welcome", balance=balance, uid=uid), reply_markup=main_menu_markup(uid))

# ========= Normalize & Parse =========
ZERO_WIDTH = "\u200f\u200e\u2066\u2067\u2068\u2069\u200b\uFEFF"
def norm_text(txt: str) -> str:
    if not txt: return ""
    t = txt.strip()
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    return t.replace("／", "/")

def parse_command(message):
    raw = norm_text(message.text or "")
    cmd_token = None
    try:
        for ent in (message.entities or []):
            if ent.type == "bot_command":
                cmd_token = raw[ent.offset: ent.offset + ent.length]
                break
    except Exception:
        pass
    if not cmd_token:
        parts = raw.split()
        cmd_token = parts[0] if parts else ""
    if cmd_token.startswith("／"):
        cmd_token = "/" + cmd_token[1:]
    token = cmd_token[1:] if cmd_token.startswith("/") else cmd_token
    if "@" in token:
        token = token.split("@", 1)[0]
    cmd = token.lower()
    args = raw[len(cmd_token):].strip()
    return cmd, args

# ========= هاندلر صريح لـ /start =========
@bot.message_handler(commands=['start'])
def _start_explicit(message):
    try:
        ensure_user(message.chat.id)
        show_main_menu(message.chat.id)
        print("START: delivered menu to", message.from_user.id)
    except Exception as e:
        print("start handler error:", e)

# ========= fallback لو كتب start بدون / =========
@bot.message_handler(func=lambda m: (m.text or "").strip().lower().startswith("start"))
def _start_fallback(m):
    try:
        ensure_user(m.chat.id)
        show_main_menu(m.chat.id)
        print("START-FALLBACK for", m.from_user.id)
    except Exception as e:
        print("start_fallback error:", e)

# ========= راوتر أوامر =========
@bot.message_handler(content_types=['text'])
def router(message):
    text_raw = message.text or ""
    uid = str(message.from_user.id)

    # لو مش أمر: نرسلها للأدمِن كتنبيه
    if not text_raw.strip().startswith(("/", "／")):
        try:
            bot.send_message(ADMIN_ID, f"📩 Message from {uid}:\n{text_raw}")
        except Exception as e:
            print("forward error:", e)
        return

    cmd, args = parse_command(message)
    print("ROUTER:", cmd, "| ARGS:", repr(args), "| FROM:", uid)

    # عام
    if cmd == "start":
        ensure_user(message.chat.id)
        return show_main_menu(message.chat.id)

    if cmd == "help":
        isA = is_admin(message.from_user.id)
        isS = is_staff(message.from_user.id)
        tt = TEXT[get_lang(uid)]
        lines = [tt["help_title"], *tt["help_public"]]
        if isS: lines += ["", tt["help_staff_title"], *tt["help_staff"]]
        if isA: lines += ["", tt["help_admin_title"], *tt["help_admin"]]
        return bot.reply_to(message, "\n".join(lines))

    if cmd == "id":
        return bot.reply_to(message, f"🆔 {uid}")

    if cmd == "balance":
        u = ensure_user(message.chat.id)
        users = load_json("users.json") or {}
        bal = users.get(u, {}).get("balance", 0)
        return bot.reply_to(message, f"💰 {bal}$")

    if cmd == "daily":
        u = str(message.chat.id)
        daily = load_json("daily_trade.txt") or TEXT[get_lang(u)]["daily_none"]
        return bot.reply_to(message, f"📈 {daily if isinstance(daily, str) else str(daily)}")

    if cmd == "withdraw":
        if not args or not args.lstrip("+").isdigit():
            return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_enter"])
        amount = int(args)
        if amount <= 0:
            return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_invalid"])
        u = ensure_user(message.chat.id)
        users = load_json("users.json") or {}
        bal = users.get(u, {}).get("balance", 0)
        if bal < amount:
            return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_insufficient"].format(bal=bal))
        users[u]["balance"] = bal - amount
        save_json("users.json", users)
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req_id = str(len(withdraw_requests) + 1)
        withdraw_requests[req_id] = {"user_id": u, "amount": amount, "status": "بانتظار الموافقة", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_json("withdraw_requests.json", withdraw_requests)
        return bot.reply_to(message, TEXT[get_lang(uid)]["withdraw_created"].format(req_id=req_id, amount=amount))

    # Staff/Admin
    if cmd == "setdaily":
        if not is_staff(message.from_user.id):
            return
        if not args:
            lc = get_lang(uid)
            txt = {
                "en": "❌ Format: /setdaily <text>",
                "ar": "❌ اكتب النص: /setdaily <النص>",
                "tr": "❌ Format: /setdaily <metin>",
                "es": "❌ Formato: /setdaily <texto>",
                "de": "❌ Format: /setdaily <Text>",
                "ru": "❌ Формат: /setdaily <текст>",
            }.get(lc, "❌ Format: /setdaily <text>")
            return bot.reply_to(message, txt)
        save_json("daily_trade.txt", args)
        conf = {
            "en": "Daily trade updated ✅",
            "ar": "تم تحديث صفقة اليوم ✅",
            "tr": "Günlük işlem güncellendi ✅",
            "es": "Operación diaria actualizada ✅",
            "de": "Tages-Trade aktualisiert ✅",
            "ru": "Сделка дня обновлена ✅",
        }[get_lang(uid)]
        return bot.reply_to(message, conf)

    if cmd == "addbalance":
        if not is_staff(message.from_user.id):
            return
        parts = args.split()
        if len(parts) != 2 or (not parts[0].isdigit()) or (not parts[1].lstrip("-").isdigit()):
            return bot.reply_to(message, {
                "en":"❌ Usage: /addbalance <user_id> <amount>",
                "ar":"❌ الاستخدام: /addbalance <user_id> <amount>",
                "tr":"❌ Kullanım: /addbalance <user_id> <tutar>",
                "es":"❌ Uso: /addbalance <user_id> <monto>",
                "de":"❌ Nutzung: /addbalance <user_id> <betrag>",
                "ru":"❌ Использование: /addbalance <user_id> <amount>",
            }[get_lang(uid)])
        uid_str, amount_str = parts
        amount = int(amount_str)
        users = load_json("users.json") or {}
        users.setdefault(uid_str, {"balance": 0})
        users[uid_str]["balance"] = users[uid_str].get("balance", 0) + amount
        save_json("users.json", users)
        return bot.reply_to(message, f"✅ {uid_str}: {users[uid_str]['balance']}$")

    if cmd == "setbalance":
        if not is_admin(message.from_user.id):
            return
        parts = args.split()
        if len(parts) != 2 or (not parts[0].isdigit()) or (not parts[1].lstrip("-").isdigit()):
            return bot.reply_to(message, "❌ usage: /setbalance <user_id> <amount>")
        uid_str, amount_str = parts
        amount = int(amount_str)
        users = load_json("users.json") or {}
        users.setdefault(uid_str, {"balance": 0})
        users[uid_str]["balance"] = amount
        save_json("users.json", users)
        return bot.reply_to(message, f"✅ {uid_str}: {amount}$")

    if cmd == "broadcast":
        if not is_admin(message.from_user.id):
            return
        if not args:
            return bot.reply_to(message, "❌ usage: /broadcast <text>")
        users = load_json("users.json") or {}
        text = args
        sent = 0
        for u in list(users.keys()):
            try:
                bot.send_message(int(u), text)
                sent += 1
            except Exception:
                pass
        return bot.reply_to(message, f"✅ sent to {sent}")

    if cmd == "promote":
        if not is_admin(message.from_user.id):
            return
        if not args or (not args.isdigit()):
            return bot.reply_to(message, "❌ usage: /promote <user_id>")
        uid2 = int(args)
        s = _load_staff_set(); s.add(uid2); _save_staff_set(s)
        return bot.reply_to(message, f"✅ promoted {uid2}")

    if cmd == "demote":
        if not is_admin(message.from_user.id):
            return
        if not args or (not args.isdigit()):
            return bot.reply_to(message, "❌ usage: /demote <user_id>")
        uid2 = int(args)
        s = _load_staff_set()
        if uid2 in s:
            s.remove(uid2); _save_staff_set(s)
            return bot.reply_to(message, f"✅ demoted {uid2}")
        else:
            return bot.reply_to(message, "not staff")

# ========= أزرار الكولباك =========
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    data = call.data or ""
    uid = str(call.from_user.id)
    print("CALLBACK:", data, "FROM:", uid)

    if data == "lang_menu":
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton("العربية 🇸🇦", callback_data="set_lang_ar"),
               types.InlineKeyboardButton("English 🇬🇧", callback_data="set_lang_en"))
        mm.add(types.InlineKeyboardButton("Türkçe 🇹🇷", callback_data="set_lang_tr"),
               types.InlineKeyboardButton("Español 🇪🇸", callback_data="set_lang_es"))
        mm.add(types.InlineKeyboardButton("Français 🇫🇷", callback_data="set_lang_fr"))
        mm.add(types.InlineKeyboardButton("Deutsch 🇩🇪", callback_data="set_lang_de"),
               types.InlineKeyboardButton("Русский 🇷🇺", callback_data="set_lang_ru"))
        return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=mm)

    if data.startswith("set_lang_"):
        code = data.split("_")[-1]
        mapping = {"en":"en","ar":"ar","tr":"tr","es":"es","de":"de","ru":"ru"}
        lang = mapping.get(code, "en")
        set_lang(uid, lang)
        confirm = {
            "en": TEXT["en"]["lang_saved"],
            "ar": TEXT["ar"]["lang_saved"],
            "tr": TEXT["tr"]["lang_saved"],
            "es": TEXT["es"]["lang_saved"],
            "de": TEXT["de"]["lang_saved"],
            "ru": TEXT["ru"]["lang_saved"],
            "fr": TEXT["fr"]["lang_saved"],
        }[lang]
        bot.send_message(call.message.chat.id, confirm)
        return show_main_menu(call.message.chat.id)

    if data == "daily_trade":
        daily = load_json("daily_trade.txt") or TEXT[get_lang(uid)]["daily_none"]
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"),
               types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, daily if isinstance(daily, str) else str(daily), reply_markup=mm)

    if data == "withdraw_menu":
        mm = types.InlineKeyboardMarkup()
        for amount in [10, 20, 30, 50, 100]:
            mm.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
        mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"))
        mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["choose_withdraw_amount"], reply_markup=mm)

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

    if data.startswith("withdraw_") and data not in ["withdraw_status", "withdraw_custom"]:
        users = load_json("users.json") or {}
        users.setdefault(uid, {"balance": 0})
        balance = users.get(uid, {}).get("balance", 0)
        amount = int(data.split("_")[1])
        if balance >= amount:
            users[uid]["balance"] = balance - amount
            save_json("users.json", users)
            _add_req_and_notify(uid, amount)
            return bot.send_message(call.message.chat.id, "✅")
        else:
            return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["not_enough"])

    if data == "withdraw_custom":
        bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["enter_custom_withdraw"])
        return bot.register_next_step_handler(call.message, process_custom_withdraw)

    if data.startswith("cancel_"):
        withdraw_requests = load_json("withdraw_requests.json") or {}
        users = load_json("users.json") or {}
        req_id = data.split("_")[1]
        req = withdraw_requests.get(req_id)
        if req and req["status"] == "بانتظار الموافقة":
            amount = req["amount"]
            users.setdefault(uid, {"balance": 0})
            users[uid]["balance"] = users[uid].get("balance", 0) + amount
            req["status"] = "ملغي"
            save_json("withdraw_requests.json", withdraw_requests)
            save_json("users.json", users)
            return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["canceled"].format(amount=amount))
        else:
            return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["cannot_cancel"])

    if data == "stats":
        trades = load_json("trades.json") or {}
        user_trades = trades.get(uid, [])
        if not user_trades:
            return bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["stats_none"])
        total = 0
        txt = TEXT[get_lang(uid)]["stats_header"]
        for i, t in enumerate(user_trades, 1):
            txt += f"{i}- {t['date']} | {t['profit']}$\n"
            total += t['profit']
        txt += TEXT[get_lang(uid)]["stats_total"].format(total=total)
        return bot.send_message(call.message.chat.id, txt)

    if data == "go_back":
        return show_main_menu(call.message.chat.id)

def _add_req_and_notify(uid: str, amount: int):
    withdraw_requests = load_json("withdraw_requests.json") or {}
    req_id = str(len(withdraw_requests) + 1)
    withdraw_requests[req_id] = {"user_id": uid, "amount": amount, "status": "بانتظار الموافقة", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    save_json("withdraw_requests.json", withdraw_requests)
    mm = types.InlineKeyboardMarkup()
    mm.add(types.InlineKeyboardButton(f"✅ قبول {req_id}", callback_data=f"approve_{req_id}"),
           types.InlineKeyboardButton(f"❌ رفض {req_id}", callback_data=f"reject_{req_id}"))
    try:
        bot.send_message(ADMIN_ID, f"🔔 طلب سحب جديد:\nمستخدم: {uid}\nالمبلغ: {amount}$", reply_markup=mm)
    except Exception as e:
        print("notify admin error:", e)

def process_custom_withdraw(message):
    uid = str(message.chat.id)
    users = load_json("users.json") or {}
    users.setdefault(uid, {"balance": 0})
    balance = users.get(uid, {}).get("balance", 0)
    try:
        amount = int((message.text or "").strip())
        if amount < 10:
            bot.send_message(message.chat.id, TEXT[get_lang(uid)]["min_withdraw"])
        elif balance >= amount:
            users[uid]["balance"] = balance - amount
            save_json("users.json", users)
            _add_req_and_notify(uid, amount)
            bot.send_message(message.chat.id, "✅")
        else:
            bot.send_message(message.chat.id, TEXT[get_lang(uid)]["not_enough"])
    except:
        bot.send_message(message.chat.id, TEXT[get_lang(uid)]["enter_number"])

# ========= Flask Webhook =========
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route(f"/{API_TOKEN}", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200
    try:
        data = request.get_json(silent=True)
        if not data:
            raw = request.get_data().decode("utf-8", errors="ignore")
            print("WEBHOOK RAW (no json):", raw[:400])
            import json as _json
            try:
                data = _json.loads(raw)
            except Exception:
                return "OK", 200
        print("UPDATE KEYS:", list(data.keys()))
        import json as _json
        update = telebot.types.Update.de_json(_json.dumps(data))
        bot.process_new_updates([update])
    except Exception as e:
        print("Webhook error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
