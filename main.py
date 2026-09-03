import os
import json
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY")

GEMINI_API_KEYS = []
for key, val in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and val:
        GEMINI_API_KEYS.extend([k.strip() for k in val.split(",") if k.strip()])

ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"

RENDER_APP_URL = "https://ai-for-zynmart.onrender.com"
DEFAULT_GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")

known_users = {}
active_group_chat_id = DEFAULT_GROUP_CHAT_ID

# ==================== دوال التعامل مع users.json ====================

def save_users_to_file():
    try:
        data_to_save = {
            "active_group_chat_id": active_group_chat_id,
            "users": known_users
        }
        with open("users.json", "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

def load_users_from_file():
    global known_users, active_group_chat_id
    try:
        if os.path.exists("users.json"):
            with open("users.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    if "users" in loaded:
                        known_users = loaded.get("users", {})
                        if loaded.get("active_group_chat_id"):
                            active_group_chat_id = loaded.get("active_group_chat_id")
                    else:
                        known_users = {str(k): v for k, v in loaded.items()}
    except Exception as e:
        print(f"Error loading users: {e}")

load_users_from_file()

# ==================== القواعد والبرومبت ====================

GROUP_RULE_TEXT = """📜 *سياسة الانضباط وقوانين مجتمع Zynmart الرسمية:*

حرصاً على حماية المنصة وتوفير بيئة جادة ومحترمة، نرجو من الجميع الالتزام الصارم بالقواعد التالية:

1️⃣ *الجدية والاحترام:*
المجموعة مخصصة للاستفسارات وتبادل المعرفة فقط. يُمنع السب، الإساءة، أو إثارة الفتنة.

2️⃣ *الأمان والهوية والروابط الرسمية:*
• يمنع نشر الروابط الخارجية غير الرسمية أو الإعلانات التجارية.
• *رابط المتجر الرسمي على Pi Browser:* http://zynmart3401.pinet.com
• *رابط بوت التعدين الرسمي:* `@zynpibot`
• يجب تعيين اسم مستخدم (@username) لحسابك.

3️⃣ *حماية النظام والعملة:*
أي محاولة لاختراق التطبيق، استغلال الثغرات، أو التحايل تؤدي للحظر الدائم وتجميد رصيد عملة ZYN.

4️⃣ *النطاق والتطبيق:*
تسري هذه القوانين داخل التطبيق وفي كافة مجموعات Telegram.

*هدفنا بناء مجتمع واعي، جاد وموثوق! 🚀*"""

ZYNMART_PROMPT = """
أنت المساعد الذكي الرسمي "AI for ZYNMART"، وظيفتك هي إرشاد ومساعدة رواد متجر "ZYNMART" داخل مجموعة التليجرام.

[حقائق ومعلومات المشروع الرسمية - التزم بها بنسبة 100% ولا تخترع أي معلومة خارجية]:
- اسم المنصة/المتجر: ZYNMART (سوق عالمي مرخص ومتكامل ضمن شبكة Pi Network).
- صاحب المشروع: صالح التونسي.
- مطور التطبيق: أيوب.
- العملة الرسمية للمتجر: ZYN.
- رابط المتجر التطبيقي: يفتح حصرياً داخل Pi Browser عبر الرابط الرسمي: http://zynmart3401.pinet.com
- رابط بوت التعدين: https://t.me/zynpibot
- الموقع الرسمي للأخبار والتحديثات: https://zynmartpi.github.io/

[التحديثات والأخبار الحينية المجلوبة تلقائياً]
{DYNAMIC_NEWS}

[قواعد صارمة للإجابة]:
1. أجب بأسلوب ذكي وجذاب يبدأ بالترحيب باسم العضو السائل.
2. التزم فقط بالحقائق المذكورة أعلاه. إذا سُئلت عن شيء لا تملك عنه معلومة مؤكدة، صرّح بوضوح أنك لا تملك المعلومة ووجّه المستخدم للموقع الرسمي.
3. التوجيه الدائم لرواد المتجر نحو رابط Pi Browser وبوت التعدين الرسمي.
4. يمنع منعاً باتاً اختراع أسماء، تواريخ، أو ميزات غير موجودة في التعليمات.
5. أجب باللغة العربية الفصحى أو التونسية المبسطة فقط، ويُمنع تماماً استخدام أي رموز أو لغات أجنبية غير مفهومة.
"""

GREETING_RESPONSE = """وعليكم السلام ورحمة الله وبركاته! 🌸
مرحباً بك في عائلة ZYNMART 🚀

أنا المساعد الذكي الخاص بالمشروع، وفي خدمتك دائماً:
🛒 **رابط المتجر (في Pi Browser):** http://zynmart3401.pinet.com
⛏️ **بوت التعدين والمهام اليومية:** https://t.me/zynpibot
🌐 **موقع التحديثات والأخبار الرسمية:** https://zynmartpi.github.io/

إذا كان لديك أي سؤال، يمكنك الإشارة لي بالمنشن: @zynmart_ai_bot وسأجيبك فوراً!"""

DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! 🚀\nتنجم تدخل للمتجر التفاعلي عبر Pi Browser: http://zynmart3401.pinet.com\nولبدء تعدين عملة ZYN والمهام اليومية افتح البوت: https://t.me/zynpibot"

# ==================== دوال المعالجة والبحث ====================

def get_latest_news():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(NEWS_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            return f"مستجدات المنصة من الموقع الرسمي:\n{response.text[:2000]}"
    except Exception as e:
        print(f"Error fetching news site: {e}")
    return "تابعوا أحدث التحديثات عبر الموقع الرسمي: https://zynmartpi.github.io/"

def search_duckduckgo(query):
    try:
        url = f"https://html.duckduckgo.com/html/?q={query}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(res.text, "html.parser")
                results = [a.get_text() for a in soup.find_all("a", class_="result__snippet")[:3]]
                if results:
                    return "\n".join(results)
            except ImportError:
                print("bs4 library not installed.")
    except Exception as e:
        print(f"Web Search Error: {e}")
    return ""

def get_hermes_response(user_message, user_name=""):
    """دالة Hermes المحسنة لمنع التخمين والرموز الصينية"""
    if not HERMES_API_KEY:
        return None

    try:
        latest_news = get_latest_news()
        web_info = search_duckduckgo(user_message)
        
        system_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", latest_news)
        if web_info:
            system_prompt += f"\n\n[معلومات من البحث الخارجي]:\n{web_info}"

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {HERMES_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "nousresearch/hermes-3-llama-3.1-405b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"اسم العضو: {user_name}\nالرسالة: {user_message}"}
            ],
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 600
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            reply_text = res_data['choices'][0]['message']['content']
            
            if any('\u4e00' <= char <= '\u9fff' for char in reply_text):
                print("Hermes returned Chinese. Fallback to Gemini.")
                return None
                
            return reply_text
    except Exception as e:
        print(f"Hermes Agent Error: {e}")
    
    return None

def get_gemini_response(user_message, is_admin_private=False, user_name=""):
    """دالة Gemini الاحتياطية"""
    keys = [k.strip() for k in GEMINI_API_KEYS if k.strip()]
    if not keys:
        return DEFAULT_FALLBACK_TEXT

    latest_news = get_latest_news()
    active_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", latest_news)

    headers = {"Content-Type": "application/json"}
    prompt_text = f"{active_prompt}\n\nاسم العضو: {user_name}\nالمستخدم: {user_message}"
    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.2}
    }

    for api_key in keys:
        models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=8)
                if response.status_code == 200:
                    candidates = response.json().get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", DEFAULT_FALLBACK_TEXT)
            except Exception:
                continue

    return DEFAULT_FALLBACK_TEXT

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def ban_telegram_member(chat_id, user_id):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Ban Error: {e}")

# ==================== المهام الدوريّة ====================

def task_check_usernames_daily():
    """مهمة إرسال قائمة الأعضاء الذين لا يملكون اسم مستخدم"""
    global active_group_chat_id
    no_username_list = []
    for uid, uinfo in list(known_users.items()):
        if isinstance(uinfo, dict):
            uname = uinfo.get("username")
            if not uname or uname == "None" or str(uname).strip() == "":
                name = uinfo.get("name") or "عضو"
                no_username_list.append(f"• {str(name).split()[0]}")

    target_chat = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if no_username_list and target_chat:
        users_str = "\n".join(no_username_list[:30])
        warning_msg = (
            "⚠️ **تنبيه هام (الفحص الدوري)**\n\n"
            "الأعضاء الكرام التالية أسماؤهم لا يملكون اسم مستخدم (@username):\n\n"
            f"{users_str}\n\n"
            "📢 **يرجى إنشاء اسم مستخدم لحساباتكم فوراً لحماية بياناتكم!**"
        )
        send_telegram_message(target_chat, warning_msg)

def task_keep_alive():
    try:
        requests.get(RENDER_APP_URL, timeout=5)
    except Exception as e:
        print(f"Keep-Alive Error: {e}")

def task_send_group_rules():
    target_chat = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if target_chat:
        send_telegram_message(target_chat, GROUP_RULE_TEXT)

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(task_check_usernames_daily, 'interval', hours=24)
scheduler.add_job(task_keep_alive, 'interval', minutes=10)
scheduler.add_job(task_send_group_rules, 'interval', hours=2)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ==================== الويب هوك ====================

@app.route("/", methods=["GET"])
def home():
    return "AI FOR ZYNMART Bot is Live with Hermes Agent!"

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    global active_group_chat_id
    if request.method == "GET":
        return "Webhook Endpoint Active!", 200

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
            active_group_chat_id = chat_id
            known_users[str(user_id)] = {
                "name": first_name,
                "username": username,
                "chat_id": chat_id
            }
            save_users_to_file()

        if "left_chat_member" in msg_obj:
            left_member = msg_obj["left_chat_member"]
            left_name = left_member.get("first_name", "العضو")
            left_id = left_member.get("id")

            farewell_msg = f"وداعاً {left_name} 👋\nتم حظرك رسمياً من العودة للمجموعة."
            send_telegram_message(chat_id, farewell_msg)
            ban_telegram_member(chat_id, left_id)
            return jsonify({"status": "ok"}), 200

        if user_message:
            if chat_type == "private" and user_id != ADMIN_ID:
                send_telegram_message(chat_id, "عذراً، الخاص مخصص للإدارة فقط. يرجى التواصل في القروب 🙏")
                return jsonify({"status": "ok"}), 200

            clean_msg = user_message.strip().lower()
            if clean_msg in ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير"]:
                send_telegram_message(chat_id, f"أهلاً بك يا {first_name} 👋\n" + GREETING_RESPONSE)
                return jsonify({"status": "ok"}), 200

            clean_bot_name = BOT_USERNAME.replace("@", "").lower()
            is_mentioned = BOT_USERNAME.lower() in clean_msg
            reply_to = msg_obj.get("reply_to_message", {})
            is_reply_to_bot = reply_to.get("from", {}).get("username", "").lower() == clean_bot_name

            if is_mentioned or is_reply_to_bot or chat_type == "private":
                query_text = user_message.replace(BOT_USERNAME, "").replace(f"@{clean_bot_name}", "").strip()
                if not query_text:
                    query_text = user_message

                reply = get_hermes_response(query_text, user_name=first_name)
                
                if not reply:
                    reply = get_gemini_response(query_text, is_admin_private=(user_id == ADMIN_ID), user_name=first_name)

                formatted_reply = f"مرحباً بك {first_name} 🌟\n\n{reply}"
                send_telegram_message(chat_id, formatted_reply, reply_to_message_id=message_id)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
