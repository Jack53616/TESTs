# bot.py
import os
import json
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ====== ENV ======
API_TOKEN = os.environ.get("BOT_TOKEN")  # ضيفه في Render
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# ====== Persistence Patch (Files -> Postgres via db_kv if available) ======
USE_DB = bool(os.environ.get("DATABASE_URL"))
if USE_DB:
    # يتطلب وجود db_kv.py بنفس المجلد
    from db_kv import init_db, get_json, set_json
    init_db()

def load_json(filename):
    """
    - لو DATABASE_URL موجود: نخزن كـ Keys في جدول kv_store
    - غير هيك: نقرأ/نكتب ملفات محلية (للاستخدام المحلي فقط)
    """
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt", "")
        default = {} if filename.endswith(".json") else ""
        return get_json(key, default=default)
    else:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                try:
                    if filename.endswith(".json"):
                        return json.load(f)
                    else:
                        return f.read()
                except Exception:
                    return {} if filename.endswith(".json") else ""
        return {} if filename.endswith(".json") else ""

def save_json(filename, data):
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt", "")
        set_json(key, data)
    else:
        mode = "w"
        with open(filename, mode, encoding="utf-8") as f:
            if filename.endswith(".json"):
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(data))

# ====== Webhook setup (optional) ======
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # مثال: https://your-app.onrender.com
if WEBHOOK_BASE:
    try:
        bot.remove_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=f"{WEBHOOK_BASE}/{API_TOKEN}")
    except Exception as e:
        print("Failed to set webhook:", e)

# ====== Roles & Staff Management ======
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
    # staff includes admins automatically
    return is_admin(user_id) or (int(user_id) in _load_staff_set())

# ====== Helpers & UI ======
def ensure_user(chat_id: int) -> str:
    user_id = str(chat_id)
    users = load_json("users.json") or {}
    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json("users.json", users)
    return user_id

def show_main_menu(chat_id: int):
    users = load_json("users.json") or {}
    user_id = str(chat_id)
    balance = users.get(user_id, {}).get("balance", 0)

    text = (
        "👋 أهلاً بك في بوت التداول\n\n"
        f"💰 رصيدك: {balance}$\n"
        f"🆔 آيديك: {user_id}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📈 صفقة اليوم", callback_data="daily_trade"),
        types.InlineKeyboardButton("💸 سحب", callback_data="withdraw_menu"),
    )
    markup.add(
        types.InlineKeyboardButton("💼 معاملات السحب", callback_data="withdraw_status"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
    )
    bot.send_message(chat_id, text, reply_markup=markup)

# ====== Commands (User) ======
@bot.message_handler(commands=["start"])
def cmd_start(message):
    ensure_user(message.chat.id)
    show_main_menu(message.chat.id)

@bot.message_handler(commands=["help"])
def cmd_help(message):
    uid = message.from_user.id
    base = [
        "🛠 الأوامر المتاحة:",
        "/start - القائمة الرئيسية",
        "/id - يظهر آيديك",
        "/balance - يظهر رصيدك",
        "/daily - صفقة اليوم",
        "/withdraw <amount> - طلب سحب",
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
    if is_staff(uid):
        lines += [""] + staff_cmds
    if is_admin(uid):
        lines += [""] + admin_cmds
    bot.reply_to(message, "\n".join(lines))

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
    bot.reply_to(message, f"📈 صفقة اليوم:\n{daily}")

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
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

    # خصم الرصيد
    users[uid]["balance"] = bal - amount
    save_json("users.json", users)

    # سجل طلب السحب
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

# ====== Commands (Staff/Admin) ======
@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message):
    # للطاقم (يشمل المدير)
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        bot.reply_to(message, "الاستخدام: /addbalance <user_id> <amount>")
        return
    uid_str, amount_str = parts[1], parts[2]
    if not amount_str.lstrip("-").isdigit():
        bot.reply_to(message, "المبلغ غير صالح.")
        return
    amount = int(amount_str)

    users = load_json("users.json") or {}
    users.setdefault(uid_str, {"balance": 0})
    users[uid_str]["balance"] = users[uid_str].get("balance", 0) + amount
    save_json("users.json", users)
    bot.reply_to(
        message,
        f"تم إضافة {amount}$ للمستخدم {uid_str}. الرصيد الجديد: {users[uid_str]['balance']}$"
    )

@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(message):
    # للطاقم (يشمل المدير)
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "اكتب نص الصفقة: /setdaily <النص>")
        return
    save_json("daily_trade.txt", parts[1])
    bot.reply_to(message, "تم تحديث صفقة اليوم ✅")

@bot.message_handler(commands=["setbalance"])
def cmd_setbalance(message):
    # للمدير فقط
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        bot.reply_to(message, "الاستخدام: /setbalance <user_id> <amount>")
        return
    uid_str, amount_str = parts[1], parts[2]
    if not amount_str.lstrip("-").isdigit():
        bot.reply_to(message, "المبلغ غير صالح.")
        return
    amount = int(amount_str)

    users = load_json("users.json") or {}
    users.setdefault(uid_str, {"balance": 0})
    users[uid_str]["balance"] = amount
    save_json("users.json", users)
    bot.reply_to(message, f"تم ضبط رصيد المستخدم {uid_str} إلى {amount}$.")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    # للمدير فقط
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
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
    # للمدير فقط
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "الاستخدام: /promote <user_id>")
        return
    uid = int(parts[1].strip())
    s = _load_staff_set()
    s.add(uid)
    _save_staff_set(s)
    bot.reply_to(message, f"✅ تمت ترقية {uid} إلى طاقم (staff).")

@bot.message_handler(commands=["demote"])
def cmd_demote(message):
    # للمدير فقط
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "الاستخدام: /demote <user_id>")
        return
    uid = int(parts[1].strip())
    s = _load_staff_set()
    if uid in s:
        s.remove(uid)
        _save_staff_set(s)
        bot.reply_to(message, f"✅ تمت إزالة {uid} من الطاقم.")
    else:
        bot.reply_to(message, "هذا المستخدم ليس ضمن الطاقم.")

# ====== Flask Webhook ======
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

# ====== Run ======
if __name__ == "__main__":
    # على Render، راح يمر عبر gunicorn عادة، لكن نخلي run محلياً للتجربة
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
