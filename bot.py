import telebot\nimport json\nimport os\nfrom datetime import datetime\nfrom flask import Flask, request\nfrom telebot import types\n\nAPI_TOKEN = os.environ.get("BOT_TOKEN")  # لازم تضيف المتغير في Render\nADMIN_ID = int(os.environ.get("ADMIN_ID", "1262317603"))\n\nbot = telebot.TeleBot(API_TOKEN)


# ===== Commands Pack (added) =====
def ensure_user(chat_id):
    user_id = str(chat_id)
    global users
    users = load_json("users.json")
    if user_id not in users:
        users[user_id] = {"balance": 0, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_json("users.json", users)
    return user_id

@bot.message_handler(commands=["start"])
def cmd_start(message):
    ensure_user(message.chat.id)
    show_main_menu(message.chat.id)

@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "🛠 الأوامر المتاحة:\n"
        "/start - القائمة الرئيسية\n"
        "/id - يظهر آيديك\n"
        "/balance - يظهر رصيدك\n"
        "/daily - يعرض صفقة اليوم\n"
        "/withdraw <amount> - طلب سحب\n"
        "— أوامر المشرف —\n"
        "/addbalance <user_id> <amount> - زيادة رصيد\n"
        "/setbalance <user_id> <amount> - ضبط رصيد\n"
        "/setdaily <نص الصفقة> - ضبط صفقة اليوم\n"
        "/broadcast <نص> - إرسال للكل\n"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["id"])
def cmd_id(message):
    bot.reply_to(message, f"🆔 آيديك: {message.from_user.id}")

@bot.message_handler(commands=["balance"])
def cmd_balance(message):
    uid = ensure_user(message.chat.id)
    bal = load_json("users.json").get(uid,{}).get("balance",0)
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
    users = load_json("users.json")
    bal = users.get(uid,{}).get("balance",0)
    if bal < amount:
        bot.reply_to(message, f"رصيدك غير كافٍ. رصيدك: {bal}$")
        return
    # اخصم و سجّل طلب سحب
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

def is_admin(user_id:int)->bool:
    try:
        return int(user_id) == ADMIN_ID
    except:
        return False

@bot.message_handler(commands=["addbalance"])
def cmd_addbalance(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "الاستخدام: /addbalance <user_id> <amount>")
        return
    uid, amount = parts[1], int(parts[2])
    users = load_json("users.json")
    users.setdefault(uid, {"balance":0})
    users[uid]["balance"] = users[uid].get("balance",0) + amount
    save_json("users.json", users)
    bot.reply_to(message, f"تم إضافة {amount}$ للمستخدم {uid}. الرصيد الجديد: {users[uid]['balance']}$")

@bot.message_handler(commands=["setbalance"])
def cmd_setbalance(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "الاستخدام: /setbalance <user_id> <amount>")
        return
    uid, amount = parts[1], int(parts[2])
    users = load_json("users.json")
    users.setdefault(uid, {"balance":0})
    users[uid]["balance"] = amount
    save_json("users.json", users)
    bot.reply_to(message, f"تم ضبط رصيد المستخدم {uid} إلى {amount}$.")

@bot.message_handler(commands=["setdaily"])
def cmd_setdaily(message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "اكتب نص الصفقة: /setdaily <النص>")
        return
    save_json("daily_trade.txt", parts[1])
    bot.reply_to(message, "تم تحديث صفقة اليوم ✅")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
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

# ===== End Commands Pack =====

# --- Webhook setup (optional) ---
WEBHOOK_BASE = os.environ.get("WEBHOOK_URL")  # e.g., https://your-app.onrender.com
if WEBHOOK_BASE:
    try:
        bot.remove_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=f"{WEBHOOK_BASE}/{API_TOKEN}")
    except Exception as e:
        print("Failed to set webhook:", e)
# --- End webhook setup ---\n\n# === Persistence Patch Start ===
USE_DB = bool(os.environ.get("DATABASE_URL"))
if USE_DB:
    from db_kv import init_db, get_json, set_json
    init_db()

def load_json(filename):
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt","")
        data = get_json(key, default={} if filename.endswith(".json") else "")
        return data
    else:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                import json as _json
                try:
                    return _json.load(f) if filename.endswith(".json") else f.read()
                except Exception:
                    return {} if filename.endswith(".json") else ""
        return {} if filename.endswith(".json") else ""

def save_json(filename, data):
    if USE_DB:
        key = filename.replace(".json", "").replace(".txt","")
        set_json(key, data)
    else:
        mode = "w"
        with open(filename, mode, encoding="utf-8") as f:
            if filename.endswith(".json"):
                import json as _json
                _json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(data))
# === Persistence Patch End ===\n\n\ndef load_json(filename):\n    if os.path.exists(filename):\n        with open(filename, "r") as f:\n            return json.load(f)\n    return {}\n\ndef save_json(filename, data):\n    with open(filename, "w") as f:\n        json.dump(data, f, indent=2)\n\nusers = load_json("users.json")\nwithdraw_requests = load_json("withdraw_requests.json")\ntrades = load_json("trades.json")\n\ndef show_main_menu(chat_id):\n    user_id = str(chat_id)\n    balance = users.get(user_id, {}).get("balance", 0)\n    text = (\n        "👋 أهلاً بك في بوت التداول\n\n"\n        f"💰 رصيدك: {balance}$\n"\n        f"🆔 ايديك: {user_id}"\n    )\n    markup = types.InlineKeyboardMarkup(row_width=2)\n    markup.add(\n        types.InlineKeyboardButton("📈 صفقاتك اليومية", callback_data="daily_trade"),\n        types.InlineKeyboardButton("💸 سحب", callback_data="withdraw_menu"),\n    )\n    markup.add(\n        types.InlineKeyboardButton("💼 معاملات السحب", callback_data="withdraw_status"),\n        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")\n    )\n    bot.send_message(chat_id, text, reply_markup=markup)\n\n@bot.message_handler(commands=['start'])\ndef start(message):\n    user_id = str(message.chat.id)\n    if user_id not in users:\n        users[user_id] = {"balance": 0}\n        save_json("users.json", users)\n    show_main_menu(message.chat.id)\n\n@bot.callback_query_handler(func=lambda call: call.data == "daily_trade")\ndef show_daily_trade(call):\n    if os.path.exists("daily_trade.txt"):\n        with open("daily_trade.txt", "r", encoding='utf-8') as f:\n            trade_info = f.read()\n    else:\n        trade_info = "🚫 لا توجد صفقات."\n    markup = types.InlineKeyboardMarkup()\n    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))\n    bot.send_message(call.message.chat.id, trade_info, reply_markup=markup)\n\n@bot.callback_query_handler(func=lambda call: call.data == "withdraw_menu")\ndef withdraw_menu(call):\n    markup = types.InlineKeyboardMarkup()\n    for amount in [10, 20, 30, 50, 100]:\n        markup.add(types.InlineKeyboardButton(f"{amount}$", callback_data=f"withdraw_{amount}"))\n    markup.add(types.InlineKeyboardButton("💰 مبلغ اختياري", callback_data="withdraw_custom"))\n    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))\n    bot.send_message(call.message.chat.id, "🔢 اختر المبلغ للسحب:", reply_markup=markup)\n\ndef add_withdraw_request(user_id, amount):\n    req_id = str(len(withdraw_requests) + 1)\n    withdraw_requests[req_id] = {\n        "user_id": user_id,\n        "amount": amount,\n        "status": "بانتظار الموافقة",\n        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n    }\n    save_json("withdraw_requests.json", withdraw_requests)\n\n    markup = types.InlineKeyboardMarkup()\n    markup.add(\n        types.InlineKeyboardButton(f"✅ قبول {req_id}", callback_data=f"approve_{req_id}"),\n        types.InlineKeyboardButton(f"❌ رفض {req_id}", callback_data=f"reject_{req_id}")\n    )\n    bot.send_message(ADMIN_ID, f"🔔 طلب سحب جديد:\nمستخدم: {user_id}\nالمبلغ: {amount}$", reply_markup=markup)\n\n@bot.callback_query_handler(func=lambda call: call.data.startswith("withdraw_") and call.data not in ["withdraw_status", "withdraw_custom"])\ndef process_withdraw(call):\n    user_id = str(call.from_user.id)\n    balance = users.get(user_id, {}).get("balance", 0)\n\n    amount = int(call.data.split("_")[1])\n    if balance >= amount:\n        users[user_id]["balance"] -= amount\n        save_json("users.json", users)\n        add_withdraw_request(user_id, amount)\n        bot.send_message(call.message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")\n    else:\n        bot.send_message(call.message.chat.id, "❌ لا يوجد رصيد كافٍ.")\n\n@bot.callback_query_handler(func=lambda call: call.data == "withdraw_custom")\ndef withdraw_custom(call):\n    bot.send_message(call.message.chat.id, "💬 اكتب المبلغ الذي تريد سحبه:")\n    bot.register_next_step_handler(call.message, process_custom_withdraw)\n\ndef process_custom_withdraw(message):\n    user_id = str(message.chat.id)\n    balance = users.get(user_id, {}).get("balance", 0)\n\n    try:\n        amount = int(message.text)\n        if amount < 10:\n            bot.send_message(message.chat.id, "❌ الحد الأدنى 10$.")\n        elif balance >= amount:\n            users[user_id]["balance"] -= amount\n            save_json("users.json", users)\n            add_withdraw_request(user_id, amount)\n            bot.send_message(message.chat.id, f"✅ تم تقديم طلب سحب {amount}$ بانتظار الموافقة.")\n        else:\n            bot.send_message(message.chat.id, "❌ لا يوجد رصيد كافٍ.")\n    except:\n        bot.send_message(message.chat.id, "❌ أدخل رقم صحيح.")\n\n@bot.callback_query_handler(func=lambda call: call.data == "withdraw_status")\ndef withdraw_status(call):\n    user_id = str(call.from_user.id)\n    markup = types.InlineKeyboardMarkup()\n    found = False\n    for req_id, req in withdraw_requests.items():\n        if req["user_id"] == user_id and req["status"] == "بانتظار الموافقة":\n            markup.add(types.InlineKeyboardButton(f"❌ إلغاء طلب {req['amount']}$", callback_data=f"cancel_{req_id}"))\n            found = True\n    markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="go_back"))\n    if found:\n        bot.send_message(call.message.chat.id, "💼 طلباتك بانتظار الموافقة:", reply_markup=markup)\n    else:\n        bot.send_message(call.message.chat.id, "🚫 لا توجد طلبات حالياً.", reply_markup=markup)\n\n@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_"))\ndef cancel_request(call):\n    req_id = call.data.split("_")[1]\n    req = withdraw_requests.get(req_id)\n    if req and req["status"] == "بانتظار الموافقة":\n        user_id = req["user_id"]\n        amount = req["amount"]\n        users[user_id]["balance"] += amount\n        req["status"] = "ملغي"\n        save_json("withdraw_requests.json", withdraw_requests)\n        save_json("users.json", users)\n        bot.send_message(call.message.chat.id, f"❌ تم إلغاء الطلب واستعادة {amount}$.")\n    else:\n        bot.send_message(call.message.chat.id, "⚠️ لا يمكن إلغاء الطلب.")\n\n@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_"))\ndef approve_request(call):\n    req_id = call.data.split("_")[1]\n    req = withdraw_requests.get(req_id)\n    if req and req["status"] == "بانتظار الموافقة":\n        req["status"] = "مكتمل"\n        save_json("withdraw_requests.json", withdraw_requests)\n        bot.send_message(int(req["user_id"]), f"✅ تم تنفيذ طلب السحب {req['amount']}$ بنجاح.")\n        bot.send_message(call.message.chat.id, "👌 تم التنفيذ.")\n    else:\n        bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")\n\n@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_"))\ndef reject_request(call):\n    req_id = call.data.split("_")[1]\n    req = withdraw_requests.get(req_id)\n    if req and req["status"] == "بانتظار الموافقة":\n        req["status"] = "مرفوض"\n        users[req["user_id"]]["balance"] += req["amount"]\n        save_json("withdraw_requests.json", withdraw_requests)\n        save_json("users.json", users)\n        bot.send_message(int(req["user_id"]), f"❌ تم رفض طلب السحب واستعادة الرصيد.")\n        bot.send_message(call.message.chat.id, "🚫 تم الرفض وإرجاع الرصيد.")\n    else:\n        bot.send_message(call.message.chat.id, "⚠️ الطلب غير صالح.")\n\n@bot.callback_query_handler(func=lambda call: call.data == "stats")\ndef stats(call):\n    user_id = str(call.from_user.id)\n    user_trades = trades.get(user_id, [])\n    if not user_trades:\n        bot.send_message(call.message.chat.id, "📊 لا توجد صفقات مسجلة.")\n        return\n    total_profit = 0\n    text = "📊 إحصائياتك:\n\n"\n    for i, t in enumerate(user_trades, 1):\n        text += f"{i}- {t['date']} | ربح: {t['profit']}$\n"\n        total_profit += t['profit']\n    text += f"\n✅ إجمالي الربح: {total_profit}$"\n    bot.send_message(call.message.chat.id, text)\n\n@bot.message_handler(commands=['broadcast'])\ndef broadcast(message):\n    if message.from_user.id != ADMIN_ID:\n        return\n\n    text = message.text.replace('/broadcast', '').strip()\n    if not text:\n        return bot.send_message(message.chat.id, "❌ اكتب الرسالة بعد الأمر.\nمثال:\n/broadcast مرحبا جميعاً!")\n\n    count = 0\n    for uid in users:\n        try:\n            bot.send_message(int(uid), f"📢 {text}")\n            count += 1\n        except:\n            continue\n\n    bot.send_message(message.chat.id, f"✅ تم الإرسال إلى {count} مستخدم.")\n\n@bot.message_handler(commands=['set'])\ndef set_balance(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ لا تملك صلاحية.")\n    try:\n        parts = message.text.split()\n        target_id = str(parts[1])\n        amount = int(parts[2])\n        users[target_id] = {"balance": amount}\n        save_json("users.json", users)\n        bot.send_message(int(target_id), f"📢 تم تعديل رصيدك إلى {amount}$.")\n        bot.send_message(message.chat.id, "✅ تم التحديث بنجاح.")\n    except:\n        bot.send_message(message.chat.id, "❌ الصيغة خاطئة.\nاكتب هكذا:\n`/set USER_ID AMOUNT`")\n\n@bot.message_handler(commands=['fine'])\ndef fine_balance(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ ما معك صلاحية.")\n    try:\n        parts = message.text.split()\n        target_id = str(parts[1])\n        amount = int(parts[2])\n        if target_id in users:\n            users[target_id]["balance"] = max(0, users[target_id].get("balance", 0) - amount)\n            save_json("users.json", users)\n            bot.send_message(int(target_id), f"📢 تم خصم {amount}$ من رصيدك.")\n            bot.send_message(message.chat.id, "✅ تم الخصم بنجاح.")\n        else:\n            bot.send_message(message.chat.id, "❌ المستخدم غير موجود.")\n    except:\n        bot.send_message(message.chat.id, "❌ الصيغة خاطئة.\nاكتب هكذا:\n/fine USER_ID AMOUNT")\n\n@bot.message_handler(commands=['setdaily'])\ndef set_daily_trade(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ ما معك صلاحية.")\n    text = message.text.replace('/setdaily', '').strip()\n    if text:\n        with open("daily_trade.txt", "w", encoding='utf-8') as f:\n            f.write(text)\n        bot.send_message(message.chat.id, "✅ تم تحديث الصفقات اليومية.")\n    else:\n        bot.send_message(message.chat.id, "❌ اكتب هيك: /setdaily النص")\n\n@bot.message_handler(commands=['cleardaily'])\ndef clear_daily_trade(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ ما معك صلاحية.")\n    if os.path.exists("daily_trade.txt"):\n        os.remove("daily_trade.txt")\n        bot.send_message(message.chat.id, "🗑️ تم مسح الصفقات اليومية.")\n    else:\n        bot.send_message(message.chat.id, "🚫 ما في صفقات يومية محفوظة.")\n\n\n@bot.message_handler(commands=['deltrade'])\ndef del_trade(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ ما معك صلاحية.")\n    try:\n        parts = message.text.split()\n        user_id = str(parts[1])\n        index = int(parts[2]) - 1\n        if user_id in trades and 0 <= index < len(trades[user_id]):\n            deleted_trade = trades[user_id].pop(index)\n            save_json("trades.json", trades)\n            bot.send_message(message.chat.id, f"✅ تم حذف الصفقة: {deleted_trade}")\n        else:\n            bot.send_message(message.chat.id, "❌ الصفقة غير موجودة.")\n    except:\n        bot.send_message(message.chat.id, "❌ مثال صحيح: /deltrade USER_ID INDEX")\n\n\n@bot.message_handler(commands=['cleartrades'])\ndef clear_trades(message):\n    if message.from_user.id != ADMIN_ID:\n        return bot.reply_to(message, "❌ ما معك صلاحية.")\n    try:\n        parts = message.text.split()\n        user_id = str(parts[1])\n        if user_id in trades:\n            trades.pop(user_id)\n            save_json("trades.json", trades)\n            bot.send_message(message.chat.id, f"✅ تم حذف كل الصفقات للمستخدم {user_id}.")\n        else:\n            bot.send_message(message.chat.id, "❌ لا توجد صفقات.")\n    except:\n        bot.send_message(message.chat.id, "❌ مثال صحيح: /cleartrades USER_ID")\n\n\n\n@bot.message_handler(commands=['addtrade'])\ndef add_trade(message):\n    if message.from_user.id != ADMIN_ID:\n        return\n    try:\n        parts = message.text.split()\n        user_id = str(parts[1])\n        profit = int(parts[2])\n        trade = {"date": datetime.now().strftime("%Y-%m-%d"), "profit": profit}\n        if user_id not in trades:\n            trades[user_id] = []\n        trades[user_id].append(trade)\n        save_json("trades.json", trades)\n        bot.send_message(message.chat.id, "✅ تمت إضافة الصفقة.")\n    except:\n        bot.send_message(message.chat.id, "❌ مثال صحيح: /addtrade 123456789 20")\n\n@bot.message_handler(func=lambda message: True)\ndef any_message(message):\n    if message.text.startswith("/"):\n        return\n    bot.send_message(ADMIN_ID, f"📩 رسالة جديدة من {message.from_user.id}:\n{message.text}")\n\n@bot.callback_query_handler(func=lambda call: call.data == "go_back")\ndef go_back(call):\n    show_main_menu(call.message.chat.id)\n\n# ==== Webhook Server via Flask ====\n\napp = Flask(__name__)\n\n@app.route("/", methods=["GET"])\ndef index():\n    return "✅ البوت شغال"\n\n@app.route(f"/{API_TOKEN}", methods=["POST"])\ndef webhook():\n    json_str = request.get_data().decode("utf-8")\n    update = telebot.types.Update.de_json(json_str)\n    bot.process_new_updates([update])\n    return "ok", 200\n\nif __name__ == "__main__":\n    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))\n