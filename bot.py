# -*- coding: utf-8 -*-
"""
QL Trading Bot — Monthly subscription only + Players admin + Pro Stats UI (i18n)
Author: ChatGPT

Features
- i18n: ar/en/tr/es/fr
- Subscription: monthly (keys) + lifetime/manual via /gensub
- Key flow: ask on /start if not active; BUY button -> @qlsupport
- Main menu: Daily / Withdraw / Requests / Stats / Deposit / Language / Website / Support
- Admin:
  /players (browse, view, set label/country, search by id)
  /pfind <id>
  /genkey <monthly|lifetime> [count]
  /delkey <KEY>
  /gensub <user_id> <monthly|+days> [days]
  /delsub <user_id>
  /setbal <user_id> <amount>
  /addbal <user_id> <amount>
  /takebal <user_id> <amount>
  /addwin /addloss /addtrade (win|loss)
  /setdaily <user_id>, /cleardaily <user_id>
  /setwebsite <url>, /delwebsite
- Withdraw approve/deny (admin) with balance refund on deny
- Stats UI: main + history/week/month + CSV export
- Storage: JSON files; if db_kv + DATABASE_URL available, uses DB
- Webhook Ready (Flask) or polling if WEBHOOK_URL empty
"""
import os, re, json, logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from flask import Flask, request
import telebot
from telebot import types

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("qlbot")

# ---------- ENV ----------
API_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/") if os.getenv("WEBHOOK_URL") else ""
PORT        = int(os.getenv("PORT", "10000"))
ADMIN_ID    = int(os.getenv("ADMIN_ID", "1262317603"))
ADMIN_IDS   = {ADMIN_ID}
try:
    _ids = os.getenv("ADMIN_IDS","").replace(" ","")
    if _ids:
        ADMIN_IDS |= {int(x) for x in _ids.split(",") if x}
except Exception:
    pass

if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML", threaded=True)
app = Flask(__name__)

# ---------- Storage ----------
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_DB = False
if DATABASE_URL:
    try:
        from db_kv import init_db, get_json as db_get, set_json as db_set
        init_db()
        USE_DB = True
        log.info("📦 Storage: Database Connected")
    except Exception as e:
        log.error("DB init failed: %s; fallback to JSON files", e)
        USE_DB = False
        log.info("📦 Storage: JSON fallback")

DATA_FILES = {
    "users": "users.json",
    "keys": "keys.json",
    "withdraw_requests": "withdraw_requests.json",
    "withdraw_log": "withdraw_log.json",
    "stats": "stats.json",
    "settings": "settings.json",
    "trades": "trades.json",
}

def _now() -> datetime: return datetime.now()
def _now_str() -> str: return _now().strftime("%Y-%m-%d %H:%M:%S")

def load_json(name: str) -> Any:
    key = name
    if USE_DB:
        try: return db_get(key)
        except Exception as e: log.error("db_get(%s) error: %s", key, e)
    path = DATA_FILES.get(name, name)
    if not os.path.exists(path): return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_json(name: str, data: Any) -> None:
    key = name
    if USE_DB:
        try: db_set(key, data); return
        except Exception as e: log.error("db_set(%s) error: %s", key, e)
    path = DATA_FILES.get(name, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---- Safe append to withdraw_log (supports dict or list storage)
def _append_withdraw_log(entry: dict):
    logbook = load_json("withdraw_log")
    if logbook is None:
        logbook = {}
    if isinstance(logbook, list):
        logbook.append(entry)
        save_json("withdraw_log", logbook)
    elif isinstance(logbook, dict):
        key = str(len(logbook) + 1)
        logbook[key] = entry
        save_json("withdraw_log", logbook)
    else:
        save_json("withdraw_log", [entry])

def get_setting(key: str, default=""):
    s = load_json("settings") or {}
    return s.get(key, default)

def set_setting(key: str, value: Any):
    s = load_json("settings") or {}
    s[key] = value
    save_json("settings", s)

# ---------- i18n ----------
LANGS = ["ar","en","tr","es","fr"]
def _T(lang: str, key: str, **kw):
    s = TEXT.get(lang, TEXT["en"]).get(key,"")
    try: return s.format(**kw)
    except Exception: return s

def get_lang(uid: str) -> str:
    users = load_json("users") or {}
    lang = (users.get(uid, {}) or {}).get("lang","en")
    return lang if lang in LANGS else "en"

def set_lang(uid: str, lang: str):
    users = load_json("users") or {}
    u = users.setdefault(uid, {"balance": 0, "created_at": _now_str(), "role": "user", "lang": "en"})
    u["lang"] = lang if lang in LANGS else "en"
    save_json("users", users)

TEXT: Dict[str, Dict[str, Any]] = {
"ar": {
"welcome": "👋 أهلاً بك في بوت التداول\n\n💰 رصيدك: {balance}$\n⏳ ينتهي الاشتراك بعد: {remain}\n🆔 آيديك: {user_id}",
"need_key": "🔑 الرجاء إدخال مفتاح الاشتراك لتفعيل البوت.\nالمتاح: اشتراك شهري فقط.",
"key_ok": "✅ تم تفعيل اشتراكك (شهري). ينتهي في: {exp}\nاستخدم /start لفتح القائمة.",
"key_ok_life": "✅ اشتراكك (دائم) تم تفعيله. استمتع!\nاستخدم /start لفتح القائمة.",
"key_invalid": "❌ مفتاح غير صالح أو مستخدم مسبقاً.",
"key_expired": "⛔ انتهى اشتراكك. أدخل مفتاح شهري جديد.",

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
"daily_none": "لا يوجد صفقة اليوم حالياً.",
"withdraw_enter": "❌ الصيغة: /withdraw 50",
"withdraw_invalid": "❌ مبلغ غير صالح.",
"withdraw_insufficient": "الرصيد غير كافٍ. رصيدك: {bal}$",
"withdraw_created": "✅ تم إنشاء طلب سحب #{req_id} بقيمة {amount}$.",

"lang_menu_title": "اختر لغتك:",
"lang_saved": "✅ تم ضبط اللغة العربية.",
"choose_withdraw_amount": "اختر مبلغ السحب:",
"requests_waiting": "طلباتك قيد الانتظار:",
"no_requests": "لا توجد طلبات قيد الانتظار.",
"deposit_choose": "اختر طريقة الإيداع:",
"deposit_cash": "💵 كاش","deposit_paypal":"🅿️ باي بال","deposit_bank":"🏦 تحويل بنكي","deposit_mc":"💳 ماستركارد","deposit_visa":"💳 فيزا",
"deposit_msg": "لإتمام الدفع عبر {method}، يرجى التواصل مباشرة معنا. اضغط الزر أدناه:",
"contact_us": "📩 تواصل معنا",
"website_msg": "🔥 زر لزيارة موقعنا:","website_not_set": "ℹ️ لم يتم ضبط رابط الموقع بعد.",
"support_msg": "للتواصل مع الدعم اضغط الزر:",
"stats_title": "📊 إحصائياتك",
"stats_line_win": "{at} — ربح +{amount}$",
"stats_line_loss": "{at} — خسارة -{amount}$",
"btn_stats_history":"📜 السجل","btn_stats_week":"🗓️ آخر 7 أيام","btn_stats_month":"🗓️ هذا الشهر","btn_stats_export":"📥 تصدير CSV","back_btn":"🔙 رجوع","note_label":"ملاحظة",

"admin_only":"⚠️ هذا الأمر للأدمن فقط.",
"genkey_ok":"✅ تم توليد {n} مفتاح.\nأول مفتاح:\n<code>{first}</code>",
"delkey_ok":"🗑️ تم حذف المفتاح.","delkey_not_found":"❌ المفتاح غير موجود.",
"delsub_ok":"🗑️ تم حذف اشتراك المستخدم {uid}.","delsub_not_found":"ℹ️ لا يوجد اشتراك.",
"subinfo_line":"📄 النوع: {t}\n🕒 الانتهاء: {exp}","subinfo_none":"ℹ️ لا يوجد اشتراك.",
"admin_w_title":"🧾 طلبات السحب (قيد الانتظار)","admin_w_none":"لا يوجد طلبات بانتظار الموافقة.","admin_w_item":"#{id} — المستخدم {uid} — {amount}$ — {at}","admin_w_approve":"✅ تمت الموافقة على طلب #{id}.","admin_w_denied":"❌ تم رفض طلب #{id} وتمت إعادة المبلغ.",
"setwebsite_ok":"✅ تم ضبط رابط الموقع.","setwebsite_usage":"الصيغة: /setwebsite <URL>","delwebsite_ok":"✅ تم حذف رابط الموقع.",
"players_title":"قائمة اللاعبين:","players_view":"عرض","players_name":"✏️ الاسم","players_country":"🌍 البلد","players_search_btn":"🔎 بحث بالآيدي","players_next":"التالي ➡️","players_prev":"⬅️ السابق","players_search_prompt":"أرسل آيدي اللاعب أو '-' للإلغاء.","players_search_not_found":"الآيدي غير موجود. جرّب رقمًا آخر."
,
"bulk_daily_set_ok": "✅ تم ضبط صفقة اليوم لكل المستخدمين."
,
"bulk_daily_cleared_ok": "🧹 تم حذف صفقة اليوم من جميع المستخدمين."
,
"bulk_trade_added_ok": "✅ تمت إضافة {kind} بقيمة {amount}$ لعدد {n} مستخدم."
,
"bulk_stats_cleared_today_ok": "🧹 تم حذف إحصائيات اليوم فقط (عدد سجلات محذوفة ≈ {removed})."
,
"bulk_stats_cleared_all_ok": "🧹 تم مسح جميع الإحصائيات لكل المستخدمين."
,
"btn_withdraw_custom": "💵 مبلغ مخصص"
,
"withdraw_enter_msg": "✍️ أرسل مبلغ السحب (رقم صحيح)."
,
"status_title": "📅 حالة اشتراكك"
,
"status_active": "⏳ المدة المتبقية: {remain}"
,
"status_expired": "⚠️ انتهى اشتراكك."
},
"en": {
"welcome":"👋 Welcome to the trading bot\n\n💰 Your balance: {balance}$\n⏳ Subscription ends in: {remain}\n🆔 Your ID: {user_id}",
"need_key":"🔑 Please enter your subscription key.\nAvailable: monthly only.",
"key_ok":"✅ Your (monthly) subscription is activated. Expires: {exp}\nUse /start to open the menu.",
"key_ok_life":"✅ Lifetime subscription activated. Enjoy!\nUse /start to open the menu.",
"key_invalid":"❌ Invalid or already used key.","key_expired":"⛔ Your subscription has expired. Enter a new monthly key.",
"btn_daily":"📈 Daily trade","btn_withdraw":"💸 Withdraw","btn_wstatus":"💼 Withdrawal requests","btn_stats":"📊 Stats","btn_lang":"🌐 Language","btn_deposit":"💳 Deposit","btn_website":"🌍 Website","btn_support":"📞 Contact support","btn_buy":"🛒 Buy subscription",
"help_title":"🛠 Available commands:",
"daily_none":"No daily trade yet.","withdraw_enter":"❌ Format: /withdraw 50","withdraw_invalid":"❌ Invalid amount.","withdraw_insufficient":"Insufficient balance. Your balance: {bal}$","withdraw_created":"✅ Withdrawal request #{req_id} created for {amount}$.",
"lang_menu_title":"Choose your language:","lang_saved":"✅ Language set to English.","choose_withdraw_amount":"Choose withdraw amount:","requests_waiting":"Your pending requests:","no_requests":"No pending requests.",
"deposit_choose":"Choose a deposit method:","deposit_cash":"💵 Cash","deposit_paypal":"🅿️ PayPal","deposit_bank":"🏦 Bank Transfer","deposit_mc":"💳 Mastercard","deposit_visa":"💳 Visa","deposit_msg":"To pay via {method}, contact us directly. Tap below:","contact_us":"📩 Contact us","website_msg":"🔥 Tap to visit our website:","website_not_set":"ℹ️ Website URL is not set yet.","support_msg":"Tap below to contact support:",
"stats_title":"📊 Your statistics","stats_line_win":"{at} — Win +{amount}$","stats_line_loss":"{at} — Loss -{amount}$",
"btn_stats_history":"📜 History","btn_stats_week":"🗓️ Last 7 days","btn_stats_month":"🗓️ This month","btn_stats_export":"📥 Export CSV","back_btn":"🔙 Back","note_label":"Note",
"admin_only":"⚠️ Admins only.","genkey_ok":"✅ Generated {n} key(s).\nFirst key:\n<code>{first}</code>","delkey_ok":"🗑️ Key deleted.","delkey_not_found":"❌ Key not found.",
"delsub_ok":"🗑️ Subscription removed for user {uid}.","delsub_not_found":"ℹ️ No subscription.","subinfo_line":"📄 Type: {t}\n🕒 Expires: {exp}","subinfo_none":"ℹ️ No subscription.",
"admin_w_title":"🧾 Pending withdrawal requests","admin_w_none":"No pending requests.","admin_w_item":"#{id} — user {uid} — {amount}$ — {at}","admin_w_approve":"✅ Request #{id} approved.","admin_w_denied":"❌ Request #{id} denied and amount returned.",
"setwebsite_ok":"✅ Website URL saved.","setwebsite_usage":"Usage: /setwebsite <URL>","delwebsite_ok":"✅ Website URL cleared.",
"players_title":"Players list:","players_view":"View","players_name":"✏️ Name","players_country":"🌍 Country","players_search_btn":"🔎 Search by ID","players_next":"Next ➡️","players_prev":"⬅️ Prev","players_search_prompt":"Send player ID or '-' to cancel.","players_search_not_found":"ID not found. Try another one."
,
"bulk_daily_set_ok": "✅ Daily trade set for all users."
,
"bulk_daily_cleared_ok": "🧹 Daily trade cleared for all users."
,
"bulk_trade_added_ok": "✅ Added {kind} of {amount}$ to {n} users."
,
"bulk_stats_cleared_today_ok": "🧹 Cleared today’s statistics (≈ {removed} records)."
,
"bulk_stats_cleared_all_ok": "🧹 Cleared ALL statistics for all users."
,
"btn_withdraw_custom": "💵 Custom amount"
,
"withdraw_enter_msg": "✍️ Send the withdrawal amount (integer)."
,
"status_title": "📅 Your subscription status"
,
"status_active": "⏳ Remaining: {remain}"
,
"status_expired": "⚠️ Your subscription has expired."
},
"tr": {
"welcome":"👋 Trading botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n⏳ Abonelik bitimine: {remain}\n🆔 ID: {user_id}",
"need_key":"🔑 Abonelik anahtarını gir.\nMevcut: sadece aylık.","key_ok":"✅ (Aylık) aboneliğin etkin. Bitiş: {exp}\nMenü için /start.","key_ok_life":"✅ Ömür boyu abonelik etkin. Keyfini çıkar!","key_invalid":"❌ Geçersiz ya da kullanılmış anahtar.","key_expired":"⛔ Aboneliğin bitti. Yeni aylık anahtar gir.",
"btn_daily":"📈 Günün işlemi","btn_withdraw":"💸 Çekim","btn_wstatus":"💼 Çekim talepleri","btn_stats":"📊 İstatistikler","btn_lang":"🌐 Dil","btn_deposit":"💳 Yatırma","btn_website":"🌍 Web sitemiz","btn_support":"📞 Destek","btn_buy":"🛒 Abonelik satın al",
"help_title":"🛠 Kullanılabilir komutlar:","daily_none":"Henüz günlük işlem yok.","withdraw_enter":"❌ Format: /withdraw 50","withdraw_invalid":"❌ Geçersiz tutar.","withdraw_insufficient":"Yetersiz bakiye. Bakiyen: {bal}$","withdraw_created":"✅ #{req_id} numaralı çekim talebi {amount}$ için oluşturuldu.",
"lang_menu_title":"Dilini seç:","lang_saved":"✅ Dil Türkçe olarak ayarlandı.","choose_withdraw_amount":"Çekim tutarını seç:","requests_waiting":"Bekleyen taleplerin:","no_requests":"Bekleyen talep yok.",
"deposit_choose":"Bir yatırma yöntemi seç:","deposit_cash":"💵 Nakit","deposit_paypal":"🅿️ PayPal","deposit_bank":"🏦 Banka Havalesi","deposit_mc":"💳 Mastercard","deposit_visa":"💳 Visa","deposit_msg":"{method} ile ödeme için bizimle iletişime geçin. Aşağı dokunun:","contact_us":"📩 Bizimle iletişim","website_msg":"🔥 Web sitemizi ziyaret etmek için dokunun:","website_not_set":"ℹ️ Website URL henüz ayarlı değil.","support_msg":"Destek için aşağı dokunun:",
"stats_title":"📊 İstatistiklerin","stats_line_win":"{at} — Kazanç +{amount}$","stats_line_loss":"{at} — Kayıp -{amount}$",
"btn_stats_history":"📜 Geçmiş","btn_stats_week":"🗓️ Son 7 gün","btn_stats_month":"🗓️ Bu ay","btn_stats_export":"📥 CSV Dışa aktar","back_btn":"🔙 Geri","note_label":"Not",
"admin_only":"⚠️ Sadece admin.","genkey_ok":"✅ {n} anahtar üretildi.\nİlk anahtar:\n<code>{first}</code>","delkey_ok":"🗑️ Anahtar silindi.","delkey_not_found":"❌ Anahtar bulunamadı.",
"delsub_ok":"🗑️ {uid} kullanıcısının aboneliği silindi.","delsub_not_found":"ℹ️ Abonelik yok.","subinfo_line":"📄 Tür: {t}\n🕒 Bitiş: {exp}","subinfo_none":"ℹ️ Abonelik yok.",
"admin_w_title":"🧾 Bekleyen çekim talepleri","admin_w_none":"Bekleyen talep yok.","admin_w_item":"#{id} — kullanıcı {uid} — {amount}$ — {at}","admin_w_approve":"✅ #{id} onaylandı.","admin_w_denied":"❌ #{id} reddedildi ve iade edildi.",
"setwebsite_ok":"✅ Web sitesi kaydedildi.","setwebsite_usage":"Kullanım: /setwebsite <URL>","delwebsite_ok":"✅ Website URL temizlendi.",
"players_title":"Oyuncu listesi:","players_view":"Görüntüle","players_name":"✏️ İsim","players_country":"🌍 Ülke","players_search_btn":"🔎 ID ile ara","players_next":"İleri ➡️","players_prev":"⬅️ Geri","players_search_prompt":"Oyuncu ID'sini gönder ya da '-' yaz.","players_search_not_found":"ID bulunamadı. Başka bir tane deneyin."
,
"bulk_daily_set_ok": "✅ Günlük işlem tüm kullanıcılara ayarlandı."
,
"bulk_daily_cleared_ok": "🧹 Günlük işlem tüm kullanıcılardan silindi."
,
"bulk_trade_added_ok": "✅ {n} kullanıcıya {amount}$ {kind} eklendi."
,
"bulk_stats_cleared_today_ok": "🧹 Bugünkü istatistikler temizlendi (≈ {removed})."
,
"bulk_stats_cleared_all_ok": "🧹 Tüm kullanıcılar için TÜM istatistikler temizlendi."
,
"btn_withdraw_custom": "💵 Özel tutar"
,
"withdraw_enter_msg": "✍️ Çekmek istediğin tutarı gönder (tam sayı)."
,
"status_title": "📅 Abonelik durumun"
,
"status_active": "⏳ Kalan süre: {remain}"
,
"status_expired": "⚠️ Aboneliğin süresi doldu."
},
"es": {
"welcome":"👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n⏳ La suscripción termina en: {remain}\n🆔 Tu ID: {user_id}",
"need_key":"🔑 Ingresa tu clave de suscripción.\nDisponible: solo mensual.","key_ok":"✅ Tu suscripción (mensual) está activa. Expira: {exp}\nUsa /start para abrir el menú.","key_ok_life":"✅ Suscripción de por vida activada. ¡Disfruta!","key_invalid":"❌ Clave inválida o usada.","key_expired":"⛔ Tu suscripción expiró. Ingresa una clave mensual nueva.",
"btn_daily":"📈 Operación del día","btn_withdraw":"💸 Retirar","btn_wstatus":"💼 Solicitudes de retiro","btn_stats":"📊 Estadísticas","btn_lang":"🌐 Idioma","btn_deposit":"💳 Depósito","btn_website":"🌍 Sitio web","btn_support":"📞 Contactar soporte","btn_buy":"🛒 Comprar suscripción",
"help_title":"🛠 Comandos disponibles:","daily_none":"Aún no hay operación del día.","withdraw_enter":"❌ Formato: /withdraw 50","withdraw_invalid":"❌ Monto inválido.","withdraw_insufficient":"Saldo insuficiente. Tu saldo: {bal}$","withdraw_created":"✅ Solicitud #{req_id} creada por {amount}$.",
"lang_menu_title":"Elige tu idioma:","lang_saved":"✅ Idioma configurado a español.","choose_withdraw_amount":"Elige el monto a retirar:","requests_waiting":"Tus solicitudes pendientes:","no_requests":"No hay solicitudes pendientes.",
"deposit_choose":"Elige un método de depósito:","deposit_cash":"💵 Efectivo","deposit_paypal":"🅿️ PayPal","deposit_bank":"🏦 Transferencia bancaria","deposit_mc":"💳 Mastercard","deposit_visa":"💳 Visa","deposit_msg":"Para pagar con {method}, contáctanos directamente.","contact_us":"📩 Contáctanos","website_msg":"🔥 Visita nuestro sitio:","website_not_set":"ℹ️ La URL del sitio no está configurada.","support_msg":"Pulsa abajo para contactar soporte:",
"stats_title":"📊 Tus estadísticas","stats_line_win":"{at} — Ganancia +{amount}$","stats_line_loss":"{at} — Pérdida -{amount}$",
"btn_stats_history":"📜 Historial","btn_stats_week":"🗓️ Últimos 7 días","btn_stats_month":"🗓️ Este mes","btn_stats_export":"📥 Exportar CSV","back_btn":"🔙 Atrás","note_label":"Nota",
"admin_only":"⚠️ Solo administradores.","genkey_ok":"✅ {n} claves generadas.\nPrimera:\n<code>{first}</code>","delkey_ok":"🗑️ Clave eliminada.","delkey_not_found":"❌ Clave no encontrada.",
"delsub_ok":"🗑️ Suscripción eliminada para {uid}.","delsub_not_found":"ℹ️ Sin suscripción.","subinfo_line":"📄 Tipo: {t}\n🕒 Expira: {exp}","subinfo_none":"ℹ️ Sin suscripción.",
"admin_w_title":"🧾 Solicitudes de retiro pendientes","admin_w_none":"No hay solicitudes pendientes.","admin_w_item":"#{id} — usuario {uid} — {amount}$ — {at}","admin_w_approve":"✅ Solicitud #{id} aprobada.","admin_w_denied":"❌ Solicitud #{id} rechazada y monto devuelto.",
"setwebsite_ok":"✅ URL del sitio guardada.","setwebsite_usage":"Uso: /setwebsite <URL>","delwebsite_ok":"✅ URL del sitio borrada.",
"players_title":"Lista de jugadores:","players_view":"Ver","players_name":"✏️ Nombre","players_country":"🌍 País","players_search_btn":"🔎 Buscar por ID","players_next":"Siguiente ➡️","players_prev":"⬅️ Anterior","players_search_prompt":"Envía el ID del jugador o '-' para cancelar.","players_search_not_found":"ID no encontrado. Prueba otro."
,
"bulk_daily_set_ok": "✅ Operación diaria establecida para todos los usuarios."
,
"bulk_daily_cleared_ok": "🧹 Operación diaria eliminada para todos los usuarios."
,
"bulk_trade_added_ok": "✅ Se añadió {kind} de {amount}$ a {n} usuarios."
,
"bulk_stats_cleared_today_ok": "🧹 Se borraron las estadísticas de hoy (≈ {removed})."
,
"bulk_stats_cleared_all_ok": "🧹 Se borraron TODAS las estadísticas para todos."
,
"btn_withdraw_custom": "💵 Monto personalizado"
,
"withdraw_enter_msg": "✍️ Envía el monto a retirar (entero)."
,
"status_title": "📅 Estado de tu suscripción"
,
"status_active": "⏳ Restante: {remain}"
,
"status_expired": "⚠️ Tu suscripción ha expirado."
},
"fr": {
"welcome":"👋 Bienvenue dans le bot de trading\n\n💰 Votre solde : {balance}$\n⏳ L’abonnement se termine dans : {remain}\n🆔 Votre ID : {user_id}",
"need_key":"🔑 Saisissez votre clé d’abonnement.\nDisponible : mensuel uniquement.","key_ok":"✅ Votre abonnement (mensuel) est activé. Expire : {exp}\nUtilisez /start.","key_ok_life":"✅ Abonnement à vie activé. Profitez-en !","key_invalid":"❌ Clé invalide ou déjà utilisée.","key_expired":"⛔ Votre abonnement a expiré. Saisissez une clé mensuelle.",
"btn_daily":"📈 Trade du jour","btn_withdraw":"💸 Retrait","btn_wstatus":"💼 Demandes de retrait","btn_stats":"📊 Statistiques","btn_lang":"🌐 Langue","btn_deposit":"💳 Dépôt","btn_website":"🌍 Site web","btn_support":"📞 Support","btn_buy":"🛒 Acheter un abonnement",
"help_title":"🛠 Commandes disponibles :","daily_none":"Aucun trade du jour.","withdraw_enter":"❌ Format : /withdraw 50","withdraw_invalid":"❌ Montant invalide.","withdraw_insufficient":"Solde insuffisant. Votre solde : {bal}$","withdraw_created":"✅ Demande #{req_id} créée pour {amount}$.",
"lang_menu_title":"Sélectionnez votre langue :","lang_saved":"✅ Langue définie sur le français.","choose_withdraw_amount":"Choisissez le montant du retrait :","requests_waiting":"Vos demandes en attente :","no_requests":"Aucune demande en attente.",
"deposit_choose":"Choisissez une méthode de dépôt :","deposit_cash":"💵 Espèces","deposit_paypal":"🅿️ PayPal","deposit_bank":"🏦 Virement bancaire","deposit_mc":"💳 Mastercard","deposit_visa":"💳 Visa","deposit_msg":"Pour payer via {method}, contactez-nous.","contact_us":"📩 Nous contacter","website_msg":"🔥 Visitez notre site :","website_not_set":"ℹ️ L’URL du site n’est pas définie.","support_msg":"Appuyez ci-dessous pour contacter le support :",
"stats_title":"📊 Vos statistiques","stats_line_win":"{at} — Gain +{amount}$","stats_line_loss":"{at} — Perte -{amount}$",
"btn_stats_history":"📜 Historique","btn_stats_week":"🗓️ 7 derniers jours","btn_stats_month":"🗓️ Ce mois","btn_stats_export":"📥 Exporter CSV","back_btn":"🔙 Retour","note_label":"Note",
"admin_only":"⚠️ Réservé aux administrateurs.","genkey_ok":"✅ {n} clé(s) générée(s).\nPremière :\n<code>{first}</code>","delkey_ok":"🗑️ Clé supprimée.","delkey_not_found":"❌ Clé introuvable.",
"delsub_ok":"🗑️ Abonnement supprimé pour {uid}.","delsub_not_found":"ℹ️ Aucun abonnement.","subinfo_line":"📄 Type : {t}\n🕒 Expire : {exp}","subinfo_none":"ℹ️ Aucun abonnement.",
"admin_w_title":"🧾 Demandes de retrait en attente","admin_w_none":"Aucune demande en attente.","admin_w_item":"#{id} — utilisateur {uid} — {amount}$ — {at}","admin_w_approve":"✅ Demande #{id} approuvée.","admin_w_denied":"❌ Demande #{id} refusée et montant remboursé.",
"setwebsite_ok":"✅ URL du site enregistrée.","setwebsite_usage":"Usage : /setwebsite <URL>","delwebsite_ok":"✅ URL du site supprimée.",
"players_title":"Liste des joueurs :","players_view":"Voir","players_name":"✏️ Nom","players_country":"🌍 Pays","players_search_btn":"🔎 Rechercher par ID","players_next":"Suivant ➡️","players_prev":"⬅️ Précédent","players_search_prompt":"Envoyez l’ID du joueur ou '-' pour annuler.","players_search_not_found":"ID introuvable. Essayez un autre."
,
"bulk_daily_set_ok": "✅ Trade du jour défini pour tous les utilisateurs."
,
"bulk_daily_cleared_ok": "🧹 Trade du jour effacé pour tous."
,
"bulk_trade_added_ok": "✅ Ajout de {kind} de {amount}$ à {n} utilisateurs."
,
"bulk_stats_cleared_today_ok": "🧹 Statistiques du jour effacées (≈ {removed})."
,
"bulk_stats_cleared_all_ok": "🧹 TOUTES les statistiques ont été effacées pour tous."
,
"btn_withdraw_custom": "💵 Montant personnalisé"
,
"withdraw_enter_msg": "✍️ Envoyez le montant à retirer (entier)."
,
"status_title": "📅 État de votre abonnement"
,
"status_active": "⏳ Restant : {remain}"
,
"status_expired": "⚠️ Votre abonnement a expiré."
}
}

def T(uid: str, key: str, **kw): return _T(get_lang(uid), key, **kw)

# ---------- Subscriptions (monthly + lifetime) ----------
DURATIONS = {"monthly": 30, "lifetime": None}

def is_sub_active(uid: str) -> bool:
    users = load_json("users") or {}
    sub = (users.get(uid, {}) or {}).get("sub")
    if not sub: return False
    exp = sub.get("expire_at")
    if exp is None: return True
    try: return datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") > _now()
    except Exception: return False

def sub_remaining_str(uid: str) -> str:
    users = load_json("users") or {}
    sub = (users.get(uid, {}) or {}).get("sub")
    if not sub: return "0s"
    exp = sub.get("expire_at")
    if exp is None: return "∞"
    try: exp_dt = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S")
    except Exception: return "0s"
    delta = exp_dt - _now()
    secs = int(delta.total_seconds())
    if secs <= 0: return "0s"
    d, rem = divmod(secs, 86400); h, rem = divmod(rem, 3600); m, s = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h or d: parts.append(f"{h}h")
    if m or h or d: parts.append(f"{m}m")
    parts.append(f"{s:02d}s")
    return " ".join(parts)

def _key_store() -> Dict[str, Any]: return load_json("keys") or {}
def _save_keys(d: Dict[str, Any]): save_json("keys", d)

def _rand_key(n=4):
    import random, string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def generate_keys(k_type: str, count: int) -> List[str]:
    keys = _key_store(); out = []
    for _ in range(count):
        while True:
            k = f"{k_type[:2].upper()}-{_rand_key()}-{_rand_key()}-{_rand_key()}"
            if k not in keys: break
        keys[k] = {"type": k_type, "created_at": _now_str()}
        out.append(k)
    _save_keys(keys); return out

def activate_key_for_user(uid: str, key: str) -> Optional[str]:
    keys = _key_store(); meta = keys.get(key)
    if not meta or meta.get("used_by"): return None
    ktype = meta.get("type")
    days = DURATIONS.get(ktype)
    users = load_json("users") or {}; users.setdefault(uid, {})
    if days is None:
        users[uid]["sub"] = {"type": ktype, "expire_at": None, "key": key}
        users[uid]["await_key"] = False
        keys[key]["used_by"] = uid; keys[key]["used_at"] = _now_str()
        _save_keys(keys); save_json("users", users)
        return T(uid, "key_ok_life")
    else:
        exp_dt = _now() + timedelta(days=days); exp = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
        users[uid]["sub"] = {"type": ktype, "expire_at": exp, "key": key}
        users[uid]["await_key"] = False
        keys[key]["used_by"] = uid; keys[key]["used_at"] = _now_str()
        _save_keys(keys); save_json("users", users)
        return T(uid, "key_ok", exp=exp)

# ---------- Users ----------
def ensure_user(chat_id: int) -> str:
    uid = str(chat_id)
    users = load_json("users") or {}
    if uid not in users:
        users[uid] = {"balance": 0, "role": "admin" if chat_id in ADMIN_IDS else "user",
                      "created_at": _now_str(), "lang": "ar"}
        save_json("users", users)
    else:
        if chat_id in ADMIN_IDS and users[uid].get("role") != "admin":
            users[uid]["role"] = "admin"; save_json("users", users)
    return uid

def is_admin(uid: str) -> bool:
    try:
        if int(uid) in ADMIN_IDS: return True
    except Exception:
        pass
    users = load_json("users") or {}
    return (users.get(uid, {}) or {}).get("role") == "admin"

# ---------- UI ----------
def build_lang_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🇸🇦 العربية", callback_data="set_lang_ar"),
           types.InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en"))
    kb.add(types.InlineKeyboardButton("🇹🇷 Türkçe", callback_data="set_lang_tr"),
           types.InlineKeyboardButton("🇪🇸 Español", callback_data="set_lang_es"))
    kb.add(types.InlineKeyboardButton("🇫🇷 Français", callback_data="set_lang_fr"))
    return kb

def main_menu(uid: str) -> types.InlineKeyboardMarkup:
    tt = TEXT[get_lang(uid)]
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton(tt["btn_daily"], callback_data="daily_trade"),
          types.InlineKeyboardButton(tt["btn_withdraw"], callback_data="withdraw_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_wstatus"], callback_data="withdraw_status"),
          types.InlineKeyboardButton(tt["btn_stats"], callback_data="stats:main"))
    m.add(types.InlineKeyboardButton(tt["btn_deposit"], callback_data="deposit"),
          types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_website"], callback_data="website"),
          types.InlineKeyboardButton(tt["btn_support"], callback_data="support"))
    return m

def show_main_menu(chat_id: int):
    uid = ensure_user(chat_id)
    users = load_json("users") or {}
    bal = (users.get(uid, {}) or {}).get("balance", 0)
    remain = sub_remaining_str(uid)
    bot.send_message(chat_id, T(uid,"welcome", balance=bal, remain=remain, user_id=uid), reply_markup=main_menu(uid))

# ---------- Need key ----------
def require_active_or_ask(chat_id: int) -> bool:
    uid = ensure_user(chat_id)
    if is_sub_active(uid):
        users = load_json("users") or {}
        if (users.get(uid,{}) or {}).get("await_key"):
            users[uid]["await_key"] = False; save_json("users", users)
        return True
    users = load_json("users") or {}; users.setdefault(uid, {}); users[uid]["await_key"]=True; save_json("users", users)
    tt = TEXT[get_lang(uid)]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport"))
    kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    msg = T(uid,"key_expired") if (users.get(uid,{}).get("sub")) else T(uid,"need_key")
    bot.send_message(chat_id, msg, reply_markup=kb)
    return False

# ---------- Daily text ----------
def _get_daily() -> str:
    trades = load_json("trades") or {}
    return trades.get("daily","")

def _set_daily(uid: str, text: str):
    trades = load_json("trades") or {}
    trades["daily"] = text
    save_json("trades", trades)

# ---------- Commands ----------
@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    show_main_menu(m.chat.id)

@bot.message_handler(commands=["lang"])
def cmd_lang(m: types.Message):
    uid = ensure_user(m.chat.id)
    bot.reply_to(m, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=build_lang_kb())

@bot.message_handler(commands=["help"])
def cmd_help(m: types.Message):
    uid = ensure_user(m.chat.id)
    is_ad = is_admin(uid)
    lang = get_lang(uid)
    tt = TEXT[lang]
    lines = [tt["help_title"]]
    public = [
        "/start - Main menu",
        "/id - Show your ID",
        "/balance - Your balance",
        "/daily - Daily trade",
        "/withdraw <amount> - Request withdrawal",
        "/wlist - My withdrawal requests",
        "/lang - Language menu",
        "/mystats - My stats",
    ]
    for c in public: lines.append(f"• {c}")
    if is_ad:
        admin = [
            "/players - Browse players",
            "/pfind <user_id> - Open player by ID",
            "/genkey <monthly|lifetime> [count]",
            "/delkey <KEY>",
            "/gensub <user_id> <monthly|+days> [days]",
            "/delsub <user_id>",
            "/setbal <user_id> <amount>",
            "/addbal <user_id> <amount>",
            "/takebal <user_id> <amount>",
            "/setdaily <user_id>",
            "/cleardaily <user_id>",
            "/setwebsite <url>",
            "/delwebsite",
            "/addwin <user_id> <amount> [note]",
            "/addloss <user_id> <amount> [note]",
            "/addtrade <user_id> win|loss <amount> [note]",
        ]
        lines.append("")
        lines.append("<b>Admin</b>:")
        for c in admin: lines.append(f"• {c}")
    bot.send_message(m.chat.id, "\n".join(lines))


@bot.message_handler(commands=["mystatus"])
def cmd_mystatus(m: types.Message):
    uid = ensure_user(m.chat.id)
    # No require_active_or_ask: show status even if expired
    remain = sub_remaining_str(uid)
    lang = get_lang(uid); tt = TEXT[lang]
    title = tt.get("status_title","Status")
    if remain == "0s":
        return bot.reply_to(m, tt.get("status_expired","Expired."))
    return bot.reply_to(m, tt.get("status_active","Remaining: {remain}").format(remain=remain))

@bot.message_handler(commands=["id"])
def cmd_id(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    bot.reply_to(m, f"<b>ID</b> <code>{m.from_user.id}</code>")

@bot.message_handler(commands=["balance"])
def cmd_balance(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    users = load_json("users") or {}; bal = (users.get(uid,{}) or {}).get("balance",0)
    bot.reply_to(m, f"💰 {bal}$")

@bot.message_handler(commands=["daily"])
def cmd_daily(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    txt = _get_daily() or TEXT[get_lang(uid)]["daily_none"]
    bot.reply_to(m, txt if isinstance(txt,str) else str(txt))

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    parts = (m.text or "").split()
    if len(parts) < 2:
        return open_withdraw_menu(m.chat.id, uid)
    try: amount = int(parts[1])
    except Exception: return bot.reply_to(m, TEXT[get_lang(uid)]["withdraw_invalid"])
    return create_withdraw_request(m.chat.id, uid, amount)

@bot.message_handler(commands=["mystats"])
def cmd_mystats(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not require_active_or_ask(m.chat.id): return
    header = _stats_build_text(uid, uid)
    bot.send_message(m.chat.id, header, reply_markup=_stats_kb(uid,"main"))


# ---------- Bulk admin ops: daily & stats (ALL users) ----------
@bot.message_handler(commands=["setdaily_all"])
def cmd_setdaily_all(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid, "admin_only"))
    parts = (m.text or "").split(maxsplit=1)
    if len(parts)<2 or not parts[1].strip():
        return bot.reply_to(m, "Usage: /setdaily_all <text>")
    text = parts[1].strip()[:2000]
    users = load_json("users") or {}
    for k in users.keys():
        u = users.setdefault(k, {}); u["daily"] = text
    save_json("users", users)
    bot.reply_to(m, T(uid, "bulk_daily_set_ok"))

@bot.message_handler(commands=["cleardaily_all"])
def cmd_cleardaily_all(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid, "admin_only"))
    users = load_json("users") or {}
    changed = 0
    for k in users.keys():
        u = users.setdefault(k, {})
        if "daily" in u:
            u.pop("daily", None); changed += 1
    save_json("users", users)
    bot.reply_to(m, T(uid, "bulk_daily_cleared_ok"))

def _recompute_stats_totals(u_hist: list) -> dict:
    win_sum = 0.0; loss_sum = 0.0
    for r in u_hist:
        kind = (r or {}).get("kind")
        amt = r.get("amount",0)
        try: amt_f = float(amt)
        except Exception: amt_f = 0.0
        if kind=="win": win_sum += amt_f
        elif kind=="loss": loss_sum += amt_f
    return {"total_win": win_sum, "total_loss": loss_sum}

@bot.message_handler(commands=["addtrade_all"])
def cmd_addtrade_all(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid, "admin_only"))
    parts = (m.text or "").split(maxsplit=3)
    if len(parts)<3 or parts[1] not in ("win","loss"):
        return bot.reply_to(m, "Usage: /addtrade_all win|loss <amount> [note]")
    kind = parts[1]
    try: amount = float(parts[2])
    except Exception: return bot.reply_to(m, "Invalid amount")
    note = parts[3] if len(parts)>3 else ""
    users = load_json("users") or {}
    n=0
    for k in users.keys():
        _add_trade_record(k, kind, amount, note)
        n += 1
    bot.reply_to(m, T(uid, "bulk_trade_added_ok").format(kind=kind, amount=amount, n=n))

@bot.message_handler(commands=["clearstats_all"])
def cmd_clearstats_all(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid, "admin_only"))
    parts = (m.text or "").split()
    scope = parts[1].lower() if len(parts)>1 else "today"
    if scope not in ("today","all"):
        return bot.reply_to(m, "Usage: /clearstats_all [today|all]")
    stats = _get_stats()
    removed = 0
    if scope=="all":
        for uid_k in list(stats.keys()):
            stats[uid_k] = {"total_win":0.0,"total_loss":0.0,"history":[]}
        _save_stats(stats)
        return bot.reply_to(m, T(uid, "bulk_stats_cleared_all_ok"))
    # today only (UTC)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    for uid_k,u in list(stats.items()):
        hist = (u or {}).get("history", [])[:]
        new_hist = []
        for r in hist:
            ts = (r or {}).get("ts","")
            if ts.startswith(today_str):
                removed += 1
                continue
            new_hist.append(r)
        stats[uid_k]["history"] = new_hist
        totals = _recompute_stats_totals(new_hist)
        stats[uid_k]["total_win"] = totals["total_win"]
        stats[uid_k]["total_loss"] = totals["total_loss"]
    _save_stats(stats)
    bot.reply_to(m, T(uid, "bulk_stats_cleared_today_ok").format(removed=removed))

# ---------- Balance admin ----------
def _notify_balance(uid_target: str):
    # notify user in their language
    lang = get_lang(uid_target)
    msg = "✅ تم ربط البوت بحسابك التداول ورصيدك {bal}$" if lang=="ar" else \
          "✅ Bot linked to your trading account. Your balance is {bal}$"
    users = load_json("users") or {}
    bal = (users.get(uid_target,{}) or {}).get("balance",0)
    try: bot.send_message(int(uid_target), msg.format(bal=bal))
    except Exception: pass

@bot.message_handler(commands=["setbal","addbal","takebal"])
def cmd_balance_admin(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit():
        return bot.reply_to(m, "Usage: /setbal|/addbal|/takebal <user_id> <amount>")
    target, amt = parts[1], parts[2]
    try: amount = float(amt)
    except Exception: return bot.reply_to(m, "Invalid amount")
    users = load_json("users") or {}; u = users.setdefault(target, {"balance":0, "role":"user", "created_at": _now_str(), "lang":"ar"})
    if m.text.startswith("/setbal"):
        u["balance"] = amount
    elif m.text.startswith("/addbal"):
        u["balance"] = float(u.get("balance",0)) + amount
    else: # takebal
        u["balance"] = max(0.0, float(u.get("balance",0)) - amount)
    save_json("users", users)
    bot.reply_to(m, f"OK. {target} balance = {u['balance']:.2f}$")
    _notify_balance(target)

# ---------- Keys / subs admin ----------
@bot.message_handler(commands=["genkey"])
def cmd_genkey(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts) < 2: return bot.reply_to(m, "Usage: /genkey <monthly|lifetime> [count]")
    ktype = parts[1].lower()
    if ktype not in DURATIONS: return bot.reply_to(m, "Usage: /genkey <monthly|lifetime> [count]")
    try:
        count = int(parts[2]) if len(parts)>2 else 1
        if count<1 or count>100: raise ValueError()
    except Exception: return bot.reply_to(m, "count must be 1..100")
    keys = generate_keys(ktype, count)
    if count==1:
        return bot.reply_to(m, T(uid,"genkey_ok", n=count, first=keys[0]))
    else:
        txt = "\\n".join(keys)
        try:
            bot.reply_to(m, T(uid,"genkey_ok", n=count, first=keys[0]))
            bot.send_document(m.chat.id, ("keys.txt", txt.encode("utf-8")))
        except Exception:
            bot.reply_to(m, "Generated keys:\\n" + ("\\n".join(f"<code>{k}</code>" for k in keys)))

@bot.message_handler(commands=["delkey"])
def cmd_delkey(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split(maxsplit=1)
    if len(parts)<2: return bot.reply_to(m, "Usage: /delkey <KEY>")
    key = parts[1].strip()
    keys = _key_store()
    if key in keys:
        del keys[key]; _save_keys(keys); return bot.reply_to(m, T(uid,"delkey_ok"))
    return bot.reply_to(m, T(uid,"delkey_not_found"))

@bot.message_handler(commands=["gensub"])
def cmd_gensub(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts) < 3: return bot.reply_to(m, "Usage: /gensub <user_id> <monthly|lifetime|+days> [days]")
    target, mode = parts[1], parts[2].lower()
    users = load_json("users") or {}; users.setdefault(target, {"balance":0,"role":"user","created_at":_now_str(),"lang":"ar"})
    now = _now()
    if mode in DURATIONS:
        days = DURATIONS[mode]
        exp = None if days is None else (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        users[target]["sub"] = {"type": mode, "expire_at": exp, "key": "MANUAL"}
    elif mode == "+days":
        if len(parts)<4: return bot.reply_to(m, "Usage: /gensub <user_id> +days <days>")
        try: addd = int(parts[3])
        except Exception: return bot.reply_to(m, "days must be int")
        base = now
        cur = users[target].get("sub",{}).get("expire_at")
        if cur:
            try: base = datetime.strptime(cur, "%Y-%m-%d %H:%M:%S")
            except Exception: pass
        new_exp = (base + timedelta(days=addd)).strftime("%Y-%m-%d %H:%M:%S")
        t = users[target].get("sub",{}).get("type","monthly")
        users[target]["sub"] = {"type": t, "expire_at": new_exp, "key":"MANUAL"}
    else:
        return bot.reply_to(m, "Usage: /gensub <user_id> <monthly|lifetime|+days> [days]")
    save_json("users", users)
    bot.reply_to(m, f"OK. sub for {target} → {users[target]['sub']}")

@bot.message_handler(commands=["delsub"])
def cmd_delsub(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts)<2: return bot.reply_to(m, "Usage: /delsub <USER_ID>")
    target = parts[1]
    users = load_json("users") or {}
    if target in users and "sub" in users[target]:
        users[target].pop("sub", None); save_json("users", users); return bot.reply_to(m, T(uid,"delsub_ok", uid=target))
    return bot.reply_to(m, T(uid,"delsub_not_found"))

@bot.message_handler(commands=["subinfo"])
def cmd_subinfo(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    target = parts[1] if len(parts)>1 else uid
    users = load_json("users") or {}; sub = (users.get(target,{}) or {}).get("sub")
    if not sub: return bot.reply_to(m, T(uid,"subinfo_none"))
    t = sub.get("type","-"); exp = sub.get("expire_at","∞") or "∞"
    return bot.reply_to(m, T(uid,"subinfo_line", t=t, exp=exp))

# ---------- Withdraw ----------
def open_withdraw_menu(chat_id: int, uid: str):
    tt = TEXT[get_lang(uid)]
    mm = types.InlineKeyboardMarkup()
    for amount in [10,20,30,50,100]:
        mm.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
    mm.add(types.InlineKeyboardButton(tt["btn_withdraw_custom"], callback_data="withdraw_custom"))
    mm.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    bot.send_message(chat_id, tt["choose_withdraw_amount"], reply_markup=mm)

def create_withdraw_request(chat_id: int, uid: str, amount: int):
    if amount<=0: return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_invalid"])
    users = load_json("users") or {}
    bal = (users.get(uid,{}) or {}).get("balance",0)
    if bal < amount: return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_insufficient"].format(bal=bal))
    users.setdefault(uid, {"balance":0})
    users[uid]["balance"] = bal - amount; save_json("users", users)
    reqs = load_json("withdraw_requests") or {}
    rid = str(len(reqs)+1)
    reqs[rid] = {"user_id": uid, "amount": amount, "status":"pending", "created_at": _now_str()}
    save_json("withdraw_requests", reqs)
    return bot.send_message(chat_id, TEXT[get_lang(uid)]["withdraw_created"].format(req_id=rid, amount=amount))

# ---------- Players (admin) ----------
PAGE_SIZE = 10
_pending_player_search: Dict[int, int] = {}  # admin_id -> back_page

def list_user_ids() -> List[int]:
    users = load_json("users") or {}
    for uid, u in users.items():
        u.setdefault("label", None); u.setdefault("country", None)
    save_json("users", users)
    return sorted([int(x) for x in users.keys()])

def _user_label(uid: str) -> str:
    users = load_json("users") or {}
    return (users.get(uid,{}) or {}).get("label") or "(no name)"

@bot.message_handler(commands=["players"])
def cmd_players(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return
    show_players_page(m.chat.id, 1)

@bot.message_handler(commands=["pfind"])
def cmd_pfind(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts)<2 or not parts[1].isdigit():
        return bot.reply_to(m, TEXT[get_lang(uid)]["players_search_not_found"])
    target = parts[1]
    users = load_json("users") or {}
    if target not in users: return bot.reply_to(m, TEXT[get_lang(uid)]["players_search_not_found"])
    _send_player_profile(m.chat.id, target, 1)

def show_players_page(chat_id: int, page: int=1):
    uid = ensure_user(chat_id); tt = TEXT[get_lang(uid)]
    ids = list_user_ids()
    if not ids: return bot.send_message(chat_id, "لا يوجد مستخدمون بعد.")
    start = (page-1)*PAGE_SIZE; chunk = ids[start:start+PAGE_SIZE]
    kb = types.InlineKeyboardMarkup()
    for i in chunk:
        sid = str(i)
        kb.add(types.InlineKeyboardButton(f"{sid} — {_user_label(sid)}", callback_data=f"players:view:{sid}:{page}"))
    nav = []
    if page>1: nav.append(types.InlineKeyboardButton(tt["players_prev"], callback_data=f"players:page:{page-1}"))
    if start+PAGE_SIZE < len(ids): nav.append(types.InlineKeyboardButton(tt["players_next"], callback_data=f"players:page:{page+1}"))
    if nav: kb.row(*nav)
    kb.row(types.InlineKeyboardButton(tt["players_search_btn"], callback_data=f"players:search:{page}"))
    bot.send_message(chat_id, tt["players_title"], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:"))
def cb_players_router(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id); tt = TEXT[get_lang(uid)]
    try: bot.answer_callback_query(c.id)
    except Exception: pass
    parts = (c.data or "").split(":")
    if parts[1] == "page":
        page = int(parts[2]); return _edit_players_page(c, page)
    if parts[1] == "view":
        _,_,sid,page = parts
        return _send_player_profile(c.message.chat.id, sid, int(page))
    if parts[1] == "search":
        _,_,page = parts
        _pending_player_search[c.from_user.id] = int(page)
        return bot.send_message(c.message.chat.id, tt["players_search_prompt"])

def _edit_players_page(c: types.CallbackQuery, page: int):
    uid = ensure_user(c.from_user.id); tt = TEXT[get_lang(uid)]
    ids = list_user_ids(); start = (page-1)*PAGE_SIZE; chunk = ids[start:start+PAGE_SIZE]
    kb = types.InlineKeyboardMarkup()
    for i in chunk:
        sid = str(i)
        kb.add(types.InlineKeyboardButton(f"{sid} — {_user_label(sid)}", callback_data=f"players:view:{sid}:{page}"))
    nav = []
    if page>1: nav.append(types.InlineKeyboardButton(tt["players_prev"], callback_data=f"players:page:{page-1}"))
    if start+PAGE_SIZE < len(ids): nav.append(types.InlineKeyboardButton(tt["players_next"], callback_data=f"players:page:{page+1}"))
    if nav: kb.row(*nav)
    kb.row(types.InlineKeyboardButton(tt["players_search_btn"], callback_data=f"players:search:{page}"))
    try:
        bot.edit_message_text(tt["players_title"], c.message.chat.id, c.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(c.message.chat.id, tt["players_title"], reply_markup=kb)

def _send_player_profile(chat_id: int, uid_target: str, back_page: int):
    users = load_json("users") or {}; u = users.get(uid_target, {}) or {}
    bal = float(u.get("balance",0))
    stats = load_json("stats") or {}; st = stats.get(uid_target, {"total_win":0.0,"total_loss":0.0})
    win=float(st.get("total_win",0.0)); loss=float(st.get("total_loss",0.0)); net=win-loss
    remain = sub_remaining_str(uid_target)
    country = u.get("country") or "—"
    label = u.get("label") or "(no name)"
    txt = (f"👤 <b>User {uid_target}</b> — {label}\n"
           f"💰 الرصيد: {bal:.2f}$\n"
           f"📊 الإحصائيات: win={win:.2f} | loss={loss:.2f} | net={net:.2f}\n"
           f"🗺️ البلد: {country}\n"
           f"⏳ اشتراك: {remain}")
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton(TEXT["ar"]["players_name"], callback_data=f"players:label:{uid_target}:{back_page}"),
           types.InlineKeyboardButton(TEXT["ar"]["players_country"], callback_data=f"players:country:{uid_target}:{back_page}"))
    kb.row(types.InlineKeyboardButton(TEXT["ar"]["back_btn"], callback_data=f"players:page:{back_page}"))
    bot.send_message(chat_id, txt, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:label:"))
def cb_players_label(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS: return bot.answer_callback_query(c.id)
    _,_,uid,page = c.data.split(":")
    _pending_label[c.from_user.id] = (uid, int(page))
    bot.answer_callback_query(c.id, "أرسل الاسم الجديد (أو '-' للحذف)")
    bot.send_message(c.message.chat.id, f"أرسل الاسم الجديد للاعب {uid}. اكتب '-' لإزالة الاسم.")

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("players:country:"))
def cb_players_country(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS: return bot.answer_callback_query(c.id)
    _,_,uid,page = c.data.split(":")
    _pending_country[c.from_user.id] = (uid, int(page))
    bot.answer_callback_query(c.id, "أرسل اسم البلد (أو '-' للحذف)")
    bot.send_message(c.message.chat.id, f"أرسل اسم البلد للاعب {uid}. اكتب '-' لإزالة البلد.")

_pending_label: Dict[int, tuple] = {}
_pending_country: Dict[int, tuple] = {}

@bot.message_handler(func=lambda m: m.from_user.id in _pending_label and not (m.text or '').strip().startswith('/'))
def on_admin_label(m: types.Message):
    uid, page = _pending_label.pop(m.from_user.id)
    users = load_json("users") or {}
    u = users.setdefault(uid, {})
    val = (m.text or "").strip()
    if val == "-" or val == "":
        u["label"] = None; msg = f"تم إزالة الاسم للمستخدم {uid}."
    else:
        u["label"] = val[:32]; msg = f"تم ضبط الاسم: {uid} — {u['label']}"
    save_json("users", users); bot.reply_to(m, msg)

@bot.message_handler(func=lambda m: m.from_user.id in _pending_country and not (m.text or '').strip().startswith('/'))
def on_admin_country(m: types.Message):
    uid, page = _pending_country.pop(m.from_user.id)
    users = load_json("users") or {}
    u = users.setdefault(uid, {})
    val = (m.text or "").strip()
    if val == "-" or val == "":
        u["country"] = None; msg = f"تم إزالة البلد للمستخدم {uid}."
    else:
        u["country"] = val[:32]; msg = f"تم ضبط البلد للمستخدم {uid}: {u['country']}"
    save_json("users", users); bot.reply_to(m, msg)

@bot.message_handler(func=lambda m: m.from_user.id in _pending_player_search and not (m.text or '').strip().startswith('/'))
def on_player_id_search(m: types.Message):
    page = _pending_player_search.get(m.from_user.id, 1)
    txt = (m.text or "").strip()
    uid_view = str(m.from_user.id)
    if txt == "-":
        _pending_player_search.pop(m.from_user.id, None)
        return show_players_page(m.chat.id, page)
    if not txt.isdigit():
        return bot.reply_to(m, TEXT[get_lang(uid_view)]["players_search_not_found"])
    target = txt; users = load_json("users") or {}
    if target not in users:
        return bot.reply_to(m, TEXT[get_lang(uid_view)]["players_search_not_found"])
    _pending_player_search.pop(m.from_user.id, None)  # clear
    _send_player_profile(m.chat.id, target, page)

# ---------- Website ----------
@bot.message_handler(commands=["setwebsite"])
def cmd_setwebsite(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split(maxsplit=1)
    if len(parts)<2 or not re.match(r"^https?://", parts[1].strip()): return bot.reply_to(m, T(uid,"setwebsite_usage"))
    set_setting("WEBSITE_URL", parts[1].strip()); bot.reply_to(m, T(uid,"setwebsite_ok"))

@bot.message_handler(commands=["delwebsite"])
def cmd_delwebsite(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    set_setting("WEBSITE_URL", ""); bot.reply_to(m, T(uid,"delwebsite_ok"))

def _website_url() -> str: return get_setting("WEBSITE_URL","")

# ---------- Key input when awaiting ----------
KEY_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

@bot.message_handler(func=lambda m: bool(m.text) and not m.text.strip().startswith(("/", "／", "⁄")))
def maybe_activate_key(m: types.Message):
    uid = ensure_user(m.chat.id)
    users = load_json("users") or {}
    if (users.get(uid,{}) or {}).get("await_key"):
        key = (m.text or "").strip().upper().replace(" ", "")
        if KEY_RE.match(key):
            resp = activate_key_for_user(uid, key)
            if resp:
                bot.reply_to(m, resp); show_main_menu(m.chat.id); return
        bot.reply_to(m, TEXT[get_lang(uid)]["key_invalid"])
        tt = TEXT[get_lang(uid)]; kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport"))
        kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
        bot.send_message(m.chat.id, TEXT[get_lang(uid)]["need_key"], reply_markup=kb)

# ---------- Stats storage ----------
def _get_stats(): return load_json("stats") or {}
def _save_stats(d): save_json("stats", d)

def _add_trade_record(user_id: str, kind: str, amount: float, note: str=""):
    stats = _get_stats()
    u = stats.setdefault(user_id, {"total_win":0.0,"total_loss":0.0,"history":[]})
    if kind == "win":
        u["total_win"] = float(u.get("total_win",0.0)) + float(amount)
    elif kind == "loss":
        u["total_loss"] = float(u.get("total_loss",0.0)) + float(amount)
    u["history"].insert(0, {"ts": datetime.utcnow().isoformat(timespec="seconds")+"Z","kind":kind,"amount":float(amount),"note":note[:100]})
    u["history"] = u["history"][:1000]
    _save_stats(stats); return u

@bot.message_handler(commands=["addwin"])
def cmd_addwin(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split(maxsplit=3)
    if len(parts)<3 or not parts[1].isdigit(): return bot.reply_to(m, "Usage: /addwin <user_id> <amount> [note]")
    target, amt = parts[1], parts[2]
    try: amount=float(amt)
    except Exception: return bot.reply_to(m, "Invalid amount")
    note = parts[3] if len(parts)>3 else ""
    _add_trade_record(target,"win",amount,note); bot.reply_to(m, f"Added win {amount}$ to {target}.")

@bot.message_handler(commands=["addloss"])
def cmd_addloss(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split(maxsplit=3)
    if len(parts)<3 or not parts[1].isdigit(): return bot.reply_to(m, "Usage: /addloss <user_id> <amount> [note]")
    target, amt = parts[1], parts[2]
    try: amount=float(amt)
    except Exception: return bot.reply_to(m, "Invalid amount")
    note = parts[3] if len(parts)>3 else ""
    _add_trade_record(target,"loss",amount,note); bot.reply_to(m, f"Added loss {amount}$ to {target}.")

@bot.message_handler(commands=["addtrade"])
def cmd_addtrade(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split(maxsplit=4)
    if len(parts)<4 or not parts[1].isdigit() or parts[2] not in ("win","loss"):
        return bot.reply_to(m, "Usage: /addtrade <user_id> win|loss <amount> [note]")
    target, kind, amt = parts[1], parts[2], parts[3]
    try: amount=float(amt)
    except Exception: return bot.reply_to(m, "Invalid amount")
    note = parts[4] if len(parts)>4 else ""
    _add_trade_record(target, kind, amount, note); bot.reply_to(m, f"Added {kind} {amount}$ to {target}.")

# ---------- Stats UI ----------
def _stats_build_text(uid_viewer: str, target_uid: str):
    lang = get_lang(uid_viewer)
    stats = _get_stats()
    u = stats.get(target_uid, {"total_win":0.0,"total_loss":0.0,"history":[]})
    win_sum = float(u.get("total_win",0.0)); loss_sum=float(u.get("total_loss",0.0))
    hist = u.get("history",[]) or []
    win_cnt = sum(1 for h in hist if (h or {}).get("kind")=="win")
    loss_cnt = sum(1 for h in hist if (h or {}).get("kind")=="loss")
    net = win_sum - loss_sum; arrow = "🟢" if net >= 0 else "🔴"
    if lang=="ar":
        return (f"📊 <b>إحصائياتك</b>\n"
                f"✅ الأرباح: <b>{win_sum:.2f}$</b> (عدد: {win_cnt})\n"
                f"❌ الخسائر: <b>{loss_sum:.2f}$</b> (عدد: {loss_cnt})\n"
                f"⚖️ الصافي: {arrow} <b>{net:.2f}$</b>")
    if lang=="tr":
        return (f"📊 <b>İstatistiklerin</b>\n"
                f"✅ Kazançlar: <b>{win_sum:.2f}$</b> (adet: {win_cnt})\n"
                f"❌ Kayıplar: <b>{loss_sum:.2f}$</b> (adet: {loss_cnt})\n"
                f"⚖️ Net: {arrow} <b>{net:.2f}$</b>")
    if lang=="es":
        return (f"📊 <b>Tus estadísticas</b>\n"
                f"✅ Ganancias: <b>{win_sum:.2f}$</b> (conteo: {win_cnt})\n"
                f"❌ Pérdidas: <b>{loss_sum:.2f}$</b> (conteo: {loss_cnt})\n"
                f"⚖️ Neto: {arrow} <b>{net:.2f}$</b>")
    if lang=="fr":
        return (f"📊 <b>Vos statistiques</b>\n"
                f"✅ Gains: <b>{win_sum:.2f}$</b> (nombre: {win_cnt})\n"
                f"❌ Pertes: <b>{loss_sum:.2f}$</b> (nombre: {loss_cnt})\n"
                f"⚖️ Net: {arrow} <b>{net:.2f}$</b>")
    return (f"📊 <b>Your statistics</b>\n"
            f"✅ Wins: <b>{win_sum:.2f}$</b> (count: {win_cnt})\n"
            f"❌ Losses: <b>{loss_sum:.2f}$</b> (count: {loss_cnt})\n"
            f"⚖️ Net: {arrow} <b>{net:.2f}$</b>")

def _stats_history_lines(uid_viewer: str, target_uid: str, page: int=1, since: datetime=None):
    stats = _get_stats(); lang = get_lang(uid_viewer); tt = TEXT[lang]
    hist = (stats.get(target_uid,{}) or {}).get("history", [])[:]
    if since is not None:
        def parse(ts):
            try: return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
            except Exception: return datetime.utcnow()
        hist = [h for h in hist if parse(h.get("ts","")) >= since]
    per=10; total=len(hist); pages=max(1,(total+per-1)//per); page=max(1,min(page,pages))
    start=(page-1)*per; part=hist[start:start+per]
    lines=[]
    for h in part:
        at = h.get("ts","").replace("T"," ").replace("Z","")
        base = T(uid_viewer, "stats_line_win" if h.get("kind")=="win" else "stats_line_loss",
                 at=at, amount=f"{float(h.get('amount',0)):.2f}")
        note = h.get("note"); 
        if note: base += f" — {tt['note_label']}: {note}"
        lines.append(base)
    footer = f"\n{page}/{pages}" if total>per else ""
    return ("\n".join(lines) if lines else "—") + footer

def _stats_kb(uid_viewer: str, scope: str="main", page: int=1):
    lang = get_lang(uid_viewer); tt = TEXT[lang]
    kb = types.InlineKeyboardMarkup()
    if scope=="main":
        kb.row(types.InlineKeyboardButton(tt["btn_stats_history"], callback_data="stats:history:1"))
        kb.row(types.InlineKeyboardButton(tt["btn_stats_week"], callback_data="stats:week:1"),
               types.InlineKeyboardButton(tt["btn_stats_month"], callback_data="stats:month:1"))
        kb.row(types.InlineKeyboardButton(tt["btn_stats_export"], callback_data="stats:export"))
        kb.row(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    else:
        prev_p = page-1 if page>1 else 1; next_p = page+1
        kb.row(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"stats:{scope}:{prev_p}"),
               types.InlineKeyboardButton("➡️ Next", callback_data=f"stats:{scope}:{next_p}"))
        kb.row(types.InlineKeyboardButton(tt["back_btn"], callback_data="stats:main"))
    return kb

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("stats:"))
def cb_stats_router(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id); lang = get_lang(uid)
    try: bot.answer_callback_query(c.id)
    except Exception: pass
    parts = (c.data or "stats:main").split(":"); scope = parts[1] if len(parts)>1 else "main"
    page = int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 1
    if scope=="main":
        header = _stats_build_text(uid, uid)
        return bot.send_message(c.message.chat.id, header, reply_markup=_stats_kb(uid,"main"))
    if scope in ("history","week","month"):
        since=None
        if scope=="week": since = datetime.utcnow() - timedelta(days=7)
        elif scope=="month":
            now = datetime.utcnow(); since = datetime(now.year, now.month, 1)
        text = _stats_history_lines(uid, uid, page=page, since=since)
        try:
            bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=_stats_kb(uid, scope, page))
        except Exception:
            bot.send_message(c.message.chat.id, text, reply_markup=_stats_kb(uid, scope, page))
    elif scope=="export":
        import io, csv
        stats = _get_stats(); rows = (stats.get(uid,{}) or {}).get("history", [])
        out = io.StringIO(); wr = csv.writer(out)
        wr.writerow(["ts","kind","amount","note"])
        for r in rows: wr.writerow([r.get("ts",""), r.get("kind",""), r.get("amount",""), r.get("note","")])
        data = out.getvalue().encode("utf-8")
        try: bot.send_document(c.message.chat.id, (f"stats_{uid}.csv", data))
        except Exception: bot.send_message(c.message.chat.id, "CSV error")

# ---------- Callback router (non-stats) ----------
@bot.callback_query_handler(func=lambda c: c.data=="lang_menu")
def cb_lang_menu(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    try: bot.answer_callback_query(c.id)
    except Exception: pass
    bot.send_message(c.message.chat.id, TEXT[get_lang(uid)]["lang_menu_title"], reply_markup=build_lang_kb())

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("set_lang_"))
def cb_set_lang(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    code = (c.data or "").split("_")[-1]
    if code in LANGS: set_lang(uid, code)
    try: bot.answer_callback_query(c.id, text="Language updated")
    except Exception: pass
    if not is_sub_active(uid): 
        tt = TEXT[get_lang(uid)]
        kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport")); kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
        bot.send_message(c.message.chat.id, TEXT[get_lang(uid)]["need_key"], reply_markup=kb)
    else:
        show_main_menu(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data=="daily_trade")
def cb_daily(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    daily = _get_daily() or TEXT[get_lang(uid)]["daily_none"]
    mm = types.InlineKeyboardMarkup()
    mm.add(types.InlineKeyboardButton(TEXT[get_lang(uid)]["btn_lang"], callback_data="lang_menu"),
           types.InlineKeyboardButton(TEXT[get_lang(uid)]["back_btn"], callback_data="go_back"))
    bot.send_message(c.message.chat.id, daily if isinstance(daily,str) else str(daily), reply_markup=mm)

@bot.callback_query_handler(func=lambda c: c.data=="withdraw_menu")
def cb_wmenu(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    open_withdraw_menu(c.message.chat.id, uid)


_pending_withdraw = set()

@bot.callback_query_handler(func=lambda c: c.data=="withdraw_custom")
def cb_withdraw_custom(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    lang = get_lang(uid); tt = TEXT[lang]
    _pending_withdraw.add(uid)
    try: bot.answer_callback_query(c.id)
    except Exception: pass
    bot.send_message(c.message.chat.id, tt["withdraw_enter_msg"])

@bot.message_handler(func=lambda m: str(m.from_user.id) in _pending_withdraw)
def on_custom_withdraw_amount(m: types.Message):
    uid = str(m.from_user.id)
    _pending_withdraw.discard(uid)
    try:
        amount = int((m.text or "").strip())
    except Exception:
        return bot.reply_to(m, TEXT[get_lang(uid)]["withdraw_invalid"])
    return create_withdraw_request(m.chat.id, uid, amount)

@bot.callback_query_handler(func=lambda c: c.data=="withdraw_status")
def cb_wstatus(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id); tt = TEXT[get_lang(uid)]
    reqs = load_json("withdraw_requests") or {}; mm = types.InlineKeyboardMarkup(); found=False
    for rid, r in reqs.items():
        if r.get("user_id")==uid and r.get("status")=="pending":
            mm.add(types.InlineKeyboardButton(f"❌ cancel {r.get('amount',0)}$", callback_data=f"cancel_{rid}")); found=True
    mm.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    msg = tt["requests_waiting"] if found else tt["no_requests"]
    bot.send_message(c.message.chat.id, msg, reply_markup=mm)

@bot.message_handler(commands=["wlist"])
def cmd_wlist(m: types.Message):
    uid = ensure_user(m.chat.id); tt = TEXT[get_lang(uid)]
    if not require_active_or_ask(m.chat.id): return
    reqs = load_json("withdraw_requests") or {}
    mm = types.InlineKeyboardMarkup(); found=False
    for rid, r in reqs.items():
        if r.get("user_id")==uid and r.get("status")=="pending":
            mm.add(types.InlineKeyboardButton(f"❌ cancel {r.get('amount',0)}$", callback_data=f"cancel_{rid}")); found=True
    mm.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    msg = tt["requests_waiting"] if found else tt["no_requests"]
    bot.send_message(m.chat.id, msg, reply_markup=mm)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("withdraw_"))
def cb_withdraw_amount(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id); amount = int((c.data or "withdraw_0").split("_",1)[1])
    create_withdraw_request(c.message.chat.id, uid, amount)

@bot.callback_query_handler(func=lambda c: c.data and (c.data.startswith("wapp_") or c.data.startswith("wden_")))
def cb_wadmin(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    if not is_admin(uid): return bot.answer_callback_query(c.id)
    rid = c.data.split("_",1)[1]
    reqs = load_json("withdraw_requests") or {}; req = reqs.get(rid)
    if not req or req.get("status")!="pending": return bot.send_message(c.message.chat.id, "Already processed or not found.")
    if c.data.startswith("wapp_"):
        req["status"]="approved"; _append_withdraw_log({**req, "processed_at": _now_str(), "action":"approved"}); save_json("withdraw_requests", reqs)
        try: bot.send_message(int(req.get("user_id")), f"✅ تم قبول طلب السحب #{rid} بقيمة {req.get('amount')}$")
        except Exception: pass
        bot.send_message(c.message.chat.id, T(uid,"admin_w_approve", id=rid))
    else:
        users = load_json("users") or {}; u = users.setdefault(req.get("user_id"), {"balance":0}); u["balance"] = float(u.get("balance",0)) + float(req.get("amount",0))
        save_json("users", users); req["status"]="denied"; _append_withdraw_log({**req, "processed_at": _now_str(), "action":"denied"}); save_json("withdraw_requests", reqs)
        try: bot.send_message(int(req.get("user_id")), f"❌ تم رفض طلب السحب #{rid} وتمت إعادة المبلغ.")
        except Exception: pass
        bot.send_message(c.message.chat.id, T(uid,"admin_w_denied", id=rid))

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("cancel_"))
def cb_cancel_withdraw(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id); rid = c.data.split("_",1)[1]
    reqs = load_json("withdraw_requests") or {}; req = reqs.get(rid)
    if req and req.get("user_id")==uid and req.get("status")=="pending":
        users = load_json("users") or {}; u = users.setdefault(uid, {"balance":0}); u["balance"] = float(u.get("balance",0)) + float(req.get("amount",0))
        save_json("users", users); req["status"]="canceled"; save_json("withdraw_requests", reqs)
        return bot.send_message(c.message.chat.id, f"❎ Canceled request #{rid}")
    return bot.send_message(c.message.chat.id, "Nothing to cancel.")

@bot.callback_query_handler(func=lambda c: c.data=="deposit")
def cb_deposit(c: types.CallbackQuery):
    uid=ensure_user(c.from_user.id); tt=TEXT[get_lang(uid)]
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(tt["deposit_paypal"], callback_data="dep_paypal"))
    kb.add(types.InlineKeyboardButton(tt["deposit_bank"], callback_data="dep_bank"))
    kb.add(types.InlineKeyboardButton(tt["deposit_mc"], callback_data="dep_mc"))
    kb.add(types.InlineKeyboardButton(tt["deposit_visa"], callback_data="dep_visa"))
    kb.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="go_back"))
    bot.send_message(c.message.chat.id, tt["deposit_choose"], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("dep_"))
def cb_dep(c: types.CallbackQuery):
    uid=ensure_user(c.from_user.id); tt=TEXT[get_lang(uid)]
    method_map={"dep_cash":tt["deposit_cash"],"dep_paypal":tt["deposit_paypal"],"dep_bank":tt["deposit_bank"],"dep_mc":tt["deposit_mc"],"dep_visa":tt["deposit_visa"]}
    method = method_map.get(c.data,"Payment")
    kb = types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton(tt["contact_us"], url="https://t.me/qlsupport")); kb.add(types.InlineKeyboardButton(tt["back_btn"], callback_data="deposit"))
    bot.send_message(c.message.chat.id, tt["deposit_msg"].format(method=method), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data=="website")
def cb_website(c: types.CallbackQuery):
    uid=ensure_user(c.from_user.id); tt=TEXT[get_lang(uid)]
    url = _website_url()
    if url:
        kb=types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton(tt["btn_website"], url=url))
        bot.send_message(c.message.chat.id, tt["website_msg"], reply_markup=kb)
    else:
        bot.send_message(c.message.chat.id, tt["website_not_set"])

@bot.callback_query_handler(func=lambda c: c.data=="support")
def cb_support(c: types.CallbackQuery):
    uid=ensure_user(c.from_user.id); tt=TEXT[get_lang(uid)]
    kb=types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton(tt["contact_us"], url="https://t.me/qlsupport"))
    bot.send_message(c.message.chat.id, tt["support_msg"], reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data=="go_back")
def cb_go_back(c: types.CallbackQuery):
    uid = ensure_user(c.from_user.id)
    if not is_sub_active(uid):
        tt = TEXT[get_lang(uid)]; kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(tt["btn_buy"], url="https://t.me/qlsupport"))
        kb.add(types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
        bot.send_message(c.message.chat.id, TEXT[get_lang(uid)]["need_key"], reply_markup=kb)
    else:
        show_main_menu(c.message.chat.id)

# ---------- Admin: setdaily/cleardaily ----------
_pending_daily_for: Dict[int, str] = {}

@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts)<2 or not parts[1].isdigit(): return bot.reply_to(m, "Usage: /setdaily <user_id>")
    target = parts[1]; _pending_daily_for[m.from_user.id]=target
    bot.reply_to(m, f"أرسل نص الصفقات اليومية للمستخدم {target}.")

@bot.message_handler(commands=["cleardaily"])
def cmd_cleardaily(m: types.Message):
    uid = ensure_user(m.chat.id)
    if not is_admin(uid): return bot.reply_to(m, T(uid,"admin_only"))
    parts = (m.text or "").split()
    if len(parts)<2 or not parts[1].isdigit(): return bot.reply_to(m, "Usage: /cleardaily <user_id>")
    target = parts[1]; users = load_json("users") or {}; u=users.setdefault(target, {}); u.pop("daily", None); save_json("users", users)
    bot.reply_to(m, f"تم مسح الصفقات اليومية للمستخدم {target}.")

@bot.message_handler(func=lambda m: m.from_user.id in _pending_daily_for and not (m.text or '').strip().startswith('/'))
def on_setdaily_text(m: types.Message):
    target = _pending_daily_for.pop(m.from_user.id); users = load_json("users") or {}; u=users.setdefault(target, {})
    u["daily"] = (m.text or "").strip()[:2000]; save_json("users", users); bot.reply_to(m, f"تم ضبط الصفقات اليومية للمستخدم {target}.")

# ---------- Health + Webhook ----------
@app.route("/healthz", methods=["GET"])
def healthz(): return "OK", 200

@app.route(f"/{API_TOKEN}", methods=["GET","POST"])
def webhook():
    if request.method=="GET": return "OK", 200
    try:
        raw = request.get_data().decode("utf-8")
        if not raw: return "OK", 200
        update = telebot.types.Update.de_json(raw)
        bot.process_new_updates([update])
    except Exception as e:
        log.error("webhook error: %s", e)
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
