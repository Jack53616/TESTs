# bot.py
import os
import json
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ========= ENV =========
API_TOKEN = os.environ.get("BOT_TOKEN")  # لازم تضيفه في Render
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # مثال: https://your-app.onrender.com
USE_DB = bool(os.environ.get("DATABASE_URL"))

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# ========= Persistence (Files -> Postgres عبر db_kv) =========
if USE_DB:
    # يتطلّب وجود db_kv.py مرفوع مع المشروع
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

# ========= Normalize & Router (يحل مشكلة الأوامر اللي ما تنمسك) =========
ZERO_WIDTH = "\u200f\u200e\u2066\u2067\u2068\u2069\u200b\uFEFF"

def norm_cmd(txt: str) -> str:
    if not txt:
        return ""
    t = txt.strip()
    for ch in ZERO_WIDTH:
        t = t.replace(ch, "")
    # بدائل سلاش غريبة
    t = t.replace("／", "/")
    return t

@bot.message_handler(func=lambda m: bool(getattr(m, "text", "")) and m.text.strip().startswith(("/", "／")))
def cmd_router(message):
    t = norm_cmd(message.text)
    print("ROUTER GOT:", repr(t))
    if t == "/help": return cmd_help(message)
    if t == "/start": return cmd_start(message)
    if t == "/id": return cmd_id(message)
    if t == "/balance": return cmd_balance(message)
    if t.startswith("/daily"): return cmd_daily(message)
    if t.startswith("/withdraw"): return cmd_withdraw(message)
    if t.startswith("/addbalance"): return cmd_addbalance(message)
    if t.startswith("/setdaily"): return cmd_setdaily(message)
    if t.startswith("/setbalance"): return cmd_setbalance(message)
    if t.startswith("/broadcast"): return cmd_broadcast(message)
    if t.startswith("/promote"): return cmd_promote(message)
    if t.startswith("/demote"): return cmd_demote(message)
    if t.startswith("/mystatus"): return cmd_mystatus(message)
    # لو ما طابقت شي، خليه يمر لباقي الهاندلرز (بس غالباً ما يلزم)
    return

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

# ========= Commands (User) =========
@bot.message_handler(commands=["start"])
def cmd_start(message):
    print("CMD /start by", message.from_user.id)
    ensure_user(message.chat.id)
    show_main_menu(message.chat.id)

@bot.message_handler(commands=["help"])
def cmd_help(message):
    print("CMD /help by", message.from_user.id)
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
        "/promote <user_id> - ترقية لطاقم",
        "/demote <user_id> - إزالة من الطاقم",
    ]
    lines = base[:]
    if is_staff(uid): lines += [""] + staff_cmds
    if is_admin(uid): lines += [""] + admin_cmds
    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(commands=["mystatus"])
def cmd_mystatus(message):
    uid = message.from_user.id
    bot.reply_to(message, f"Your ID: {uid}\nis_admin: {is_admin(uid)}\nis_staff: {is_staff(uid)}")

@bot.message_handler(commands=["id"])
def cmd_id(message):
    bot.reply_to(message, f"🆔 آيديك: {message.from_user.id}")

@bot.message_handler(commands=["balance"])
def cmd_balance(message):
    uid = ensure_user(message.chat.id)
    users = load_json("users.json") or {}
    bal = users.get(uid, {}).get("balance", 0)
    bot.reply_to(message, f"💰 رصيدك الحالي: {bal}$")

@bot.message_handler(commands=["daily"])
def cmd_daily(message):
    daily = load_json("daily_trade.txt") or "لا توجد صفقة يومية حالياً."
    bot.reply_to(message, f"📈 صفقة اليوم:\n{daily if isinstance(daily, str) else str(daily)}")

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message):
    parts = norm_cmd(message.text).split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().lstrip("+").isdigit():
        bot.reply_to(message, "اكتب المبلغ: /withdraw 50")
        return
    amount = int(parts[1].strip())
    if amount <= 0:
        bot.reply_to(message, "المبلغ غير صالح.")
        return
    uid = ensure_user(message.chat.id)
    users = load_json("users.json") or {}
    bal = users.get(uid, {}).get("balance", 0)
    if bal < amount:
        bot.reply_to(message, f"رصيدك غير كافٍ. رصيدك: {bal}$")
        return
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
    bot.reply_to(message, f"✅ تم إنشاء طلب السحب #{req_id} بقيمة {amount}$.")

# ========= Commands (Staff/Admin) =========
@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message):
    if not is_staff(message.from_user.id): return
    parts = norm_cmd(message.text).split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        bot.reply_to(message, "الاستخدام: /addbalance <user_id> <amount>")
        return
    uid_str, amount_str = parts[1], parts[2]
    amount = int(amount_str)
    users = load_json("users.json") or {}
    users.setdefault(uid_str, {"balance": 0})
    users[uid_str]["balance"] = users[uid_str].get("balance", 0) + amount
    save_json("users.json", users)
    bot.reply_to(message, f"تم إضافة {amount}$ للمستخدم {uid_str}. الرصيد الجديد: {users[uid_str]['balance']}$")

@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(message):
    if not is_staff(message.from_user.id): return
    parts = norm_cmd(message.text).split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "اكتب نص الصفقة: /setdaily <النص>")
        return
    save_json("daily_trade.txt", parts[1])
    bot.reply_to(message, "تم تحديث صفقة اليوم ✅")

@bot.message_handler(commands=["setbalance"])
def cmd_setbalance(message):
    if not is_admin(message.from_user.id): return
    parts = norm_cmd(message.text).split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        bot.reply_to(message, "الاستخدام: /setbalance <user_id> <amount>")
        return
    uid_str, amount_str = parts[1], parts[2]
    amount = int(amount_str)
    users = load_json("users.json") or {}
    users.setdefault(uid_str, {"balance": 0})
    users[uid_str]["balance"] = amount
    save_json("users.json", users)
    bot.reply_to(message, f"تم ضبط رصيد المستخدم {uid_str} إلى {amount}$.")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not is_admin(message.from_user.id): return
    parts = norm_cmd(message.text).split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "اكتب الرسالة: /broadcast <النص>")
        return
    users = load_json("users.json") or {}
    text = parts[1]
    sent = 0
    for uid in list(users.keys()):
        try:
            bot.send_message(int(uid), text)
            sent += 1
        except Exception:
            pass
    bot.reply_to(message, f"تم الإرسال إلى {sent} مستخدم.")

@bot.message_handler(commands=["promote"])
def cmd_promote(message):
    if not is_admin(message.from_user.id): return
    parts = norm_cmd(message.text).split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "الاستخدام: /promote <user_id>")
        return
    uid = int(parts[1].strip())
    s = _load_staff_set(); s.add(uid); _save_staff_set(s)
    bot.reply_to(message, f"✅ تمت ترقية {uid} إلى طاقم (staff).")

@bot.message_handler(commands=["demote"])
def cmd_demote(message):
    if not is_admin(message.from_user.id): return
    parts = norm_cmd(message.text).split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "الاستخدام: /demote <user_id>")
        return
    uid = int(parts[1].strip())
    s = _load_staff_set()
    if uid in s:
        s.remove(uid); _save_staff_set(s)
        bot.reply_to(message, f"✅ تمت إزالة {uid} من الطاقم.")
    else:
        bot.reply_to(message, "هذا المستخدم ليس ضمن الطاقم.")

# ========= Callback Handlers (Buttons) =========
@bot.callback_query_handler(func=lambda call: True)
def all_callbacks(call):
    # نطبع لوج للتشخيص
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    data = call.data or ""
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
        amount = int(norm_cmd(message.text))
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

# ========= Catch-all (لا يمنع الأوامر) =========
@bot.message_handler(func=lambda m: True)
def any_text(message):
    # لو رسالة فيها سلاش، خليه للراوتر
    if message.text and message.text.strip().startswith(("/", "／")):
        return
    # مررها للأدمن كتنبيه
    try:
        bot.send_message(ADMIN_ID, f"📩 رسالة من {message.from_user.id}:\n{message.text}")
    except Exception as e:
        print("forward error:", e)

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
