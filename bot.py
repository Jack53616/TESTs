# -*- coding: utf-8 -*-
"""
Telegram bot (Render-ready) — Subscription Keys + Buy button + i18n
- Shows balance then remaining subscription time on a separate line.
- Subscription keys (daily/weekly/monthly/yearly/lifetime)
- Admin: /genkey, /delkey, /delsub, /subinfo
- On /start asks for key if user not subscribed (or expired)
- "🛒 Buy" button opens support chat (@qlsupport) when subscription inactive + Language button
- i18n (ar/en/tr/es/fr)
- Main menu: Daily / Withdraw / Withdrawal requests / Stats / Deposit / Language / Website / Support
- Withdraw via buttons or /withdraw <amount>
- Storage: DB (db_kv.py) if DATABASE_URL, else JSON files
- Webhook via Flask (Render)
"""
import os, json, logging, random, string, re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
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
    "users": "users.json",
    "withdraw_requests": "withdraw_requests.json",
    "withdraw_log": "withdraw_log.json",
    "trades": "trades.json",
    "keys": "keys.json",
}

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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _now() -> datetime:
    return datetime.now()

def _now_str() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")

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
        f.write((text or "").strip())

# ---------- Subscription Keys ----------
DURATIONS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "yearly": 365,
    "lifetime": None,
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
    if exp is None:  # lifetime
        return True
    try:
        return datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") > _now()
    except Exception:
        return False

def sub_remaining_str(uid: str) -> str:
    """Return remaining time string: 3d 4h 12m 05s / ∞ / 0s."""
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
        "need_key": "🔑 الرجاء إدخال مفتاح الاشتراك لتفعيل البوت.\nأنواع المفاتيح: يومي / أسبوعي / شهري / سنوي / دائم",
        "key_ok": "✅ تم تفعيل اشتراكك ({stype}). ينتهي في: {exp}\nاستخدم /start لفتح القائمة.",
        "key_ok_life": "✅ تم تفعيل اشتراكك ({stype} — دائم). استمتع!\nاستخدم /start لفتح القائمة.",
        "key_invalid": "❌ مفتاح غير صالح أو مستخدم مسبقاً. حاول مرة أخرى.",
        "key_expired": "⛔ انتهى اشتراكك. الرجاء إدخال مفتاح جديد للتجديد.",
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
            "/id - عرض آيديك",
            "/balance - رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw &lt;amount&gt; - طلب سحب (مثال: /withdraw 50)",
            "/mystats - إحصائياتي",
            "/genkey &lt;type&gt; [count] - توليد مفاتيح (أدمن)"
        ],
        "daily_none": "لا يوجد صفقة اليوم حالياً.",
        "cleardaily_ok": "🧹 تم مسح صفقة اليوم.",
        "withdraw_enter": "❌ الصيغة: /withdraw 50",
        "withdraw_invalid": "❌ مبلغ غير صالح.",
        "withdraw_insufficient": "الرصيد غير كافٍ. رصيدك: {bal}$",
        "withdraw_created": "✅ تم إنشاء طلب سحب #{req_id} بقيمة {amount}$.",
        "lang_menu_title": "اختر لغتك:",
        "lang_saved": "✅ تم ضبط اللغة العربية.",
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
        "genkey_ok": "✅ تم توليد {n} مفتاح من نوع {t}.\nأول مفتاح:\n<code>{first}</code>",
        "delkey_ok": "🗑️ تم حذف المفتاح.",
        "delkey_not_found": "❌ المفتاح غير موجود.",
        "delsub_ok": "🗑️ تم حذف اشتراك المستخدم {uid}.",
        "delsub_not_found": "ℹ️ لا يوجد اشتراك محفوظ لهذا المستخدم.",
        "subinfo_none": "ℹ️ لا يوجد اشتراك.",
        "subinfo_line": "📄 النوع: {t}\n🕒 الانتهاء: {exp}",
    },
    "en": {
        "welcome": "👋 Welcome to the trading bot\n\n💰 Your balance: {balance}$\n⏳ Subscription ends in: {remain}\n🆔 Your ID: {user_id}",
        "need_key": "🔑 Please enter your subscription key to activate the bot.\nTypes: daily / weekly / monthly / yearly / lifetime",
        "key_ok": "✅ Your subscription ({stype}) is activated. Expires at: {exp}\nUse /start to open the menu.",
        "key_ok_life": "✅ Your subscription ({stype}, lifetime) is activated. Enjoy!\nUse /start to open the menu.",
        "key_invalid": "❌ Invalid or already used key. Try again.",
        "key_expired": "⛔ Your subscription has expired. Please enter a new key.",
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
            "/id - Show your ID",
            "/balance - Your balance",
            "/daily - Daily trade",
            "/withdraw &lt;amount&gt; - Request withdrawal",
            "/mystats - My stats",
            "/genkey &lt;type&gt; [count] - generate keys (admin)"
        ],
        "daily_none": "No daily trade yet.",
        "cleardaily_ok": "🧹 Daily trade cleared.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Invalid amount.",
        "withdraw_insufficient": "Insufficient balance. Your balance: {bal}$",
        "withdraw_created": "✅ Withdrawal request #{req_id} created for {amount}$.",
        "lang_menu_title": "Choose your language:",
        "lang_saved": "✅ Language set to English.",
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
        "stats_title": "📊 Your statistics",
        "stats_wins": "✅ Wins: {sum}$ (count: {count})",
        "stats_losses": "❌ Losses: {sum}$ (count: {count})",
        "stats_net": "⚖️ Net: {net}$",
        "stats_no_data": "No operations yet.",
        "stats_line_win": "{at} — Win +{amount}$",
        "stats_line_loss": "{at} — Loss -{amount}$",
        "admin_only": "⚠️ Admins only.",
        "genkey_ok": "✅ Generated {n} key(s) of type {t}.\nFirst key:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Key deleted.",
        "delkey_not_found": "❌ Key not found.",
        "delsub_ok": "🗑️ Subscription removed for user {uid}.",
        "delsub_not_found": "ℹ️ No subscription recorded for this user.",
        "subinfo_none": "ℹ️ No subscription.",
        "subinfo_line": "📄 Type: {t}\n🕒 Expires: {exp}",
    },
    "tr": {
        "welcome": "👋 Trading botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n⏳ Abonelik bitimine: {remain}\n🆔 ID: {user_id}",
        "need_key": "🔑 Botu etkinleştirmek için abonelik anahtarını gir.\nTürler: günlük / haftalık / aylık / yıllık / ömür boyu",
        "key_ok": "✅ Aboneliğin ({stype}) etkin. Bitiş: {exp}\nMenü için /start.",
        "key_ok_life": "✅ Abonelik ({stype}, ömür boyu) etkin. Keyfini çıkar!\nMenü için /start.",
        "key_invalid": "❌ Geçersiz ya da kullanılmış anahtar. Tekrar dene.",
        "key_expired": "⛔ Aboneliğin bitti. Lütfen yeni anahtar gir.",
        "btn_daily": "📈 Günün işlemi",
        "btn_withdraw": "💸 Çekim",
        "btn_wstatus": "💼 Çekim talepleri",
        "btn_stats": "📊 İstatistikler",
        "btn_lang": "🌐 Dil",
        "btn_deposit": "💳 Yatırma",
        "btn_website": "🌍 Web sitemiz",
        "btn_support": "📞 Destek ile iletişim",
        "btn_buy": "🛒 Abonelik satın al",
        "help_title": "🛠 Kullanılabilir komutlar:",
        "help_public": [
            "/start - Ana menü",
            "/id - ID'ni göster",
            "/balance - Bakiyen",
            "/daily - Günün işlemi",
            "/withdraw &lt;tutar&gt; - Çekim isteği",
            "/mystats - İstatistiklerim",
            "/genkey &lt;type&gt; [count] - anahtar üret (admin)"
        ],
        "daily_none": "Henüz günlük işlem yok.",
        "cleardaily_ok": "🧹 Günlük işlem temizlendi.",
        "withdraw_enter": "❌ Format: /withdraw 50",
        "withdraw_invalid": "❌ Geçersiz tutar.",
        "withdraw_insufficient": "Yetersiz bakiye. Bakiyen: {bal}$",
        "withdraw_created": "✅ #{req_id} numaralı çekim talebi {amount}$ için oluşturuldu.",
        "lang_menu_title": "Dilini seç:",
        "lang_saved": "✅ Dil Türkçe olarak ayarlandı.",
        "choose_withdraw_amount": "Çekim tutarını seç:",
        "requests_waiting": "Bekleyen taleplerin:",
        "no_requests": "Bekleyen talep yok.",
        "deposit_choose": "Bir yatırma yöntemi seç:",
        "deposit_cash": "💵 Nakit",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Banka Havalesi",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "{method} ile ödeme için lütfen doğrudan bizimle iletişime geçin. Aşağıya dokunun:",
        "contact_us": "📩 Bizimle iletişim",
        "website_msg": "🔥 Web sitemizi ziyaret etmek için dokunun:",
        "website_not_set": "ℹ️ Website URL henüz ayarlı değil.",
        "support_msg": "Destek ile iletişim için aşağı dokunun:",
        "stats_title": "📊 İstatistiklerin",
        "stats_wins": "✅ Kazançlar: {sum}$ (adet: {count})",
        "stats_losses": "❌ Kayıplar: {sum}$ (adet: {count})",
        "stats_net": "⚖️ Net: {net}$",
        "stats_no_data": "Henüz işlem yok.",
        "stats_line_win": "{at} — Kazanç +{amount}$",
        "stats_line_loss": "{at} — Kayıp -{amount}$",
        "admin_only": "⚠️ Sadece admin.",
        "genkey_ok": "✅ {t} türünden {n} anahtar üretildi.\nİlk anahtar:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Anahtar silindi.",
        "delkey_not_found": "❌ Anahtar bulunamadı.",
        "delsub_ok": "🗑️ {uid} kullanıcısının aboneliği silindi.",
        "delsub_not_found": "ℹ️ Bu kullanıcı için abonelik bulunmuyor.",
        "subinfo_none": "ℹ️ Abonelik yok.",
        "subinfo_line": "📄 Tür: {t}\n🕒 Bitiş: {exp}",
    },
    "es": {
        "welcome": "👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n⏳ La suscripción termina en: {remain}\n🆔 Tu ID: {user_id}",
        "need_key": "🔑 Ingresa tu clave de suscripción para activar el bot.\nTipos: diario / semanal / mensual / anual / de por vida",
        "key_ok": "✅ Tu suscripción ({stype}) está activa. Expira: {exp}\nUsa /start para abrir el menú.",
        "key_ok_life": "✅ Suscripción ({stype}, de por vida) activada. ¡Disfruta!\nUsa /start para abrir el menú.",
        "key_invalid": "❌ Clave inválida o ya usada. Intenta de nuevo.",
        "key_expired": "⛔ Tu suscripción expiró. Ingresa una nueva clave.",
        "btn_daily": "📈 Operación del día",
        "btn_withdraw": "💸 Retirar",
        "btn_wstatus": "💼 Solicitudes de retiro",
        "btn_stats": "📊 Estadísticas",
        "btn_lang": "🌐 Idioma",
        "btn_deposit": "💳 Depósito",
        "btn_website": "🌍 Sitio web",
        "btn_support": "📞 Contactar soporte",
        "btn_buy": "🛒 Comprar suscripción",
        "help_title": "🛠 Comandos disponibles:",
        "help_public": [
            "/start - Menú principal",
            "/id - Mostrar tu ID",
            "/balance - Tu saldo",
            "/daily - Operación del día",
            "/withdraw &lt;monto&gt; - Solicitar retiro",
            "/mystats - Mis estadísticas",
            "/genkey &lt;type&gt; [count] - generar claves (admin)"
        ],
        "daily_none": "Aún no hay operación del día.",
        "cleardaily_ok": "🧹 Operación del día eliminada.",
        "withdraw_enter": "❌ Formato: /withdraw 50",
        "withdraw_invalid": "❌ Monto inválido.",
        "withdraw_insufficient": "Saldo insuficiente. Tu saldo: {bal}$",
        "withdraw_created": "✅ Solicitud #{req_id} creada por {amount}$.",
        "lang_menu_title": "Elige tu idioma:",
        "lang_saved": "✅ Idioma configurado a español.",
        "choose_withdraw_amount": "Elige el monto a retirar:",
        "requests_waiting": "Tus solicitudes pendientes:",
        "no_requests": "No hay solicitudes pendientes.",
        "deposit_choose": "Elige un método de depósito:",
        "deposit_cash": "💵 Efectivo",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Transferencia bancaria",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "Para pagar con {method}, contáctanos directamente. Pulsa abajo:",
        "contact_us": "📩 Contáctanos",
        "website_msg": "🔥 Pulsa para visitar nuestro sitio:",
        "website_not_set": "ℹ️ La URL del sitio aún no está configurada.",
        "support_msg": "Pulsa abajo para contactar soporte:",
        "stats_title": "📊 Tus estadísticas",
        "stats_wins": "✅ Ganancias: {sum}$ (conteo: {count})",
        "stats_losses": "❌ Pérdidas: {sum}$ (conteo: {count})",
        "stats_net": "⚖️ Neto: {net}$",
        "stats_no_data": "Aún no hay operaciones.",
        "stats_line_win": "{at} — Ganancia +{amount}$",
        "stats_line_loss": "{at} — Pérdida -{amount}$",
        "admin_only": "⚠️ Solo para administradores.",
        "genkey_ok": "✅ Generadas {n} claves tipo {t}.\nPrimera clave:\n<code>{first}</code>",
        "delkey_ok": "🗑️ Clave eliminada.",
        "delkey_not_found": "❌ Clave no encontrada.",
        "delsub_ok": "🗑️ Suscripción eliminada para el usuario {uid}.",
        "delsub_not_found": "ℹ️ No hay suscripción registrada para este usuario.",
        "subinfo_none": "ℹ️ Sin suscripción.",
        "subinfo_line": "📄 Tipo: {t}\n🕒 Expira: {exp}",
    },
    "fr": {
        "welcome": "👋 Bienvenue dans le bot de trading\n\n💰 Votre solde : {balance}$\n⏳ L’abonnement se termine dans : {remain}\n🆔 Votre ID : {user_id}",
        "need_key": "🔑 Veuillez saisir votre clé d’abonnement pour activer le bot.\nTypes : quotidien / hebdomadaire / mensuel / annuel / à vie",
        "key_ok": "✅ Votre abonnement ({stype}) est activé. Expire : {exp}\nUtilisez /start pour ouvrir le menu.",
        "key_ok_life": "✅ Abonnement ({stype}, à vie) activé. Profitez-en !\nUtilisez /start pour ouvrir le menu.",
        "key_invalid": "❌ Clé invalide ou déjà utilisée. Réessayez.",
        "key_expired": "⛔ Votre abonnement a expiré. Veuillez saisir une nouvelle clé.",
        "btn_daily": "📈 Trade du jour",
        "btn_withdraw": "💸 Retrait",
        "btn_wstatus": "💼 Demandes de retrait",
        "btn_stats": "📊 Statistiques",
        "btn_lang": "🌐 Langue",
        "btn_deposit": "💳 Dépôt",
        "btn_website": "🌍 Site web",
        "btn_support": "📞 Contacter le support",
        "btn_buy": "🛒 Acheter un abonnement",
        "help_title": "🛠 Commandes disponibles :",
        "help_public": [
            "/start - Menu principal",
            "/id - Afficher votre ID",
            "/balance - Votre solde",
            "/daily - Trade du jour",
            "/withdraw &lt;montant&gt; - Demander un retrait",
            "/mystats - Mes statistiques",
            "/genkey &lt;type&gt; [count] - générer des clés (admin)"
        ],
        "daily_none": "Aucun trade du jour pour le moment.",
        "cleardaily_ok": "🧹 Trade du jour effacé.",
        "withdraw_enter": "❌ Format : /withdraw 50",
        "withdraw_invalid": "❌ Montant invalide.",
        "withdraw_insufficient": "Solde insuffisant. Votre solde : {bal}$",
        "withdraw_created": "✅ Demande #{req_id} créée pour {amount}$.",
        "lang_menu_title": "Sélectionnez votre langue :",
        "lang_saved": "✅ Langue définie sur le français.",
        "choose_withdraw_amount": "Choisissez le montant du retrait :",
        "requests_waiting": "Vos demandes en attente :",
        "no_requests": "Aucune demande en attente.",
        "deposit_choose": "Choisissez une méthode de dépôt :",
        "deposit_cash": "💵 Espèces",
        "deposit_paypal": "🅿️ PayPal",
        "deposit_bank": "🏦 Virement bancaire",
        "deposit_mc": "💳 Mastercard",
        "deposit_visa": "💳 Visa",
        "deposit_msg": "Pour payer via {method}, contactez-nous directement. Appuyez ci-dessous :",
        "contact_us": "📩 Nous contacter",
        "website_msg": "🔥 Appuyez pour visiter notre site :",
        "website_not_set": "ℹ️ L’URL du site n’est pas encore définie.",
        "support_msg": "Appuyez ci-dessous pour contacter le support :",
        "stats_title": "📊 Vos statistiques",
        "stats_wins": "✅ Gains : {sum}$ (nombre : {count})",
        "stats_losses": "❌ Pertes : {sum}$ (nombre : {count})",
        "stats_net": "⚖️ Net : {net}$",
        "stats_no_data": "Aucune opération pour le moment.",
        "stats_line_win": "{at} — Gain +{amount}$",
        "stats_line_loss": "{at} — Perte -{amount}$",
        "admin_only": "⚠️ Réservé aux administrateurs.",
        "genkey_ok": "✅ {n} clé(s) de type {t} générée(s).\nPremière clé :\n<code>{first}</code>",
        "delkey_ok": "🗑️ Clé supprimée.",
        "delkey_not_found": "❌ Clé introuvable.",
        "delsub_ok": "🗑️ Abonnement supprimé pour l’utilisateur {uid}.",
        "delsub_not_found": "ℹ️ Aucun abonnement enregistré pour cet utilisateur.",
        "subinfo_none": "ℹ️ Aucun abonnement.",
        "subinfo_line": "📄 Type : {t}\n🕒 Expire : {exp}",
    }
}

def get_lang(uid: str) -> str:
    users = load_json("users.json") or {}
    lang = (users.get(uid, {}) or {}).get("lang", "ar")
    return lang if lang in LANGS else "ar"

def set_lang(uid: str, lang: str) -> None:
    users = load_json("users.json") or {}
    users.setdefault(uid, {"balance": 0, "role": "user", "created_at": _now_str(), "lang": "ar"})
    users[uid]["lang"] = lang if lang in LANGS else "ar"
    save_json("users.json", users)

def T(user_uid: str, key: str, **kwargs) -> str:
    lang = get_lang(user_uid)
    s = TEXT.get(lang, TEXT["ar"]).get(key, "")
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
            "lang": "ar"
        }
        save_json("users.json", users)
    else:
        # upgrade to admin if now in ADMIN_IDS
        if chat_id in ADMIN_IDS and users.get(uid, {}).get("role") != "admin":
            users[uid]["role"] = "admin"
            save_json("users.json", users)
    return uid

def is_admin(uid: str) -> bool:
    try:
        # quick check: if uid numeric and belongs to ADMIN_IDS
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
    """Return True if active; else ask for key (with Buy + Language) and return False."""
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

    tt = TEXT[get_lang(uid)]
    msg = T(uid, "key_expired") if users.get(uid, {}).get("sub") else T(uid, "need_key")

    show_need_key_prompt(chat_id, uid)
    return False



def show_need_key_prompt(chat_id: int, uid: str):
    """Show the 'enter key' prompt with Buy+Language buttons (for inactive users)."""
    tt = TEXT[get_lang(uid)]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport"))
    kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    msg = T(uid, "key_expired") if (load_json("users.json") or {}).get(uid, {}).get("sub") else T(uid, "need_key")
    bot.send_message(chat_id, msg, reply_markup=kb)


def _rand_key(n=4) -> str:
    import random, string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def generate_keys(k_type: str, count: int) -> List[str]:
    keys = _key_store()
    out: List[str] = []
    for _ in range(count):
        while True:
            k = f"{k_type[:2].upper()}-{_rand_key()}-{_rand_key()}-{_rand_key()}"
            if k not in keys:
                break
        keys[k] = {"type": k_type, "created_at": _now_str()}
        out.append(k)
    _save_keys(keys)
    return out

def activate_key_for_user(uid: str, key: str) -> Optional[str]:
    """Try to activate key. Return localized success msg; None if invalid."""
    keys = _key_store()
    meta = keys.get(key)
    if not meta or meta.get("used_by"):
        return None

    ktype = meta.get("type")
    days = DURATIONS.get(ktype)

    users = load_json("users.json") or {}
    users.setdefault(uid, {})

    if days is None:  # lifetime
        exp = None
        users[uid]["sub"] = {"type": ktype, "expire_at": exp, "key": key}
        users[uid]["await_key"] = False
        keys[key]["used_by"] = uid
        keys[key]["used_at"] = _now_str()
        _save_keys(keys)
        save_json("users.json", users)
        return T(uid, "key_ok_life", stype=ktype)
    else:
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
    if not require_active_or_ask(message.chat.id):
        return
    tt = TEXT[get_lang(uid)]
    bot.reply_to(message, "\n".join([tt["help_title"], *tt["help_public"]]))

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
    daily = load_daily_text() or TEXT[get_lang(uid)]["daily_none"]
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

# ----- Admin: keys & subs -----
@bot.message_handler(commands=["genkey"])
def cmd_genkey(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))

    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /genkey <daily|weekly|monthly|yearly|lifetime> [count]")
    ktype = parts[1].lower()
    if ktype not in DURATIONS:
        return bot.reply_to(message, "Usage: /genkey <daily|weekly|monthly|yearly|lifetime> [count]")
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
    exp = sub.get("expire_at", "∞")
    return bot.reply_to(message, T(uid, "subinfo_line", t=t, exp=exp))

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
        "created_at": _now_str()
    }
    save_json("withdraw_requests.json", withdraw_requests)
    return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_created"].format(req_id=req_id, amount=amount))

# ---------- Callbacks ----------


# --- Language callbacks (specific handlers, run before generic) ---
@bot.callback_query_handler(func=lambda c: c.data=="lang_menu")
def cb_lang_menu(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=build_lang_kb())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("set_lang_"))
def cb_set_lang(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    code = (call.data or "").split("_")[-1]
    if code in ("ar","en","tr","es","fr"):
        set_lang(uid, code)
    try:
        bot.answer_callback_query(call.id, text="Language updated")
    except Exception:
        pass
    try:
        bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_saved"])
    except Exception:
        pass
    try:
        show_main_menu(call.message.chat.id)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    uid = ensure_user(call.from_user.id)
    data = call.data or ""
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data.startswith("set_lang_"):
        code = data.split("_")[-1]
        if code in ("ar","en","tr","es","fr"):
            set_lang(uid, code)
            try:
                bot.send_message(call.message.chat.id, TEXT[get_lang(uid)]["lang_saved"])
            except Exception:
                pass
            try:
                show_main_menu(call.message.chat.id)
            except Exception:
                pass
        return

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
            if req.get("user_id") == uid and req.get("status") == "بانتظار الموافقة":
                mm.add(types.InlineKeyboardButton(f"❌ cancel {req.get('amount',0)}$", callback_data=f"cancel_{req_id}"))
                found = True
        mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        msg = TEXT[get_lang(uid)]["requests_waiting"] if found else TEXT[get_lang(uid)]["no_requests"]
        return bot.send_message(call.message.chat.id, msg, reply_markup=mm)

    if data.startswith("withdraw_"):
        try:
            amount = int(data.split("_", 1)[1])
        except Exception:
            amount = 0
        return create_withdraw_request(call.message.chat.id, uid, amount)

    if data.startswith("cancel_"):
        req_id = data.split("_", 1)[1]
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req = withdraw_requests.get(req_id)
        if req and req.get("user_id") == uid and req.get("status") == "بانتظار الموافقة":
            users = load_json("users.json") or {}
            users.setdefault(uid, {"balance": 0})
            users[uid]["balance"] = users[uid].get("balance", 0) + int(req.get("amount", 0))
            save_json("users.json", users)
            req["status"] = "ملغاة"
            save_json("withdraw_requests.json", withdraw_requests)
            return bot.send_message(call.message.chat.id, f"❎ Canceled request #{req_id}")
        return bot.send_message(call.message.chat.id, "Nothing to cancel.")

    if data == "stats":
        txt = _stats_text(uid, uid)
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"),
               types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, txt, reply_markup=mm)

    if data == "deposit":
        tt = TEXT[get_lang(uid)]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["deposit_cash"], callback_data="dep_cash"))
        kb.add(types.InlineKeyboardButton(tt["deposit_paypal"], callback_data="dep_paypal"))
        kb.add(types.InlineKeyboardButton(tt["deposit_bank"], callback_data="dep_bank"))
        kb.add(types.InlineKeyboardButton(tt["deposit_mc"], callback_data="dep_mc"))
        kb.add(types.InlineKeyboardButton(tt["deposit_visa"], callback_data="dep_visa"))
        kb.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, tt["deposit_choose"], reply_markup=kb)

    if data.startswith("dep_"):
        tt = TEXT[get_lang(uid)]
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
        kb.add(types.InlineKeyboardButton("🔙", callback_data="deposit"))
        return bot.send_message(call.message.chat.id, tt["deposit_msg"].format(method=method), reply_markup=kb)

    if data == "website":
        tt = TEXT[get_lang(uid)]
        if WEBSITE_URL:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(tt["btn_website"], url=WEBSITE_URL))
            return bot.send_message(call.message.chat.id, tt["website_msg"], reply_markup=kb)
        else:
            return bot.send_message(call.message.chat.id, tt["website_not_set"])

    if data == "support":
        tt = TEXT[get_lang(uid)]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["contact_us"], url="https://t.me/qlsupport"))
        return bot.send_message(call.message.chat.id, tt["support_msg"], reply_markup=kb)

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
    if cmd.startswith("/daily") or cmd == "daily":
        return cmd_daily(message)
    if cmd.startswith("/withdraw") or cmd == "withdraw":
        return cmd_withdraw(message)

    # --- New commands passthrough ---
    if cmd in ("/broadcast", "broadcast"):
        return cmd_broadcast(message)
    if cmd in ("/addmoney", "/finemoney", "addmoney", "finemoney"):
        return cmd_money(message)
    if cmd in ("/setdaily", "setdaily"):
        return cmd_setdaily(message)
    if cmd in ("/cleardaily", "cleardaily"):
        return cmd_cleardaily(message)
    if cmd in ("/win", "win", "/loss", "loss"):
        return cmd_win_loss(message)
    if cmd in ("/record_set", "record_set"):
        return cmd_record_set(message)
    if cmd in ("/record_done", "record_done", "/cancel", "cancel"):
        # let cancel handler run; fallback to calling it here
        try:
            return cmd_cancel(message)
        except Exception:
            return
    if cmd in ("/mystats", "mystats"):
        return cmd_mystats(message)
    if cmd in ("/userstats", "userstats"):
        return cmd_userstats(message)
    return


@bot.message_handler(func=lambda m: bool(m.text and m.text.strip().startswith(("/", "／", "⁄"))))
def any_command_like(message: types.Message):
    try:
        return dispatch_command(message)
    except Exception as e:
        log.error("fallback dispatch error: %s", e)



# ---------- Broadcast, Money, Daily, and Stats (per-user) ----------

# In-memory state for admin broadcast and record mode; persisted record mode also saved to users.json meta if needed.
_BROADCAST_WAIT = set()          # admins waiting to send photo with caption
_RECORD_MODE = {}                # admin_id -> target_user_id (str)

def _all_user_ids() -> list:
    users = load_json("users.json") or {}
    return [int(uid) for uid in users.keys()]

def _get_stats():
    return load_json("stats.json") or {}

def _save_stats(data):
    save_json("stats.json", data)

def _add_stat(user_id: str, kind: str, amount: float):
    stats = _get_stats()
    u = stats.setdefault(user_id, {"total_win": 0.0, "total_loss": 0.0, "history": []})
    if kind == "win":
        u["total_win"] = float(u.get("total_win", 0.0)) + float(amount)
    else:
        u["total_loss"] = float(u.get("total_loss", 0.0)) + float(amount)
    u["history"].insert(0, {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "kind": kind,
        "amount": float(amount),
    })
    u["history"] = u["history"][:100]  # keep last 100
    _save_stats(stats)
    return u

def _stats_text(uid_viewer: str, target_uid: str):
    stats = _get_stats()
    u = stats.get(target_uid, {"total_win": 0.0, "total_loss": 0.0, "history": []})
    total_win = float(u.get("total_win", 0.0))
    total_loss = float(u.get("total_loss", 0.0))
    cnt_win = sum(1 for h in u.get("history", []) if h.get("kind") == "win")
    cnt_loss = sum(1 for h in u.get("history", []) if h.get("kind") == "loss")
    net = total_win - total_loss
    header = T(uid_viewer, "stats_title") if uid_viewer == target_uid else f"📊 إحصائيات المستخدم {target_uid}"
    lines = [header,
             T(uid_viewer, "stats_wins", sum=f"{total_win:.2f}", count=cnt_win),
             T(uid_viewer, "stats_losses", sum=f"{total_loss:.2f}", count=cnt_loss),
             T(uid_viewer, "stats_net", net=f"{net:.2f}")
    ]
    if not u.get("history"):
        lines.append(T(uid_viewer, "stats_no_data"))
    else:
        for h in u["history"][:10]:
            at = str(h.get("ts","")) .replace("T"," ")
            amount_str = f"{float(h.get('amount',0)):.2f}"
            if h.get("kind") == "win":
                lines.append(T(uid_viewer, "stats_line_win", at=at, amount=amount_str))
            else:
                lines.append(T(uid_viewer, "stats_line_loss", at=at, amount=amount_str))
    return "\n".join(lines)
# ---- /broadcast ----
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    _BROADCAST_WAIT.add(message.from_user.id)
    return bot.reply_to(message, "📣 ابعت «صورة مع كابتشن» لإرسالها للجميع.\nاكتب /cancel للإلغاء.")

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message: types.Message):
    if message.from_user.id in _BROADCAST_WAIT:
        _BROADCAST_WAIT.discard(message.from_user.id)
        return bot.reply_to(message, "✅ تم الإلغاء.")
    if _RECORD_MODE.get(message.from_user.id):
        _RECORD_MODE.pop(message.from_user.id, None)
        return bot.reply_to(message, "✅ خرجت من وضع التسجيل.")
    # else ignore

@bot.message_handler(content_types=["photo"])
def handle_photo(message: types.Message):
    # handle broadcast photo+caption
    uid = ensure_user(message.chat.id)
    if message.from_user.id in _BROADCAST_WAIT and is_admin(uid):
        _BROADCAST_WAIT.discard(message.from_user.id)
        users = _all_user_ids()
        if not users:
            return bot.reply_to(message, "⚠️ ما في مستخدمين لإرسال الرسالة.")
        # send by file_id to each
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
        sent = 0
        for cid in users:
            try:
                bot.send_photo(cid, file_id, caption=caption)
                sent += 1
            except Exception:
                pass
        return bot.reply_to(message, f"✅ تم الإرسال للجميع: {sent} مستخدم.")


@bot.message_handler(func=lambda m: m.from_user.id in _BROADCAST_WAIT, content_types=['text'])
def handle_broadcast_text(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return
    bot.reply_to(message, "ℹ️ أنت في وضع الإرسال. ابعت *صورة مع كابتشن* ليتم البث للجميع، أو اكتب /cancel للإلغاء.")


# ---- /addmoney & /finemoney ----
@bot.message_handler(commands=["addmoney","finemoney"])
def cmd_money(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return bot.reply_to(message, T(uid_admin, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, "صيغة الاستعمال: /addmoney <user_id> <amount> أو /finemoney <user_id> <amount>")
    target_uid = parts[1].strip()
    try:
        amount = float(parts[2])
    except Exception:
        return bot.reply_to(message, "❌ المبلغ غير صالح.")
    users = load_json("users.json") or {}
    if target_uid not in users:
        return bot.reply_to(message, "❌ المستخدم غير موجود.")
    bal = float(users[target_uid].get("balance", 0))
    if message.text.startswith("/finemoney"):
        bal -= amount
        amount_applied = -amount
    else:
        bal += amount
        amount_applied = amount
    users[target_uid]["balance"] = round(bal, 2)
    save_json("users.json", users)
    return bot.reply_to(message, f"✅ رصيد {target_uid} صار: {users[target_uid]['balance']}$ (تغيير: {amount_applied:+.2f}$)")

# ---- /setdaily & /cleardaily ----
@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    text_part = (message.text or "").split(maxsplit=1)
    if len(text_part) < 2:
        return bot.reply_to(message, "اكتب: /setdaily <نص صفقات اليوم>")
    save_daily_text(text_part[1])
    return bot.reply_to(message, "✅ تم حفظ صفقات اليوم.")

@bot.message_handler(commands=["cleardaily"])
def cmd_cleardaily(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    save_daily_text("")
    return bot.reply_to(message, T(uid, "cleardaily_ok"))

# ---- Stats: /win /loss /record_set /record_done /mystats /userstats ----
@bot.message_handler(commands=["win","loss"])
def cmd_win_loss(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return bot.reply_to(message, T(uid_admin, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 3:
        return bot.reply_to(message, "صيغة: /win <user_id> <amount> أو /loss <user_id> <amount>")
    target_uid = parts[1].strip()
    try:
        amt = float(parts[2])
    except Exception:
        return bot.reply_to(message, "❌ المبلغ غير صالح.")
    kind = "win" if message.text.startswith("/win") else "loss"
    _add_stat(target_uid, kind, amt)
    return bot.reply_to(message, f"✅ تم تسجيل {'ربح' if kind=='win' else 'خسارة'} {amt}$ للمستخدم {target_uid}.")

@bot.message_handler(commands=["record_set"])
def cmd_record_set(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return bot.reply_to(message, T(uid_admin, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "صيغة: /record_set <user_id>")
    target_uid = parts[1].strip()
    _RECORD_MODE[message.from_user.id] = target_uid
    return bot.reply_to(message, f"📝 وضع التسجيل شغّال للمستخدم {target_uid}. اكتب أرقام مثل 10 أو 10- أو -7. اكتب /record_done للخروج.")

@bot.message_handler(commands=["record_done"])
def cmd_record_done(message: types.Message):
    if _RECORD_MODE.pop(message.from_user.id, None):
        return bot.reply_to(message, "✅ تم إنهاء وضع التسجيل.")
    # else ignore

@bot.message_handler(commands=["mystats"])
def cmd_mystats(message: types.Message):
    uid = ensure_user(message.chat.id)
    return bot.reply_to(message, _stats_text(uid, uid))

@bot.message_handler(commands=["userstats"])
def cmd_userstats(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return bot.reply_to(message, T(uid_admin, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "صيغة: /userstats <user_id>")
    target_uid = parts[1].strip()
    return bot.reply_to(message, _stats_text(uid_admin, target_uid))

# ---- Record mode free-text numbers (only when active) ----
@bot.message_handler(func=lambda m: _RECORD_MODE.get(m.from_user.id) is not None, content_types=['text'])
def record_mode_handler(message: types.Message):
    uid_admin = ensure_user(message.chat.id)
    if not is_admin(uid_admin):
        return
    target_uid = _RECORD_MODE.get(message.from_user.id)
    raw = (message.text or "").strip().replace(" ", "")
    m = re.match(r"^(-?\d+(\.\d+)?)([\+\-]?)$", raw)
    if not m:
        return bot.reply_to(message, "❗ اكتب رقم مثل 10 أو 10- أو -7. اكتب /record_done للخروج.")
    val = float(m.group(1))
    sign = m.group(3)
    if sign == "-" or val < 0:
        kind = "loss"; amt = abs(val)
    else:
        kind = "win"; amt = abs(val)
    u = _add_stat(target_uid, kind, amt)
    net = float(u.get("total_win",0.0)) - float(u.get("total_loss",0.0))
    return bot.reply_to(message, f"✅ تم تسجيل {'ربح' if kind=='win' else 'خسارة'} {amt}$ للمستخدم {target_uid}. الصافي الآن: {net:.2f}$.")

# ---------- Key entry via plain text when inactive ----------
@bot.message_handler(func=lambda m: True, content_types=['text'])
def any_text(message: types.Message):
    uid = ensure_user(message.chat.id)
    users = load_json("users.json") or {}
    awaiting = (users.get(uid, {}) or {}).get("await_key", False)

    # if active, ignore to avoid spamming; or you can route to support, etc.
    if is_sub_active(uid):
        return

    # treat message as a key try
    key = (message.text or "").strip()
    msg = activate_key_for_user(uid, key)
    if msg:
        bot.reply_to(message, msg)
        try:
            show_main_menu(message.chat.id)
        except Exception as e:
            log.error("show_main_menu after key failed: %s", e)
    else:
        bot.reply_to(message, T(uid, "key_invalid"))

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
