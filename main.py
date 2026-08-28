import os
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# جلب كافة مفاتيح Gemini المعرفة في Render وتصفيتها من التكرار
GEMINI_API_KEYS = []
for key, val in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and val:
        GEMINI_API_KEYS.extend([k.strip() for k in val.split(",") if k.strip()])
GEMINI_API_KEYS = list(set(GEMINI_API_KEYS))

ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"

RENDER_APP_URL = "https://ai-for-zynmart.onrender.com"
DEFAULT_GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")

# قاعدة البيانات المحلية للأعضاء
known_users = {}

# --- نظام حفظ وقراءة الأعضاء من ملف محلي لمنع ضياع البيانات عند إعادة تشغيل Render ---
def save_users_to_file():
    try:
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(known_users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

def load_users_from_file():
    global known_users
    try:
        if os.path.exists("users.json"):
            with open("users.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                known_users = {int(k): v for k, v in loaded.items()}
    except Exception as e:
        print(f"Error loading users: {e}")

load_users_from_file()

GROUP_RULE_TEXT = """📜 *سياسة الانضباط وقوانين مجتمع Zynmart الرسمية:*

حرصاً على حماية المنصة وتوفير بيئة جادة ومحترمة، نرجو من الجميع الالتزام الصارم بالقواعد التالية:

1️⃣ *الجدية والاحترام:*
المجموعة مخصصة للاستفسارات وتبادل المعرفة فقط. يُمنع السب، الإساءة، أو إثارة الفتنة.

2️⃣ *الأمان والهوية والروابط الرسمية:*
• يمنع نشر الروابط الخارجية غير الرسمية أو الإعلانات التجارية.
• *رابط المتجر الرسمي:* [zynmart.pages.dev](https://zynmart.pages.dev)
• *رابط بوت التعدين الرسمي:* `@zynpibot`
• يجب تعيين اسم مستخدم (@username) لحسابك.

3️⃣ *حماية النظام والعملة:*
أي محاولة لااختراق التطبيق أو التحايل تؤدي للحظر الدائم.

*هدفنا بناء مجتمع واعي، جاد وموثوق! 🚀*"""

ZYNMART_PROMPT = """
أنت المساعد الذكي الرسمي "AI for ZYNMART"، وظيفتك هي إرشاد ومساعدة رواد متجر "ZYNMART" داخل مجموعة التليجرام.

[معلومات المشروع]
- اسم المنصة/المتجر: ZYNMART
- صاحب المشروع: صالح التونسي.
- مطور التطبيق: أيوب.
- العملة الرسمية للمتجر: ZYN.
- رابط المتجر: zynmart.pages.dev (في Pi Browser).
- رابط بوت التعدين: https://t.me/zynpibot
- الموقع الرسمي للأخبار: https://zynmartpi.github.io/

[التحديثات الحينية]
{DYNAMIC_NEWS}

[قواعد الرد]
- كن ودوداً واحترافياً.
- إذا كان السؤال خاصاً ببيانات شخصية أو مشكلة تنفيذية معقدة، قل: "سؤالك مهم، دقيقة نخلي الأدمن يجاوبك".
"""

GREETING_RESPONSE = """وعليكم السلام ورحمة الله وبركاته! 🌸
مرحباً بك في عائلة ZYNMART 🚀

أنا المساعد الذكي الخاص بالمشروع، وفي خدمتك دائماً:
🛒 **رابط المتجر (في Pi Browser):** zynmart.pages.dev
⛏️ **بوت التعدين والمهام اليومية:** https://t.me/zynpibot
🌐 **موقع التحديثات والأخبار الرسمية:** https://zynmartpi.github.io/

إذا كان لديك أي سؤال تفصيلي، يمكنك الإشارة لي بالمنشن: @zynmart_ai_bot وسأجيبك فوراً!"""

DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! 🚀\nمتجرنا: zynmart.pages.dev\nبوت التعدين: https://t.me/zynpibot"

def get_latest_news():
    try:
        response = requests.get(NEWS_URL, timeout=5)
        if response.status_code == 200:
            return response.text[:1500]
    except Exception as e:
        print(f"Error fetching news site: {e}")
    return "تابعوا التحديثات عبر الموقع: https://zynmartpi.github.io/"

def send_telegram_message(chat_id, text, reply_to_message_id=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def ban_telegram_member(chat_id, user_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Ban Error: {e}")

def get_gemini_response(user_message, is_admin_private=False, user_name=""):
    if not GEMINI_API_KEYS:
        return DEFAULT_FALLBACK_TEXT

    latest_news = get_latest_news()
    active_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", latest_news)

    model_name = "gemini-3.6-flash"
    headers = {"Content-Type": "application/json"}
    
    context_prefix = f"اسم العضو السائل: {user_name}\n" if user_name else ""
    prompt_text = f"{active_prompt}\n\n{context_prefix}المستخدم: {user_message}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    for api_key in GEMINI_API_KEYS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                res_data = response.json()
                candidates = res_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", DEFAULT_FALLBACK_TEXT)
        except Exception:
            continue

    return DEFAULT_FALLBACK_TEXT

# ==================== المهام المجدولة ====================

def task_check_usernames_daily():
    """فحص الأعضاء ونشر القائمة فوراً عند التحديث ثم كل 5 ساعات بدون parse_mode"""
    no_username_list = []
    target_chat_id = None
    
    for uid, uinfo in list(known_users.items()):
        if not target_chat_id and uinfo.get("chat_id"):
            target_chat_id = uinfo.get("chat_id")
            
        if not uinfo.get("username"):
            no_username_list.append(f"- {uinfo.get('name', 'عضو')}")

    if not target_chat_id:
        target_chat_id = DEFAULT_GROUP_CHAT_ID

    if no_username_list and target_chat_id:
        users_str = "\n".join(no_username_list)
        warning_msg = (
            "⚠️ تنبيه هام ومكرر (فحص الدوري كل 5 ساعات)\n\n"
            "قائمة الأعضاء الذين لا يملكون اسم مستخدم (Username):\n"
            f"{users_str}\n\n"
            "🔴 يرجى إنشاء اسم مستخدم لحسابكم في التيليجرام فوراً!"
        )
        send_telegram_message(target_chat_id, warning_msg, parse_mode=None)

def task_keep_alive():
    try:
        requests.get(RENDER_APP_URL, timeout=10)
    except Exception as e:
        print(f"Keep-Alive Error: {e}")

def task_send_group_rules():
    target_chat_id = DEFAULT_GROUP_CHAT_ID
    if known_users:
        target_chat_id = list(known_users.values())[0].get("chat_id") or DEFAULT_GROUP_CHAT_ID
    if target_chat_id:
        send_telegram_message(target_chat_id, GROUP_RULE_TEXT)

# إعداد المجدول المكتبي لتشغيل المهام
scheduler = BackgroundScheduler(daemon=True)

# التحديث الجديد: تعمل المهمة فور رفع الكود وتتكرر كل 5 ساعات تلقائياً
scheduler.add_job(task_check_usernames_daily, 'interval', hours=5, next_run_time=datetime.now())
scheduler.add_job(task_keep_alive, 'interval', minutes=10)
scheduler.add_job(task_send_group_rules, 'interval', hours=2)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ===============================================================

@app.route("/", methods=["GET"])
def home():
    return "AI FOR ZYNMART Bot is Live!"

# مسار لإجبار البوت على نشر القائمة يدوياً من المتصفح في أي وقت
@app.route("/check-users", methods=["GET"])
def trigger_users_check():
    task_check_usernames_daily()
    return f"Users check executed! Registered users count: {len(known_users)}", 200

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook Endpoint is Active!", 200

    data = request.get_json()
    if data and "message" in data:
        msg_obj = data["message"]
        chat_id = msg_obj["chat"]["id"]
        chat_type = msg_obj["chat"]["type"]
        from_user = msg_obj["from"]
        user_id = from_user["id"]
        first_name = from_user.get("first_name", "صديقنا")
        username = from_user.get("username")
        user_message = msg_obj.get("text", "")
        message_id = msg_obj.get("message_id")

        if chat_type in ["group", "supergroup"]:
            known_users[user_id] = {
                "name": first_name,
                "username": username,
                "chat_id": chat_id
            }
            save_users_to_file()

        if "left_chat_member" in msg_obj:
            left_member = msg_obj["left_chat_member"]
            left_name = left_member.get("first_name", "العضو")
            left_id = left_member.get("id")

            farewell_msg = f"وداعاً {left_name} 👋\nقد تم حظرك رسمياً من العودة للمجموعة."
            send_telegram_message(chat_id, farewell_msg, parse_mode=None)
            ban_telegram_member(chat_id, left_id)
            
            if left_id in known_users:
                del known_users[left_id]
                save_users_to_file()
            return jsonify({"status": "ok"}), 200

        if user_message:
            if chat_type == "private":
                if user_id != ADMIN_ID:
                    send_telegram_message(chat_id, "عذراً، هذا الخاص مخصص لإدارة ZYNMART فقط.")
                else:
                    reply = get_gemini_response(user_message, is_admin_private=True, user_name=first_name)
                    send_telegram_message(chat_id, reply)
                return jsonify({"status": "ok"}), 200

            clean_msg = user_message.strip().lower()

            # التنبيه اللحظي للعضو الذي يفتقد اسم مستخدم
            if not username and chat_type in ["group", "supergroup"]:
                no_user_warn = f"أهلاً بك {first_name} ⚠️\nلاحظنا أن حسابك لا يملك اسم مستخدم (Username). يرجى إنشاؤه لتجنب أي مشاكل."
                send_telegram_message(chat_id, no_user_warn, parse_mode=None)

            greetings = ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير"]
            if any(g in clean_msg for g in greetings):
                greeting_text = f"أهلاً بك يا {first_name} 👋\n" + GREETING_RESPONSE
                send_telegram_message(chat_id, greeting_text)
                return jsonify({"status": "ok"}), 200

            clean_bot_name = BOT_USERNAME.replace("@", "").lower()
            is_mentioned = BOT_USERNAME.lower() in clean_msg
            
            reply_to = msg_obj.get("reply_to_message", {})
            reply_from = reply_to.get("from", {})
            is_reply_to_bot = reply_from.get("username", "").lower() == clean_bot_name

            if is_mentioned or is_reply_to_bot:
                query_text = user_message.replace(BOT_USERNAME, "").replace(f"@{clean_bot_name}", "").strip()
                reply = get_gemini_response(query_text or user_message, is_admin_private=False, user_name=first_name)
                formatted_reply = f"مرحباً بك {first_name} 🌟\n\n{reply}"
                send_telegram_message(chat_id, formatted_reply, reply_to_message_id=message_id)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
