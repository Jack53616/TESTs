# -*- coding: utf-8 -*-
"""
Telegram bot (Render-ready) — features:
- i18n (ar/en/tr/es/fr)
- Main menu: Daily / Withdraw / Withdrawal requests / Stats / Language / Deposit / Website / Support
- Withdraw via buttons or /withdraw <amount>
- Per-user stats (win/loss) with admin record mode and commands
- Broadcast for admin
- Non-command messages are relayed to admin
- Storage: DB (db_kv.py) if DATABASE_URL, else JSON files
- Fixes:
  * Robust HTML escaping in help
  * __main__ runs Flask when WEBHOOK_URL is set (Render) to avoid polling conflict
"""
import os, json, logging, html
from datetime import datetime
from typing import Dict, Any, Optional
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
DATABASE_URL  = os.getenv("DATABASE_URL", "").strip()
SUPPORT_USER  = os.getenv("SUPPORT_USERNAME", "qlsupport").lstrip("@") or "qlsupport"
WEBSITE_URL   = os.getenv("WEBSITE_URL", "").strip()  # ← ضع رابط موقعك هنا أو كمتغير بيئة

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
    "stats": "stats.json",
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
        "btn_deposit": "💳 الإيداع",
        "btn_website": "🌍 موقعنا",
        "btn_support": "📞 تواصل مع الدعم",
        "help_title": "🛠 الأوامر المتاحة:",
        "help_public": [
            "/start - القائمة الرئيسية",
            "/id - عرض آيديك",
            "/balance - رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw &lt;amount&gt; - طلب سحب (مثال: /withdraw 50)",
            "/mystats - إحصائياتي"
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
        # admin / record
        "admin_only": "🚫 هذا الأمر للأدمن فقط.",
        "record_target_is": "🎯 تم اختيار المستخدم: {uid}. أرسل أرقام مثل 10 (ربح) أو 10- (خسارة).",
        "record_mode_on": "🟢 تم تفعيل وضع التسجيل للمستخدم {uid}.",
        "record_mode_off": "🛑 تم إنهاء وضع التسجيل.",
        "record_saved_win": "✅ تم تسجيل ربح +{amount}$ للمستخدم {uid} — {at}",
        "record_saved_loss": "✅ تم تسجيل خسارة -{amount}$ للمستخدم {uid} — {at}",
        "record_invalid_amount": "❌ الرجاء إرسال رقم صحيح (مثال: 10 أو 10-).",
        "userstats_header": "📊 إحصائيات المستخدم {uid}",
        # balance link / deduct
        "balance_linked_user": "✅ تم ربط البوت بحسابك التداول.\n💰 رصيدك الآن: {bal}$",
        "balance_updated_admin": "✅ تم تحديث رصيد {uid}. الرصيد الآن: {bal}$",
        "balance_deduct_user": "🔻 تم خصم {amount}$ من رصيدك.\n💰 رصيدك الآن: {bal}$",
        "balance_deduct_admin": "🔻 تم الخصم من رصيد {uid}. الرصيد الآن: {bal}$",
        # broadcast
        "broadcast_need_text": "❌ الصيغة: /broadcast النص",
        "broadcast_done": "📢 تم الإرسال: نجاح {ok} / فشل {fail}",
        # relay
        "relayed_to_admin": "📨 تم إرسال رسالتك للإدارة.",
    },
    "en": {
        "welcome": "👋 Welcome to the trading bot\n\n💰 Your balance: {balance}$\n🆔 Your ID: {uid}",
        "btn_daily": "📈 Daily trade",
        "btn_withdraw": "💸 Withdraw",
        "btn_wstatus": "💼 Withdrawal requests",
        "btn_stats": "📊 Stats",
        "btn_lang": "🌐 Language",
        "btn_deposit": "💳 Deposit",
        "btn_website": "🌍 Website",
        "btn_support": "📞 Contact support",
        "help_title": "🛠 Available commands:",
        "help_public": [
            "/start - Main menu",
            "/id - Show your ID",
            "/balance - Your balance",
            "/daily - Daily trade",
            "/withdraw &lt;amount&gt; - Request withdrawal",
            "/mystats - My stats"
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
        "admin_only": "🚫 Admin only.",
        "record_target_is": "🎯 Target user: {uid}. Send numbers like 10 (win) or 10- (loss).",
        "record_mode_on": "🟢 Record mode ON for user {uid}.",
        "record_mode_off": "🛑 Record mode OFF.",
        "record_saved_win": "✅ Recorded WIN +{amount}$ for {uid} — {at}",
        "record_saved_loss": "✅ Recorded LOSS -{amount}$ for {uid} — {at}",
        "record_invalid_amount": "❌ Send a valid number (e.g., 10 or 10-).",
        "userstats_header": "📊 Stats for user {uid}",
        "balance_linked_user": "✅ The bot is linked to your trading account.\n💰 Your balance is now: {bal}$",
        "balance_updated_admin": "✅ Balance updated for {uid}. New balance: {bal}$",
        "balance_deduct_user": "🔻 {amount}$ has been deducted.\n💰 Your new balance: {bal}$",
        "balance_deduct_admin": "🔻 Deducted from {uid}. New balance: {bal}$",
        "broadcast_need_text": "❌ Usage: /broadcast text",
        "broadcast_done": "📢 Sent: OK {ok} / Fail {fail}",
        "relayed_to_admin": "📨 Your message was sent to the admin.",
    },
    "tr": {
        "welcome": "👋 Trading botuna hoş geldin\n\n💰 Bakiyen: {balance}$\n🆔 ID: {uid}",
        "btn_daily": "📈 Günün işlemi",
        "btn_withdraw": "💸 Çekim",
        "btn_wstatus": "💼 Çekim talepleri",
        "btn_stats": "📊 İstatistikler",
        "btn_lang": "🌐 Dil",
        "btn_deposit": "💳 Yatırma",
        "btn_website": "🌍 Web sitemiz",
        "btn_support": "📞 Destek ile iletişim",
        "help_title": "🛠 Kullanılabilir komutlar:",
        "help_public": [
            "/start - Ana menü",
            "/id - ID'ni göster",
            "/balance - Bakiyen",
            "/daily - Günün işlemi",
            "/withdraw &lt;tutar&gt; - Çekim isteği",
            "/mystats - İstatistiklerim"
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
        "admin_only": "🚫 Sadece yönetici.",
        "record_target_is": "🎯 Hedef kullanıcı: {uid}. 10 (kazanç) veya 10- (kayıp) gibi sayılar gönderin.",
        "record_mode_on": "🟢 {uid} için kayıt modu AÇIK.",
        "record_mode_off": "🛑 Kayıt modu KAPALI.",
        "record_saved_win": "✅ {uid} için KAZANÇ +{amount}$ — {at}",
        "record_saved_loss": "✅ {uid} için KAYIP -{amount}$ — {at}",
        "record_invalid_amount": "❌ Geçerli sayı gönderin (örn. 10 veya 10-).",
        "userstats_header": "📊 {uid} kullanıcısının istatistikleri",
        "balance_linked_user": "✅ Bot, işlem hesabınıza bağlandı.\n💰 Güncel bakiyeniz: {bal}$",
        "balance_updated_admin": "✅ {uid} için bakiye güncellendi. Yeni bakiye: {bal}$",
        "balance_deduct_user": "🔻 Bakiyenizden {amount}$ düşüldü.\n💰 Yeni bakiyeniz: {bal}$",
        "balance_deduct_admin": "🔻 {uid} kullanıcısından düşüldü. Yeni bakiye: {bal}$",
        "broadcast_need_text": "❌ Kullanım: /broadcast metin",
        "broadcast_done": "📢 Gönderildi: Başarılı {ok} / Başarısız {fail}",
        "relayed_to_admin": "📨 Mesajınız yöneticiye gönderildi.",
    },
    "es": {
        "welcome": "👋 Bienvenido al bot de trading\n\n💰 Tu saldo: {balance}$\n🆔 Tu ID: {uid}",
        "btn_daily": "📈 Operación del día",
        "btn_withdraw": "💸 Retirar",
        "btn_wstatus": "💼 Solicitudes de retiro",
        "btn_stats": "📊 Estadísticas",
        "btn_lang": "🌐 Idioma",
        "btn_deposit": "💳 Depósito",
        "btn_website": "🌍 Sitio web",
        "btn_support": "📞 Contactar soporte",
        "help_title": "🛠 Comandos disponibles:",
        "help_public": [
            "/start - Menú principal",
            "/id - Mostrar tu ID",
            "/balance - Tu saldo",
            "/daily - Operación del día",
            "/withdraw &lt;monto&gt; - Solicitar retiro",
            "/mystats - Mis estadísticas"
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
        "admin_only": "🚫 Solo admin.",
        "record_target_is": "🎯 Usuario objetivo: {uid}. Envía números como 10 (ganancia) o 10- (pérdida).",
        "record_mode_on": "🟢 Modo de registro ACTIVADO para {uid}.",
        "record_mode_off": "🛑 Modo de registro DESACTIVADO.",
        "record_saved_win": "✅ Registrada GANANCIA +{amount}$ para {uid} — {at}",
        "record_saved_loss": "✅ Registrada PÉRDIDA -{amount}$ para {uid} — {at}",
        "record_invalid_amount": "❌ Envía un número válido (ej. 10 o 10-).",
        "userstats_header": "📊 Estadísticas de {uid}",
        "balance_linked_user": "✅ El bot está vinculado a tu cuenta de trading.\n💰 Tu saldo ahora es: {bal}$",
        "balance_updated_admin": "✅ Saldo actualizado para {uid}. Nuevo saldo: {bal}$",
        "balance_deduct_user": "🔻 Se ha descontado {amount}$. \n💰 Tu nuevo saldo: {bal}$",
        "balance_deduct_admin": "🔻 Descontado a {uid}. Nuevo saldo: {bal}$",
        "broadcast_need_text": "❌ Uso: /broadcast texto",
        "broadcast_done": "📢 Enviado: OK {ok} / Fallo {fail}",
        "relayed_to_admin": "📨 Tu mensaje fue enviado al administrador.",
    },
    "fr": {
        "welcome": "👋 Bienvenue dans le bot de trading\n\n💰 Votre solde : {balance}$\n🆔 Votre ID : {uid}",
        "btn_daily": "📈 Trade du jour",
        "btn_withdraw": "💸 Retrait",
        "btn_wstatus": "💼 Demandes de retrait",
        "btn_stats": "📊 Statistiques",
        "btn_lang": "🌐 Langue",
        "btn_deposit": "💳 Dépôt",
        "btn_website": "🌍 Notre site",
        "btn_support": "📞 Contacter le support",
        "help_title": "🛠 Commandes disponibles :",
        "help_public": [
            "/start - Menu principal",
            "/id - Afficher votre ID",
            "/balance - Votre solde",
            "/daily - Trade du jour",
            "/withdraw &lt;montant&gt; - Demande de retrait",
            "/mystats - Mes statistiques"
        ],
        "daily_none": "Aucun trade du jour pour le moment.",
        "cleardaily_ok": "🧹 Trade du jour supprimé.",
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
        "deposit_msg": "Pour payer via {method}, contactez-nous directement. Touchez ci-dessous :",
        "contact_us": "📩 Nous contacter",
        "website_msg": "🔥 Touchez pour visiter notre site :",
        "website_not_set": "ℹ️ L’URL du site n’est pas encore définie.",
        "support_msg": "Touchez ci-dessous pour contacter le support :",
        "stats_title": "📊 Vos statistiques",
        "stats_wins": "✅ Gains : {sum}$ (nb : {count})",
        "stats_losses": "❌ Pertes : {sum}$ (nb : {count})",
        "stats_net": "⚖️ Net : {net}$",
        "stats_no_data": "Aucune opération pour l’instant.",
        "stats_line_win": "{at} — Gain +{amount}$",
        "stats_line_loss": "{at} — Perte -{amount}$",
        "admin_only": "🚫 Réservé à l’admin.",
        "record_target_is": "🎯 Utilisateur ciblé : {uid}. Envoyez des nombres comme 10 (gain) ou 10- (perte).",
        "record_mode_on": "🟢 Mode enregistrement ACTIVÉ pour {uid}.",
        "record_mode_off": "🛑 Mode enregistrement DÉSACTIVÉ.",
        "record_saved_win": "✅ GAIN +{amount}$ enregistré pour {uid} — {at}",
        "record_saved_loss": "✅ PERTE -{amount}$ enregistrée pour {uid} — {at}",
        "record_invalid_amount": "❌ Envoyez un nombre valide (ex : 10 ou 10-).",
        "userstats_header": "📊 Statistiques de l’utilisateur {uid}",
        "balance_linked_user": "✅ Le bot est lié à votre compte de trading.\n💰 Votre solde est maintenant : {bal}$",
        "balance_updated_admin": "✅ Solde mis à jour pour {uid}. Nouveau solde : {bal}$",
        "balance_deduct_user": "🔻 {amount}$ ont été déduits.\n💰 Nouveau solde : {bal}$",
        "balance_deduct_admin": "🔻 Déduit pour {uid}. Nouveau solde : {bal}$",
        "broadcast_need_text": "❌ Usage : /broadcast texte",
        "broadcast_done": "📢 Envoyé : OK {ok} / Échec {fail}",
        "relayed_to_admin": "📨 Votre message a été envoyé à l’admin.",
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

def T(user_id: str, key: str, **kwargs) -> str:
    lang = get_lang(user_id)
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
        users[uid] = {"balance": 0, "role": "admin" if chat_id == ADMIN_ID else "user",
                      "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      "lang": "ar"}
        save_json("users.json", users)
    return uid

def is_admin(uid: str) -> bool:
    users = load_json("users.json") or {}
    return (users.get(uid, {}) or {}).get("role") == "admin"

# ---------- Stats helpers ----------
def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def stats_get(uid: str) -> Dict[str, Any]:
    stats = load_json("stats.json") or {}
    return stats.get(uid, {
        "events": [],  # [{"type":"win"|"loss","amount":int,"at":str}]
        "totals": {"win": {"count": 0, "sum": 0}, "loss": {"count": 0, "sum": 0}}
    })

def stats_save(uid: str, data: Dict[str, Any]) -> None:
    stats = load_json("stats.json") or {}
    stats[uid] = data
    save_json("stats.json", stats)

def stats_add(uid: str, typ: str, amount: int) -> None:
    data = stats_get(uid)
    data["events"].insert(0, {"type": typ, "amount": int(amount), "at": _now_str()})
    t = data["totals"].setdefault(typ, {"count": 0, "sum": 0})
    t["count"] += 1
    t["sum"] += int(amount)
    stats_save(uid, data)

def format_user_stats(viewer_uid: str, target_uid: str, limit: int = 10) -> str:
    d = stats_get(target_uid)
    wins = d["totals"]["win"]
    losses = d["totals"]["loss"]
    net = int(wins["sum"]) - int(losses["sum"])
    header = f"<b>{T(viewer_uid, 'stats_title' if viewer_uid==target_uid else 'userstats_header', uid=target_uid)}</b>"
    lines = [
        header,
        T(viewer_uid, "stats_wins", sum=wins["sum"], count=wins["count"]),
        T(viewer_uid, "stats_losses", sum=losses["sum"], count=losses["count"]),
        T(viewer_uid, "stats_net", net=net)
    ]
    events = d["events"][:limit]
    if not events:
        lines.append(T(viewer_uid, "stats_no_data"))
    else:
        for e in events:
            if e["type"] == "win":
                lines.append(T(viewer_uid, "stats_line_win", at=e["at"], amount=e["amount"]))
            else:
                lines.append(T(viewer_uid, "stats_line_loss", at=e["at"], amount=e["amount"]))
    return "\n".join(lines)

# in-memory admin record modes {admin_uid: target_uid}
RECORD_MODE: Dict[str, str] = {}

# ---------- UI ----------
def main_menu_markup(uid: str) -> telebot.types.InlineKeyboardMarkup:
    tt = TEXT[get_lang(uid)]
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton(tt["btn_daily"], callback_data="daily_trade"),
          types.InlineKeyboardButton(tt["btn_withdraw"], callback_data="withdraw_menu"))
    m.add(types.InlineKeyboardButton(tt["btn_wstatus"], callback_data="withdraw_status"),
          types.InlineKeyboardButton(tt["btn_stats"], callback_data="stats"))
    m.add(types.InlineKeyboardButton(tt["btn_deposit"], callback_data="deposit_menu"),
          types.InlineKeyboardButton(tt["btn_lang"], callback_data="lang_menu"))
    # new row for website & support
    m.add(types.InlineKeyboardButton(tt["btn_website"], callback_data="open_website"),
          types.InlineKeyboardButton(tt["btn_support"], callback_data="open_support"))
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

@bot.message_handler(commands=["cleardaily"])
def cmd_cleardaily(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    save_daily_text("")
    bot.reply_to(message, T(uid, "cleardaily_ok"))

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

@bot.message_handler(commands=["mystats"])
def cmd_mystats(message: types.Message):
    uid = ensure_user(message.chat.id)
    bot.reply_to(message, format_user_stats(uid, uid))

@bot.message_handler(commands=["userstats"])
def cmd_userstats(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /userstats <user_id>")
    target = parts[1]
    bot.reply_to(message, format_user_stats(uid, target))

@bot.message_handler(commands=["record_set"])
def cmd_record_set(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        return bot.reply_to(message, "Usage: /record_set <user_id>")
    target = parts[1]
    RECORD_MODE[uid] = target
    bot.reply_to(message, T(uid, "record_mode_on", uid=target) + "\n" + T(uid, "record_target_is", uid=target))

@bot.message_handler(commands=["record_done"])
def cmd_record_done(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    if uid in RECORD_MODE:
        del RECORD_MODE[uid]
    bot.reply_to(message, T(uid, "record_mode_off"))

@bot.message_handler(commands=["win", "loss"])
def cmd_win_loss(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        return bot.reply_to(message, f"Usage: /{message.text.split()[0][1:]} <user_id> <amount>")
    target, amount_str = parts[1], parts[2]
    try:
        amount = int(amount_str)
    except Exception:
        return bot.reply_to(message, T(uid, "record_invalid_amount"))
    typ = "win" if message.text.startswith("/win") else "loss"
    stats_add(target, typ, amount)
    at = _now_str()
    if typ == "win":
        bot.reply_to(message, T(uid, "record_saved_win", amount=amount, uid=target, at=at))
    else:
        bot.reply_to(message, T(uid, "record_saved_loss", amount=amount, uid=target, at=at))

@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        return bot.reply_to(message, "Usage: /addbalance &lt;user_id&gt; &lt;amount&gt;")
    target, amount = parts[1], int(parts[2])
    users = load_json("users.json") or {}
    users.setdefault(target, {"balance": 0})
    users[target]["balance"] = users[target].get("balance", 0) + amount
    save_json("users.json", users)

    # Notify target
    try:
        bot.send_message(int(target), T(target, "balance_linked_user", bal=users[target]["balance"]))
    except Exception as e:
        log.warning("Cannot message target %s: %s", target, e)

    # Confirm to admin
    bot.reply_to(message, T(uid, "balance_updated_admin", uid=target, bal=users[target]["balance"]))

@bot.message_handler(commands=["removebalance"])
def cmd_removebalance(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        return bot.reply_to(message, "Usage: /removebalance &lt;user_id&gt; &lt;amount&gt;")
    target, amount = parts[1], int(parts[2])
    users = load_json("users.json") or {}
    users.setdefault(target, {"balance": 0})
    new_bal = users[target].get("balance", 0) - amount
    if new_bal < 0:
        new_bal = 0
    users[target]["balance"] = new_bal
    save_json("users.json", users)

    # Notify target about deduction
    try:
        bot.send_message(int(target), T(target, "balance_deduct_user", amount=amount, bal=new_bal))
    except Exception as e:
        log.warning("Cannot message target %s: %s", target, e)

    # Confirm to admin
    bot.reply_to(message, T(uid, "balance_deduct_admin", uid=target, bal=new_bal))

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message: types.Message):
    uid = ensure_user(message.chat.id)
    if not is_admin(uid):
        return bot.reply_to(message, T(uid, "admin_only"))
    raw = (message.text or "")
    if " " not in raw.strip():
        return bot.reply_to(message, T(uid, "broadcast_need_text"))
    text = raw.split(" ", 1)[1].strip()
    users = load_json("users.json") or {}
    ok = fail = 0
    for tuid in list(users.keys()):
        try:
            bot.send_message(int(tuid), text)
            ok += 1
        except Exception:
            fail += 1
    bot.reply_to(message, T(uid, "broadcast_done", ok=ok, fail=fail))

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
    if cmd == "/mystats":
        return cmd_mystats(message)
    return

@bot.message_handler(func=lambda m: bool(m.text) and m.text.strip().startswith(("/", "／", "⁄")))
def any_command_like(message: types.Message):
    try:
        return dispatch_command(message)
    except Exception as e:
        log.error("fallback dispatch error: %s", e)

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
        return bot.send_message(call.message.chat.id, format_user_stats(uid, uid))

    if data == "deposit_menu":
        tt = TEXT[get_lang(uid)]
        mm = types.InlineKeyboardMarkup(row_width=2)
        mm.add(types.InlineKeyboardButton(tt["deposit_cash"], callback_data="dep_cash"),
               types.InlineKeyboardButton(tt["deposit_paypal"], callback_data="dep_paypal"))
        mm.add(types.InlineKeyboardButton(tt["deposit_bank"], callback_data="dep_bank"))
        mm.add(types.InlineKeyboardButton(tt["deposit_mc"], callback_data="dep_mc"),
               types.InlineKeyboardButton(tt["deposit_visa"], callback_data="dep_visa"))
        mm.add(types.InlineKeyboardButton("🔙", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, tt["deposit_choose"], reply_markup=mm)

    if data.startswith("dep_"):
        tt = TEXT[get_lang(uid)]
        methods = {
            "dep_cash": tt["deposit_cash"],
            "dep_paypal": tt["deposit_paypal"],
            "dep_bank": tt["deposit_bank"],
            "dep_mc": tt["deposit_mc"],
            "dep_visa": tt["deposit_visa"],
        }
        method = methods.get(data, "Payment")
        chat_link = f"https://t.me/{SUPPORT_USER}"
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(tt["contact_us"], url=chat_link))
        return bot.send_message(call.message.chat.id, T(uid, "deposit_msg", method=method), reply_markup=mm)

    if data == "open_website":
        tt = TEXT[get_lang(uid)]
        if WEBSITE_URL:
            mm = types.InlineKeyboardMarkup()
            mm.add(types.InlineKeyboardButton(tt["btn_website"], url=WEBSITE_URL))
            return bot.send_message(call.message.chat.id, tt["website_msg"], reply_markup=mm)
        else:
            return bot.send_message(call.message.chat.id, tt["website_not_set"])

    if data == "open_support":
        tt = TEXT[get_lang(uid)]
        chat_link = f"https://t.me/{SUPPORT_USER}"
        mm = types.InlineKeyboardMarkup()
        mm.add(types.InlineKeyboardButton(tt["contact_us"], url=chat_link))
        return bot.send_message(call.message.chat.id, tt["support_msg"], reply_markup=mm)

# ---------- Non-command messages: relay to admin ----------
@bot.message_handler(func=lambda m: bool(m.text) and not m.text.strip().startswith(("/", "／", "⁄")))
def relay_to_admin(message: types.Message):
    uid = ensure_user(message.chat.id)
    try:
        uname = f"@{message.from_user.username}" if message.from_user.username else ""
    except Exception:
        uname = ""
    info = f"📨 MSG from {message.from_user.id} {html.escape(uname)}\n" \
           f"Name: {html.escape((message.from_user.first_name or '') + ' ' + (message.from_user.last_name or ''))}\n" \
           f"Text:\n{html.escape(message.text or '')}"
    try:
        bot.send_message(ADMIN_ID, info)
    except Exception as e:
        log.error("Failed relaying to admin: %s", e)
    try:
        bot.reply_to(message, T(uid, "relayed_to_admin"))
    except Exception:
        pass

# ---------- Record mode numeric handler (admin only, numbers) ----------
@bot.message_handler(func=lambda m: (str(m.from_user.id) in RECORD_MODE) and bool(m.text) and not m.text.strip().startswith(("/", "／", "⁄")))
def record_mode_numbers(message: types.Message):
    admin_uid = ensure_user(message.from_user.id)
    target = RECORD_MODE.get(admin_uid)
    if not target:
        return
    txt = (message.text or "").strip()
    typ: Optional[str] = None
    amt_str = None
    if txt.endswith("-") and txt[:-1].isdigit():
        typ = "loss"; amt_str = txt[:-1]
    elif txt.startswith("-") and txt[1:].isdigit():
        typ = "loss"; amt_str = txt[1:]
    elif txt.isdigit():
        typ = "win"; amt_str = txt
    if typ is None or not amt_str:
        return bot.reply_to(message, T(admin_uid, "record_invalid_amount"))
    amount = int(amt_str)
    stats_add(target, typ, amount)
    at = _now_str()
    if typ == "win":
        bot.reply_to(message, T(admin_uid, "record_saved_win", amount=amount, uid=target, at=at))
    else:
        bot.reply_to(message, T(admin_uid, "record_saved_loss", amount=amount, uid=target, at=at))

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

# Set webhook automatically if WEBHOOK_URL present
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
    if WEBHOOK_URL:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    else:
        try:
            bot.remove_webhook()
        except Exception:
            pass
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
