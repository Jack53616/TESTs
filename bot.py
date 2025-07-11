import telebot
import json
import os
from datetime import datetime
from flask import Flask, request
from telebot import types

API_TOKEN = os.environ.get("BOT_TOKEN")  # لازم تضيف المتغير في Render
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))

bot = telebot.TeleBot(API_TOKEN)

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

users = load_json("users.json")
withdraw_requests = load_json("withdraw_requests.json")
trades = load_json("trades.json")

def show_main_menu(chat_id):
    user_id = str(chat_id)
    balance = users.get(user_id, {}).get("balance", 0)
    text = (
        "👋 أهلاً بك في بوت التداول\n\n"
        f"💰 رصيدك: {balance}$\n"
        f"🆔 ايديك: {user_id}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📈 صفقاتك اليومية", callback_data="daily_trade"),
        types.InlineKeyboardButton("💸 سحب", callback_data="withdraw_menu"),
    )
    markup.add(
        types.InlineKeyboardButton("💼 معاملات السحب", callback_data="withdraw_status"),
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")
    )
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.chat.id)
    if user_id not in users:
        users[user_id] = {"balance": 0}
        save_json("users.json", users)
    show_main_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == "daily_trade")
def show_daily_trade(call):
    if os.path.exists("daily_trade.txt"):
        with open("daily_trade.txt", "r", encoding='utf-8') as f:
            trade_info = f.read()
    else:
        trade_info = "🚫 لا توجد صفقات."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
    bot.send_message(call.message.chat.id, trade_info, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "withdraw_menu")
def withdraw_menu(call):
    markup = types.InlineKeyboardMarkup()
    for amount in [10, 20, 30, 50, 100]:
        markup.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))
    markup.add(types.InlineKeyboardButton("💰 مبلغ اختياري", callback_data="withdraw_custom"))
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
    bot.send_message(call.message.chat.id, "🔢 اختر المبلغ للسحب:", reply_markup=markup)

def add_withdraw_request(user_id, amount):
    req_id = str(len(withdraw_requests) + 1)
    withdraw_requests[req_id] = {
        "user_id": user_id,
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
    bot.send_message(ADMIN_ID, f"🔔 طلب سحب جديد:\nمستخدم: {user_id}\nالمبلغ: {amount}$", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("withdraw_") and call.data not in ["withdraw_status", "withdraw_custom"])
def process_withdraw(call):
    user_id = str(call.from_user.id)
    balance = users.get(user_id, {}).get("balance", 0)

    amount = int(call.data.split("_")[1])
    if balance >= amount:
        users[user_id]["balance"] -= amount
        save_json("users.json", users)
        add_withdraw_request(user_id, amount)
        bot.send_message(call.message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")
    else:
        bot.send_message(call.message.chat.id, "❌ لا يوجد رصيد كافٍ.")

@bot.callback_query_handler(func=lambda call: call.data == "withdraw_custom")
def withdraw_custom(call):
    bot.send_message(call.message.chat.id, "💬 اكتب المبلغ الذي تريد سحبه:")
    bot.register_next_step_handler(call.message, process_custom_withdraw)

def process_custom_withdraw(message):
    user_id = str(message.chat.id)
    balance = users.get(user_id, {}).get("balance", 0)

    try:
        amount = int(message.text)
        if amount < 10:
            bot.send_message(message.chat.id, "❌ الحد الأدنى 10$.")
        elif balance >= amount:
            users[user_id]["balance"] -= amount
            save_json("users.json", users)
            add_withdraw_request(user_id, amount)
            bot.send_message(message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")
        else:
            bot.send_message(message.chat.id, "❌ لا يوجد رصيد كافٍ.")
    except:
        bot.send_message(message.chat.id, "❌ أدخل رقم صحيح.")

@bot.callback_query_handler(func=lambda call: call.data == "withdraw_status")
def withdraw_status(call):
    user_id = str(call.from_user.id)
    markup = types.InlineKeyboardMarkup()
    found = False
    for req_id, req in withdraw_requests.items():
        if req["user_id"] == user_id and req["status"] == "بانتظار الموافقة":
            markup.add(types.InlineKeyboardButton(f"❌ إلغاء طلب {req['amount']}$", callback_data=f"cancel_{req_id}"))
            found = True
    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))
    if found:
        bot.send_message(call.message.chat.id, "💼 طلباتك بانتظار الموافقة:", reply_markup=markup)
    else:
        bot.send_message(call.message.chat.id, "🚫 لا توجد طلبات حالياً.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_"))
def cancel_request(call):
    req_id = call.data.split("_")[1]
    req = withdraw_requests.get(req_id)
    if req and req["status"] == "بانتظار الموافقة":
        user_id = req["user_id"]
        amount = req["amount"]
        users[user_id]["balance"] += amount
        req["status"] = "ملغي"
        save_json("withdraw_requests.json", withdraw_requests)
        save_json("users.json", users)
        bot.send_message(call.message.chat.id, f"❌ تم إلغاء الطلب واستعادة {amount}$.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ لا يمكن إلغاء الطلب.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_"))
def approve_request(call):
    req_id = call.data.split("_")[1]
    req = withdraw_requests.get(req_id)
    if req and req["status"] == "بانتظار الموافقة":
        req["status"] = "مكتمل"
        save_json("withdraw_requests.json", withdraw_requests)
        bot.send_message(int(req["user_id"]), f"✅ تم تنفيذ طلب السحب {req['amount']}$ بنجاح.")
        bot.send_message(call.message.chat.id, "👌 تم التنفيذ.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_"))
def reject_request(call):
    req_id = call.data.split("_")[1]
    req = withdraw_requests.get(req_id)
    if req and req["status"] == "بانتظار الموافقة":
        req["status"] = "مرفوض"
        users[req["user_id"]]["balance"] += req["amount"]
        save_json("withdraw_requests.json", withdraw_requests)
        save_json("users.json", users)
        bot.send_message(int(req["user_id"]), f"❌ تم رفض طلب السحب واستعادة الرصيد.")
        bot.send_message(call.message.chat.id, "🚫 تم الرفض وإرجاع الرصيد.")
    else:
        bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")

@bot.callback_query_handler(func=lambda call: call.data == "stats")
def stats(call):
    user_id = str(call.from_user.id)
    user_trades = trades.get(user_id, [])
    if not user_trades:
        bot.send_message(call.message.chat.id, "📊 لا توجد صفقات مسجلة.")
        return
    total_profit = 0
    text = "📊 إحصائياتك:\n\n"
    for i, t in enumerate(user_trades, 1):
        text += f"{i}- {t['date']} | ربح: {t['profit']}$\n"
        total_profit += t['profit']
    text += f"\n✅ إجمالي الربح: {total_profit}$"
    bot.send_message(call.message.chat.id, text)

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text.replace('/broadcast', '').strip()
    if not text:
        return bot.send_message(message.chat.id, "❌ اكتب الرسالة بعد الأمر.\nمثال:\n/broadcast مرحبا جميعاً!")

    count = 0
    for uid in users:
        try:
            bot.send_message(int(uid), f"📢 {text}")
            count += 1
        except:
            continue

    bot.send_message(message.chat.id, f"✅ تم الإرسال إلى {count} مستخدم.")

@bot.message_handler(commands=['set'])
def set_balance(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ لا تملك صلاحية.")
    try:
        parts = message.text.split()
        target_id = str(parts[1])
        amount = int(parts[2])
        users[target_id] = {"balance": amount}
        save_json("users.json", users)
        bot.send_message(int(target_id), f"📢 تم تعديل رصيدك إلى {amount}$.")
        bot.send_message(message.chat.id, "✅ تم التحديث بنجاح.")
    except:
        bot.send_message(message.chat.id, "❌ الصيغة خاطئة.\nاكتب هكذا:\n`/set USER_ID AMOUNT`")

@bot.message_handler(commands=['fine'])
def fine_balance(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ما معك صلاحية.")
    try:
        parts = message.text.split()
        target_id = str(parts[1])
        amount = int(parts[2])
        if target_id in users:
            users[target_id]["balance"] = max(0, users[target_id].get("balance", 0) - amount)
            save_json("users.json", users)
            bot.send_message(int(target_id), f"📢 تم خصم {amount}$ من رصيدك.")
            bot.send_message(message.chat.id, "✅ تم الخصم بنجاح.")
        else:
            bot.send_message(message.chat.id, "❌ المستخدم غير موجود.")
    except:
        bot.send_message(message.chat.id, "❌ الصيغة خاطئة.\nاكتب هكذا:\n/fine USER_ID AMOUNT")

@bot.message_handler(commands=['setdaily'])
def set_daily_trade(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ما معك صلاحية.")
    text = message.text.replace('/setdaily', '').strip()
    if text:
        with open("daily_trade.txt", "w", encoding='utf-8') as f:
            f.write(text)
        bot.send_message(message.chat.id, "✅ تم تحديث الصفقات اليومية.")
    else:
        bot.send_message(message.chat.id, "❌ اكتب هيك: /setdaily النص")

@bot.message_handler(commands=['cleardaily'])
def clear_daily_trade(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ما معك صلاحية.")
    if os.path.exists("daily_trade.txt"):
        os.remove("daily_trade.txt")
        bot.send_message(message.chat.id, "🗑️ تم مسح الصفقات اليومية.")
    else:
        bot.send_message(message.chat.id, "🚫 ما في صفقات يومية محفوظة.")


@bot.message_handler(commands=['deltrade'])
def del_trade(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ما معك صلاحية.")
    try:
        parts = message.text.split()
        user_id = str(parts[1])
        index = int(parts[2]) - 1
        if user_id in trades and 0 <= index < len(trades[user_id]):
            deleted_trade = trades[user_id].pop(index)
            save_json("trades.json", trades)
            bot.send_message(message.chat.id, f"✅ تم حذف الصفقة: {deleted_trade}")
        else:
            bot.send_message(message.chat.id, "❌ الصفقة غير موجودة.")
    except:
        bot.send_message(message.chat.id, "❌ مثال صحيح: /deltrade USER_ID INDEX")


@bot.message_handler(commands=['cleartrades'])
def clear_trades(message):
    if message.from_user.id != ADMIN_ID:
        return bot.reply_to(message, "❌ ما معك صلاحية.")
    try:
        parts = message.text.split()
        user_id = str(parts[1])
        if user_id in trades:
            trades.pop(user_id)
            save_json("trades.json", trades)
            bot.send_message(message.chat.id, f"✅ تم حذف كل الصفقات للمستخدم {user_id}.")
        else:
            bot.send_message(message.chat.id, "❌ لا توجد صفقات.")
    except:
        bot.send_message(message.chat.id, "❌ مثال صحيح: /cleartrades USER_ID")



@bot.message_handler(commands=['addtrade'])
def add_trade(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        user_id = str(parts[1])
        profit = int(parts[2])
        trade = {"date": datetime.now().strftime("%Y-%m-%d"), "profit": profit}
        if user_id not in trades:
            trades[user_id] = []
        trades[user_id].append(trade)
        save_json("trades.json", trades)
        bot.send_message(message.chat.id, "✅ تمت إضافة الصفقة.")
    except:
        bot.send_message(message.chat.id, "❌ مثال صحيح: /addtrade 123456789 20")

@bot.message_handler(func=lambda message: True)
def any_message(message):
    if message.text.startswith("/"):
        return
    bot.send_message(ADMIN_ID, f"📩 رسالة جديدة من {message.from_user.id}:\n{message.text}")

@bot.callback_query_handler(func=lambda call: call.data == "go_back")
def go_back(call):
    show_main_menu(call.message.chat.id)

# ==== Webhook Server via Flask ====

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "✅ البوت شغال"

@app.route(f"/{API_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
