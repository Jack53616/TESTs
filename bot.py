import os
import json
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ========= ENV =========
API_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # مثال: https://your-app.onrender.com
USE_DB = bool(os.environ.get("DATABASE_URL"))

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# احصل على اسم البوت (مفيد لو في /cmd@BotName)
BOT_USERNAME = ""
try:
    me = bot.get_me()
    BOT_USERNAME = (me.username or "").lower()
except Exception as e:
    print("get_me error:", e)

# ========= تسجيل الأوامر (زر Commands) =========
try:
    bot.set_my_commands([
        telebot.types.BotCommand("start", "القائمة الرئيسية"),
        telebot.types.BotCommand("help", "قائمة الأوامر"),
        telebot.types.BotCommand("id", "إظهار آيديك"),
        telebot.types.BotCommand("balance", "رصيدك"),
        telebot.types.BotCommand("daily", "صفقة اليوم"),
        telebot.types.BotCommand("withdraw", "طلب سحب"),
        telebot.types.BotCommand("mystatus", "فحص صلاحياتي"),
        telebot.types.BotCommand("addbalance", "STAFF: إضافة رصيد"),
        telebot.types.BotCommand("setdaily", "STAFF: ضبط صفقة اليوم"),
        telebot.types.BotCommand("setbalance", "ADMIN: ضبط رصيد"),
        telebot.types.BotCommand("broadcast", "ADMIN: بث"),
        telebot.types.BotCommand("promote", "ADMIN: ترقية طاقم"),
        telebot.types.BotCommand("demote", "ADMIN: إزالة طاقم"),
        telebot.types.BotCommand("ping", "اختبار سريع"),
    ])
except Exception as e:
    print("set_my_commands error:", e)

# ========= Persistence (ملف -> Postgres عبر db_kv) =========
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

# ========= Webhook =========
if WEBHOOK_BASE:
    try:
        bot.remove_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=f"{WEBHOOK_BASE}/{API_TOKEN}")
        print("Webhook set to:", f"{WEBHOOK_BASE}/{API_TOKEN}")
    except Exception as e:
        print("Failed to set webhook:", e)

# ========= Roles & Staff =========
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

# ========= Normalize & Parse =========
ZERO_WIDTH = "\u200f\u200e\u2066\u2067\u2068\u2069\u200b\uFEFF"

def norm_text(txt: str) -> str:
    if not txt:
        return ""
    t = txt.strip()
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    return t.replace("／", "/")  # سلاش بديل

def parse_command(message):
    """
    يرجّع (cmd, args) مثل ("help", "").
    يعتمد على entities ويزيل @BotName إن وجد.
    """
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

# ========= Helpers & UI =========
def ensure_user(chat_id: int) -> str:
    uid = str(chat_id)
    users = load_json("users.json") or {}
    if uid not in users:
        users[uid] = {"balance": 0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_json("users.json", users)
    return uid

def show_main_menu(chat_id: int):
    users = load_json("users.json") or {}
    uid = str(chat_id)
    balance = users.get(uid, {}).get("balance", 0)
    text = (
        "👋 أهلاً بك في بوت التداول\n\n"
        f"💰 رصيدك: {balance}$\n"
        f"🆔 آيديك: {uid}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📈 صفقة اليوم", callback_data="daily_trade"),
        types.InlineKeyboardButton("💸 سحب", callback_data="withdraw_menu"),
    )
    markup.add(
        types.InlineKeyboardButton("💼 معاملات السحب", callback_data="withdraw_status"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")
    )
    bot.send_message(chat_id, text, reply_markup=markup)

# ========= Router (كل النصوص) =========
@bot.message_handler(content_types=['text'])
def router(message):
    text_raw = message.text or ""

    # لو مش أمر: مرر للأدمن كتنبيه وانتهى
    if not text_raw.strip().startswith(("/", "／")):
        try:
            bot.send_message(ADMIN_ID, f"📩 رسالة من {message.from_user.id}:\n{text_raw}")
        except Exception as e:
            print("forward error:", e)
        return

    cmd, args = parse_command(message)
    print("ROUTER:", cmd, "| ARGS:", repr(args), "| FROM:", message.from_user.id)

    # عامة
    if cmd == "ping":
        return bot.reply_to(message, "pong ✅")

    if cmd == "start":
        ensure_user(message.chat.id)
        return show_main_menu(message.chat.id)

    if cmd == "help":
        uid = message.from_user.id
        base = [
            "🛠 الأوامر المتاحة:",
            "/start - القائمة الرئيسية",
            "/id - يظهر آيديك",
            "/balance - يظهر رصيدك",
            "/daily - صفقة اليوم",
            "/withdraw <amount> - طلب سحب",
            "/mystatus - فحص صلاحياتي",
        ]
        staff_cmds = [
            "— أوامر الطاقم —",
            "/addbalance <user_id> <amount> - زيادة رصيد",
            "/setdaily <نص الصفقة> - ضبط صفقة اليوم",
        ]
        admin_cmds = [
            "— أوامر المدير —",
            "/setbalance <user_id> <amount> - ضبط رصيد",
            "/broadcast <نص> - إرسال للكل",
            "/promote <user_id> - ترقية طاقم",
            "/demote <user_id> - إزالة من الطاقم",
        ]
        lines = base[:]
        if is_staff(uid): lines += [""] + staff_cmds
        if is_admin(uid): lines += [""] + admin_cmds
        return bot.reply_to(message, "\n".join(lines))

    if cmd == "mystatus":
        uid = message.from_user.id
        return bot.reply_to(message, f"Your ID: {uid}\nis_admin: {is_admin(uid)}\nis_staff: {is_staff(uid)}")

    if cmd == "id":
        return bot.reply_to(message, f"🆔 آيديك: {message.from_user.id}")

    if cmd == "balance":
        uid = ensure_user(message.chat.id)
        users = load_json("users.json") or {}
        bal = users.get(uid, {}).get("balance", 0)
        return bot.reply_to(message, f"💰 رصيدك الحالي: {bal}$")

    if cmd == "daily":
        daily = load_json("daily_trade.txt") or "لا توجد صفقة يومية حالياً."
        return bot.reply_to(message, f"📈 صفقة اليوم:\n{daily if isinstance(daily, str) else str(daily)}")

    if cmd == "withdraw":
        if not args or not args.lstrip("+").isdigit():
            return bot.reply_to(message, "❌ الصيغة: /withdraw 50")
        amount = int(args)
        if amount <= 0:
            return bot.reply_to(message, "❌ المبلغ غير صالح.")
        uid = ensure_user(message.chat.id)
        users = load_json("users.json") or {}
        bal = users.get(uid, {}).get("balance", 0)
        if bal < amount:
            return bot.reply_to(message, f"رصيدك غير كافٍ. رصيدك: {bal}$")
        users[uid]["balance"] = bal - amount
        save_json("users.json", users)
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req_id = str(len(withdraw_requests) + 1)
        withdraw_requests[req_id] = {
            "user_id": uid,
            "amount": amount,
            "status": "بانتظار الموافقة",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_json("withdraw_requests.json", withdraw_requests)
        return bot.reply_to(message, f"✅ تم إنشاء طلب السحب #{req_id} بقيمة {amount}$.")

    # Staff/Admin
    if cmd == "setdaily":
        if not is_staff(message.from_user.id):
            return
        if not args:
            return bot.reply_to(message, "❌ اكتب النص: /setdaily <النص>")
        save_json("daily_trade.txt", args)
        return bot.reply_to(message, "تم تحديث صفقة اليوم ✅")

    if cmd == "addbalance":
        if not is_staff(message.from_user.id):
            return
        parts = args.split()
        if len(parts) != 2 or (not parts[0].isdigit()) or (not parts[1].lstrip("-").isdigit()):
            return bot.reply_to(message, "❌ الاستخدام: /addbalance <user_id> <amount>")
        uid_str, amount_str = parts
        amount = int(amount_str)
        users = load_json("users.json") or {}
        users.setdefault(uid_str, {"balance": 0})
        users[uid_str]["balance"] = users[uid_str].get("balance", 0) + amount
        save_json("users.json", users)
        return bot.reply_to(message, f"تم إضافة {amount}$ للمستخدم {uid_str}. الرصيد الجديد: {users[uid_str]['balance']}$")

    if cmd == "setbalance":
        if not is_admin(message.from_user.id):
            return
        parts = args.split()
        if len(parts) != 2 or (not parts[0].isdigit()) or (not parts[1].lstrip("-").isdigit()):
            return bot.reply_to(message, "❌ الاستخدام: /setbalance <user_id> <amount>")
        uid_str, amount_str = parts
        amount = int(amount_str)
        users = load_json("users.json") or {}
        users.setdefault(uid_str, {"balance": 0})
        users[uid_str]["balance"] = amount
        save_json("users.json", users)
        return bot.reply_to(message, f"تم ضبط رصيد المستخدم {uid_str} إلى {amount}$.")

    if cmd == "broadcast":
        if not is_admin(message.from_user.id):
            return
        if not args:
            return bot.reply_to(message, "❌ اكتب الرسالة: /broadcast <النص>")
        users = load_json("users.json") or {}
        text = args
        sent = 0
        for uid in list(users.keys()):
            try:
                bot.send_message(int(uid), text)
                sent += 1
            except Exception:
                pass
        return bot.reply_to(message, f"تم الإرسال إلى {sent} مستخدم.")

    if cmd == "promote":
        if not is_admin(message.from_user.id):
            return
        if not args or (not args.isdigit()):
            return bot.reply_to(message, "❌ الاستخدام: /promote <user_id>")
        uid = int(args)
        s = _load_staff_set(); s.add(uid); _save_staff_set(s)
        return bot.reply_to(message, f"✅ تمت ترقية {uid} إلى طاقم (staff).")

    if cmd == "demote":
        if not is_admin(message.from_user.id):
            return
        if not args or (not args.isdigit()):
            return bot.reply_to(message, "❌ الاستخدام: /demote <user_id>")
        uid = int(args)
        s = _load_staff_set()
        if uid in s:
            s.remove(uid); _save_staff_set(s)
            return bot.reply_to(message, f"✅ تمت إزالة {uid} من الطاقم.")
        else:
            return bot.reply_to(message, "هذا المستخدم ليس ضمن الطاقم.")

# ========= تمرير أوامر TeleBot لنفس الراوتر (ضمان مزدوج) =========
@bot.message_handler(commands=[
    "start","help","id","balance","daily","withdraw","mystatus",
    "addbalance","setdaily","setbalance","broadcast","promote","demote","ping"
])
def _commands_passthrough(message):
    try:
        router(message)
    except Exception as e:
        print("passthrough error:", e)

# ========= Callback Handlers =========
@bot.callback_query_handler(func=lambda call: True)
def all_callbacks(call):
    try: bot.answer_callback_query(call.id)
    except Exception: pass
    data = (call.data or "")
    print("CALLBACK:", data, "from", call.from_user.id)

    if data == "daily_trade":
        trade_info = load_json("daily_trade.txt") or "🚫 لا توجد صفقات."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, trade_info if isinstance(trade_info, str) else str(trade_info), reply_markup=markup)

    if data == "withdraw_menu":
        markup = types.InlineKeyboardMarkup()
        for amount in [10, 20, 30, 50, 100]:
            markup.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
        markup.add(types.InlineKeyboardButton("💰 مبلغ اختياري", callback_data="withdraw_custom"))
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
        return bot.send_message(call.message.chat.id, "🔢 اختر المبلغ للسحب:", reply_markup=markup)

    if data == "withdraw_status":
        withdraw_requests = load_json("withdraw_requests.json") or {}
        uid = str(call.from_user.id)
        markup = types.InlineKeyboardMarkup()
        found = False
        for req_id, req in withdraw_requests.items():
            if req["user_id"] == uid and req["status"] == "بانتظار الموافقة":
                markup.add(types.InlineKeyboardButton(f"❌ إلغاء طلب {req['amount']}$", callback_data=f"cancel_{req_id}"))
                found = True
        markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
        if found:
            return bot.send_message(call.message.chat.id, "💼 طلباتك بانتظار الموافقة:", reply_markup=markup)
        else:
            return bot.send_message(call.message.chat.id, "🚫 لا توجد طلبات حالياً.", reply_markup=markup)

    if data.startswith("withdraw_") and data not in ["withdraw_status", "withdraw_custom"]:
        users = load_json("users.json") or {}
        uid = str(call.from_user.id)
        users.setdefault(uid, {"balance": 0})
        balance = users.get(uid, {}).get("balance", 0)
        amount = int(data.split("_")[1])
        if balance >= amount:
            users[uid]["balance"] = balance - amount
            save_json("users.json", users)
            _add_req_and_notify(uid, amount)
            return bot.send_message(call.message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")
        else:
            return bot.send_message(call.message.chat.id, "❌ لا يوجد رصيد كافٍ.")

    if data == "withdraw_custom":
        bot.send_message(call.message.chat.id, "💬 اكتب المبلغ الذي تريد سحبه:")
        return bot.register_next_step_handler(call.message, process_custom_withdraw)

    if data.startswith("cancel_"):
        withdraw_requests = load_json("withdraw_requests.json") or {}
        users = load_json("users.json") or {}
        req_id = data.split("_")[1]
        req = withdraw_requests.get(req_id)
        if req and req["status"] == "بانتظار الموافقة":
            uid = req["user_id"]; amount = req["amount"]
            users.setdefault(uid, {"balance": 0})
            users[uid]["balance"] = users[uid].get("balance", 0) + amount
            req["status"] = "ملغي"
            save_json("withdraw_requests.json", withdraw_requests)
            save_json("users.json", users)
            return bot.send_message(call.message.chat.id, f"❌ تم إلغاء الطلب واستعادة {amount}$.")
        else:
            return bot.send_message(call.message.chat.id, "⚠️ لا يمكن إلغاء الطلب.")

    if data.startswith("approve_") and is_admin(call.from_user.id):
        withdraw_requests = load_json("withdraw_requests.json") or {}
        req_id = data.split("_")[1]
        req = withdraw_requests.get(req_id)
        if req and req["status"] == "بانتظار الموافقة":
            req["status"] = "مكتمل"
            save_json("withdraw_requests.json", withdraw_requests)
            bot.send_message(int(req["user_id"]), f"✅ تم تنفيذ طلب السحب {req['amount']}$ بنجاح.")
            return bot.send_message(call.message.chat.id, "👌 تم التنفيذ.")
        else:
            return bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")

    if data.startswith("reject_") and is_admin(call.from_user.id):
        withdraw_requests = load_json("withdraw_requests.json") or {}
        users = load_json("users.json") or {}
        req_id = data.split("_")[1]
        req = withdraw_requests.get(req_id)
        if req and req["status"] == "بانتظار الموافقة":
            req["status"] = "مرفوض"
            uid = req["user_id"]; amount = req["amount"]
            users.setdefault(uid, {"balance": 0})
            users[uid]["balance"] = users[uid].get("balance", 0) + amount
            save_json("withdraw_requests.json", withdraw_requests)
            save_json("users.json", users)
            bot.send_message(int(uid), "❌ تم رفض طلب السحب واستعادة الرصيد.")
            return bot.send_message(call.message.chat.id, "🚫 تم الرفض وإرجاع الرصيد.")
        else:
            return bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")

    if data == "stats":
        trades = load_json("trades.json") or {}
        uid = str(call.from_user.id)
        user_trades = trades.get(uid, [])
        if not user_trades:
            return bot.send_message(call.message.chat.id, "📊 لا توجد صفقات مسجلة.")
        total_profit = 0
        text = "📊 إحصائياتك:\n\n"
        for i, t in enumerate(user_trades, 1):
            text += f"{i}- {t['date']} | ربح: {t['profit']}$\n"
            total_profit += t['profit']
        text += f"\n✅ إجمالي الربح: {total_profit}$"
        return bot.send_message(call.message.chat.id, text)

    if data == "go_back":
        return show_main_menu(call.message.chat.id)

def _add_req_and_notify(uid: str, amount: int):
    withdraw_requests = load_json("withdraw_requests.json") or {}
    req_id = str(len(withdraw_requests) + 1)
    withdraw_requests[req_id] = {
        "user_id": uid,
        "amount": amount,
        "status": "بانتظار الموافقة",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_json("withdraw_requests.json", withdraw_requests)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"✅ قبول {req_id}", callback_data=f"approve_{req_id}"),
        types.InlineKeyboardButton(f"❌ رفض {req_id}", callback_data=f"reject_{req_id}")
    )
    try:
        bot.send_message(ADMIN_ID, f"🔔 طلب سحب جديد:\nمستخدم: {uid}\nالمبلغ: {amount}$", reply_markup=markup)
    except Exception as e:
        print("notify admin error:", e)

def process_custom_withdraw(message):
    users = load_json("users.json") or {}
    uid = str(message.chat.id)
    users.setdefault(uid, {"balance": 0})
    balance = users.get(uid, {}).get("balance", 0)
    try:
        amount = int(norm_text(message.text))
        if amount < 10:
            bot.send_message(message.chat.id, "❌ الحد الأدنى 10$.")
        elif balance >= amount:
            users[uid]["balance"] = balance - amount
            save_json("users.json", users)
            _add_req_and_notify(uid, amount)
            bot.send_message(message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")
        else:
            bot.send_message(message.chat.id, "❌ لا يوجد رصيد كافٍ.")
    except:
        bot.send_message(message.chat.id, "❌ أدخل رقم صحيح.")

# ========= Flask Webhook =========
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route(f"/{API_TOKEN}", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        print("Webhook error:", e)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
