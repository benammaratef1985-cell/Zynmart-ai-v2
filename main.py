import os
import json
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

GEMINI_API_KEYS = []
for key, val in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and val:
        GEMINI_API_KEYS.extend([k.strip() for k in val.split(",") if k.strip()])

ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"
GITHUB_REPO_API = "https://api.github.com/repos/benammaratef1985-cell/Zynmart-ai-v2/events"

RENDER_APP_URL = "https://ai-for-zynmart.onrender.com"
DEFAULT_GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")

known_users = {}
last_seen_github_id = None
active_group_chat_id = DEFAULT_GROUP_CHAT_ID

# ==================== دوال التعامل مع users.json ====================

def save_users_to_file():
    """حفظ بيانات الأعضاء في ملف users.json"""
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
    """قراءة بيانات الأعضاء من ملف users.json عند التشغيل"""
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

# =================================================================

GROUP_RULE_TEXT = """📜 *سياسة الانضباط وقوانين مجتمع Zynmart الرسمية:*

حرصاً على حماية المنصة وتوفير بيئة جادة ومحترمة، نرجو من الجميع الالتزام الصارم بالقواعد التالية:

1️⃣ *الجدية والاحترام:*
المجموعة مخصصة للاستفسارات وتبادل المعرفة فقط. يُمنع السب، الإساءة، أو إثارة الفتنة. (ملاحظة: التذرع بـ "أنا أمزح" بعد إزعاج أي عضو لا يعفي صاحبه من المخالفة).

2️⃣ *الأمان والهوية والروابط الرسمية:*
• يمنع نشر الروابط الخارجية غير الرسمية أو الإعلانات التجارية.
• *رابط المتجر الرسمي:* [zynmart.pages.dev](https://zynmart.pages.dev)
• *رابط بوت التعدين الرسمي:* `@zynpibot`
• يجب تعيين اسم مستخدم (@username) لحسابك، الحسابات الوهمية لا تمنح أي حماية ويتم تتبعها.

3️⃣ *حماية النظام والعملة:*
أي محاولة لااختراق التطبيق، استغلال الثغرات، أو التحايل تؤدي للحظر الدائم وتجميد رصيد عملة ZYN مع حظر الجهاز بالكامل.

4️⃣ *النطاق والتطبيق:*
تسري هذه القوانين داخل التطبيق وفي كافة مجموعات Telegram. للإدارة الحق في اتخاذ إجراءات فورية (حظر مؤقت/دائم) أو حظر إضافي عند محاولة الالتفاف على النظام.

*هدفنا بناء مجتمع واعي، جاد وموثوق. نرحب بالجميع للتعلم والتطور معنا! 🚀*"""

ZYNMART_PROMPT = """
أنت المساعد الذكي الرسمي "AI for ZYNMART"، وظيفتك هي إرشاد ومساعدة رواد متجر "ZYNMART" داخل مجموعة التليجرام.

[معلومات المشروع والمنظومة]
- اسم المنصة/المتجر: ZYNMART (سوق عالمي مرخص ومتكامل ضمن شبكة Pi Network).
- صاحب المشروع: صالح التونسي.
- مطور التطبيق: أيوب.
- العملة الرسمية للمتجر: ZYN (حالية في انتظار Testnet الخاص بـ Pi Network في الماينت).
- رابط المتجر التطبيقي: zynmart.pages.dev (يفتح حصرياً داخل Pi Browser عبر الرابط: zynmart.pages.dev).
- رابط بوت التعدين: https://t.me/zynpibot (تذكر الأعضاء بتفعيل بوت التعدين والمهام اليومية).
- الموقع الرسمي للأخبار والتحديثات: https://zynmartpi.github.io/

[التحديثات الأخيرة الشاملة للمنصة (الأمان، الأداء، والطلبات)]
- الأمان والحماية: تعزيز الحماية بالكامل؛ التأكد من هوية المستخدم وصلاحياته قبل أي عملية، حماية الأرصدة والعمليات المالية من الوصول أو التعديل غير المصرح به، وحماية البيانات الحساسة.
- عمليات المتجر والشراء (Marketplace): إدارة فائقة للمنتجات والمخزون، التحقق من الرصيد الكافي قبل الشراء، وتحديث الرصيد والطلب والمخزون بشكل متناسق ومضمون دون أخطاء.
- دورة الطلبات المكتملة: تتبع دقيق ومحمي للطلب (طلب جديد ← دفع ← شحن ← تأكيد الاستلام ← إتمام العملية) مع تحكم كامل بالصلاحيات بين البائع والمشتري.
- الأداء وقواعد البيانات: تحسين الاستعلامات المالية والبيانات بنسبة 97.5% (39/40) لإلغاء أي بطء، مع إضافة مراقبة آلية للعمليات البطيئة لضمان أقصى سرعة.
- جودة واختبارات النظام: اجتياز 140 اختباراً ناجحاً من أصل 140 (100%) تغطي الحماية، المتاجر، الأرصدة، والتدفق العملياتي (Flows)، بالإضافة لنظام نشر وتحديث آمن ومستقر.

[التحديثات والأخبار الحينية المجلوبة من الموقع الرسمي]
{DYNAMIC_NEWS}

[مهامك وأسلوب الرد]
1. توجيه الإجابة بأسلوب ذكي وجذاب: ابدأ الرد بالترحيب بالسائل بأناقة باسمه، واستخدم أسلوباً مشوقاً يلفت انتباه باقي الأعضاء والمتابعين في القروب للاستفادة من المعلومة.
2. الاستدلال بأحدث الأخبار والتحديثات المجلوبة من الموقع الرسمي zynmartpi.github.io عند الإجابة على استفسارات الأعضاء.
3. شرح وتوضيح كفاءة وأمان منصة ZYNMART بناءً على التحديثات الأخيرة وطمأنة المستخدمين حول أرصدتهم ومعاملاتهم.
4. مساعدة رواد المتجر وشرح كيفية الدخول للتطبيق zynmart.pages.dev عبر Pi Browser وتصفح المنتجات.
5. شرح بوت التعدين zynboot ورابطه https://t.me/zynpibot وكيفية التفاعل مع المهام اليومية لجمع عملة ZYN.
6. الترحيب بالأعضاء الجدد وتشجيع التجار والبائعين على الانضمام لمنصة آمنة وسريعة وموثوقة.
7. الإجابة على جميع الاستفسارات التقنية العامة المتعلقة بالبلوكشين، العقود الذكية، الـ Launchpad، الـ DEX، والعملات المشفرة بشكل احترافي ومبسط.

[قواعد وقوانين الرد]
- الأسلوب: ودود، محترم، احترافي وبسيط (بالعربية أو الدارجة التونسية السلسة).
- تجيب بثقة وعمق على الأسئلة التقنية والمستجدات بناءً على معلومات المشروع والموقع الرسمي.
- فقط إذا كان السؤال يتعلق بحساب شخصي خاص بعضو محدد أو مشكلة تنفيذية معقدة جداً تتطلب تدخل الإدارة المباشر، قل: "سؤالك مهم، دقيقة نخلي الأدمن يجاوبك".
- حافظ على الاختصار والوضوح وتجنب التكرار الطويل.
"""

GREETING_RESPONSE = """وعليكم السلام ورحمة الله وبركاته! 🌸
مرحباً بك في عائلة ZYNMART 🚀

أنا المساعد الذكي الخاص بالمشروع، وفي خدمتك دائماً:
🛒 **رابط المتجر (في Pi Browser):** zynmart.pages.dev
⛏️ **بوت التعدين والمهام اليومية:** https://t.me/zynpibot
🌐 **موقع التحديثات والأخبار الرسمية:** https://zynmartpi.github.io/

إذا كان لديك أي سؤال تفصيلي، يمكنك الإشارة لي بالمنشن: @zynmart_ai_bot وسأجيبك فوراً!"""

DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! 🚀\nتنجم تدخل للمتجر التفاعلي عبر Pi Browser: zynmart.pages.dev\nولبدء تعدين عملة ZYN والمهام اليومية افتح البوت: https://t.me/zynpibot\nلمتابعة أحدث الأخبار والتحديثات: https://zynmartpi.github.io/"

def get_latest_news():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(NEWS_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.text[:1500]
    except Exception as e:
        print(f"Error fetching news site: {e}")
    return "تابعوا أحدث التحديثات والأخبار الرسمية عبر الموقع: https://zynmartpi.github.io/"

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def ban_telegram_member(chat_id, user_id):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember"
    payload = {"chat_id": chat_id, "user_id": user_id}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Ban Error: {e}")

def get_gemini_response(user_message, is_admin_private=False, user_name=""):
    keys = [k.strip() for k in GEMINI_API_KEYS if k.strip()]
    if not keys:
        if is_admin_private:
            return "تنبيه للأدمن: مفتاح GEMINI_API_KEY غير مضاف في إعدادات Render!"
        return DEFAULT_FALLBACK_TEXT

    latest_news = get_latest_news()
    active_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", latest_news)

    # قائمة الموديلات المستقرة والمتاحة على الخطة المجانية
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash"
    ]
    
    headers = {"Content-Type": "application/json"}
    context_prefix = f"اسم العضو السائل: {user_name}\n" if user_name else ""
    prompt_text = f"{active_prompt}\n\n{context_prefix}المستخدم: {user_message}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    last_error = ""

    for api_key in keys:
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=20)
                res_data = response.json()

                if response.status_code == 200:
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", DEFAULT_FALLBACK_TEXT)

                last_error = res_data.get("error", {}).get("message", response.text)
            except Exception as e:
                last_error = str(e)
                continue

    if is_admin_private:
        return f"تنبيه للأدمن (استنفاد كافة المفاتيح والموديلات):\nالسبب: {last_error}"
    return DEFAULT_FALLBACK_TEXT

# ==================== المهام الدوريّة ====================

def task_check_usernames_daily():
    global active_group_chat_id
    no_username_list = []
    
    for uid, uinfo in list(known_users.items()):
        if isinstance(uinfo, dict):
            uname = uinfo.get("username")
            if not uname or uname == "None" or str(uname).strip() == "":
                name = uinfo.get("name") or uinfo.get("first_name") or "عضو"
                first_name = str(name).split()[0]
                no_username_list.append(f"• {first_name}")

    target_chat = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if no_username_list and target_chat:
        users_str = "\n".join(no_username_list[:30])
        warning_msg = (
            "⚠️ **تنبيه هام (الفحص الدوري للأعضاء)**\n\n"
            "الأعضاء الكرام التالية أسماؤهم لا يملكون اسم مستخدم (@username):\n\n"
            f"{users_str}\n\n"
            "📢 **يرجى إنشاء اسم مستخدم (Username) لحساباتكم فوراً!**\n"
            "ذلك لضمان توثيق حساباتكم وحمايتها عند التفاعل مع المتجر وبوت التعدين."
        )
        send_telegram_message(target_chat, warning_msg)
        return f"Found {len(no_username_list)} users without username. Message sent!"
    
    return f"Checked {len(known_users)} total users. Found {len(no_username_list)} without username. No message sent."

def task_check_github_updates():
    global last_seen_github_id, active_group_chat_id
    try:
        headers = {"User-Agent": "ZynmartBot/1.0"}
        response = requests.get(GITHUB_REPO_API, headers=headers, timeout=10)
        if response.status_code == 200:
            events = response.json()
            if isinstance(events, list) and events:
                latest_event = events[0]
                event_id = latest_event.get("id")
                
                if last_seen_github_id is not None and event_id != last_seen_github_id:
                    event_type = latest_event.get("type", "Update")
                    repo_name = latest_event.get("repo", {}).get("name", "ZynMart Repo")
                    
                    prompt = (
                        f"قم بصياغة منشور تقني واحترافي مشوق جداً لمجموعة تليجرام مشروع ZYNMART، "
                        f"تعلن فيه عن تحديث جديد تم إنشاؤه على GitHub الخاص بالمنصة.\n"
                        f"نوع التحديث: {event_type}\nاسم المستودع: {repo_name}\n"
                        f"اشرح بأسلوب راقٍ أن المنصة تواصل التطوير والتحديث لضمان أقصى حماية وسرعة للأرصدة والمعاملات."
                    )
                    announcement = get_gemini_response(prompt)
                    
                    target_chat = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
                    if target_chat:
                        full_post = f"📢 **تحديث تقني جديد من GitHub!** 🚀\n\n{announcement}\n\n🌐 للمتابعة: {NEWS_URL}"
                        send_telegram_message(target_chat, full_post)
                
                last_seen_github_id = event_id
    except Exception as e:
        print(f"Error checking GitHub API: {e}")

def task_keep_alive():
    try:
        requests.get(RENDER_APP_URL, timeout=10)
    except Exception as e:
        print(f"Keep-Alive Error: {e}")

def task_send_group_rules():
    target_chat = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if target_chat:
        send_telegram_message(target_chat, GROUP_RULE_TEXT)

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(task_check_usernames_daily, 'interval', hours=24)
scheduler.add_job(task_check_github_updates, 'interval', minutes=10)
scheduler.add_job(task_keep_alive, 'interval', minutes=10)
scheduler.add_job(task_send_group_rules, 'interval', hours=2)

scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ==================== المسارات والويب هوك ====================

@app.route("/", methods=["GET"])
def home():
    return "AI FOR ZYNMART Bot is Live!"

@app.route("/send-rules", methods=["GET"])
def trigger_rules_endpoint():
    task_send_group_rules()
    return "Rules Triggered Successfully", 200

@app.route("/check-users", methods=["GET"])
def trigger_users_check_endpoint():
    result_status = task_check_usernames_daily()
    return f"Check Result: {result_status}", 200

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    global active_group_chat_id
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
            active_group_chat_id = chat_id
            known_users[str(user_id)] = {
                "name": first_name,
                "username": username,
                "chat_id": chat_id,
                "chat_type": chat_type
            }
            save_users_to_file()

        if "left_chat_member" in msg_obj:
            left_member = msg_obj["left_chat_member"]
            left_name = left_member.get("first_name", "العضو")
            left_id = left_member.get("id")

            farewell_msg = (
                f"وداعاً {left_name} 👋\n\n"
                f"بما أنك اخترت المغادرة بنفسك، نعلمك بأنه قد تم حظرك رسمياً من العودة للمجموعة مجدداً.\n"
                f"نتمنى لك التوفيق!"
            )
            send_telegram_message(chat_id, farewell_msg)
            ban_telegram_member(chat_id, left_id)
            
            if str(left_id) in known_users:
                del known_users[str(left_id)]
                save_users_to_file()
            return jsonify({"status": "ok"}), 200

        if user_message:
            if chat_type == "private":
                if user_id != ADMIN_ID:
                    send_telegram_message(chat_id, "عذراً، هذا الخاص مخصص لإدارة ZYNMART فقط. الرجاء التواصل في القروب 🙏")
                    return jsonify({"status": "ok"}), 200
                else:
                    reply = get_gemini_response(user_message, is_admin_private=True, user_name=first_name)
                    send_telegram_message(chat_id, reply)
                    return jsonify({"status": "ok"}), 200

            clean_msg = user_message.strip().lower()

            greetings = ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير", "السلام عليكم ورحمة الله"]

            if clean_msg in greetings:
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
                if not query_text:
                    query_text = user_message
                
                reply = get_gemini_response(query_text, is_admin_private=False, user_name=first_name)
                formatted_reply = f"مرحباً بك {first_name} 🌟\n\n{reply}"
                send_telegram_message(chat_id, formatted_reply, reply_to_message_id=message_id)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
