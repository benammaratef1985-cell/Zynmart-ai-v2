import os
import requests
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEYS = os.environ.get("GEMINI_API_KEY", "").split(",")
ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"
GITHUB_REPO_API = "https://api.github.com/repos/zynmartpi/zynmartpi.github.io/events"

# قاعدة بيانات مؤقتة في الذاكرة لتخزين الأعضاء ومتابعة التحديثات
known_users = {}  # {user_id: {"name": str, "username": str/None}}
last_seen_github_id = None  # لتتبع آخر تحديث تم نشره من GitHub

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
- جودة وااختبارات النظام: اجتياز 140 اختباراً ناجحاً من أصل 140 (100%) تغطي الحماية، المتاجر، الأرصدة، والتدفق العملياتي (Flows)، بالإضافة لنظام نشر وتحديث آمن ومستقر.

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

# رسالة الترحيب التلقائية وعرض الخدمات
GREETING_RESPONSE = """وعليكم السلام ورحمة الله وبركاته! 🌸
مرحباً بك في عائلة ZYNMART 🚀

أنا المساعد الذكي الخاص بالمشروع، وفي خدمتك دائماً:
🛒 **رابط المتجر (في Pi Browser):** zynmart.pages.dev
⛏️ **بوت التعدين والمهام اليومية:** https://t.me/zynpibot
🌐 **موقع التحديثات والأخبار الرسمية:** https://zynmartpi.github.io/

إذا كان لديك أي سؤال تفصيلي، يمكنك الإشارة لي بالمنشن: @zynmart_ai_bot وسأجيبك فوراً!"""

DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! 🚀\nتنجم تدخل للمتجر التفاعلي عبر Pi Browser: zynmart.pages.dev\nولبدء تعدين عملة ZYN والمهام اليومية افتح البوت: https://t.me/zynpibot\nلمتابعة أحدث الأخبار والتحديثات: https://zynmartpi.github.io/"

def get_latest_news():
    """جلب محتوى التحديثات والأخبار من موقع GitHub Pages الرسمي"""
    try:
        response = requests.get(NEWS_URL, timeout=5)
        if response.status_code == 200:
            return response.text[:1500]
    except Exception as e:
        print(f"Error fetching news site: {e}")
    return "تابعوا أحدث التحديثات والأخبار الرسمية عبر الموقع: https://zynmartpi.github.io/"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def ban_telegram_member(chat_id, user_id):
    """حظر عضو من المجموعة"""
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

    model_name = "gemini-3.6-flash"
    headers = {"Content-Type": "application/json"}
    
    context_prefix = f"اسم العضو السائل: {user_name}\n" if user_name else ""
    prompt_text = f"{active_prompt}\n\n{context_prefix}المستخدم: {user_message}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    last_error = ""

    for api_key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
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
        return f"تنبيه للأدمن (استنفاد مفاتيح API):\nالسبب: {last_error}"
    return DEFAULT_FALLBACK_TEXT

# ==================== المهام الجديدة المضافة ====================

def task_check_usernames_daily():
    """المهمة 1: فحص واستعراض قائمة الأعضاء بدون اسم مستخدم كل 24 ساعة"""
    no_username_list = []
    
    for uid, uinfo in list(known_users.items()):
        if not uinfo.get("username"):
            no_username_list.append(f"- {uinfo.get('name', 'عضو')}")

    if no_username_list:
        group_chat_id = list(known_users.values())[0].get("chat_id") if known_users else None
        if group_chat_id:
            users_str = "\n".join(no_username_list)
            warning_msg = (
                "⚠️ **تنبيه هام ومكرر (فحص 24 ساعة الدوري)**\n\n"
                "قائمة الأعضاء الذين لا يملكون اسم مستخدم (Username):\n"
                f"{users_str}\n\n"
                "🔴 **يرجى إنشاء اسم مستخدم لحسابكم في التيليجرام فوراً!**\n"
                "قد تتعرضون لبعض المشاكل في حسابكم المرتبط بتعدين عملة **ZYN** عند إطلاق الشبكة الرسمية في حال عدم وجود Username."
            )
            send_telegram_message(group_chat_id, warning_msg)

def task_check_github_updates():
    """المهمة 3: المتابعة التلقائية وتفقّد أحداث وتحديثات GitHub"""
    global last_seen_github_id
    try:
        response = requests.get(GITHUB_REPO_API, timeout=10)
        if response.status_code == 200:
            events = response.json()
            if events:
                latest_event = events[0]
                event_id = latest_event.get("id")
                
                # إذا وجدنا تحديثاً جديداً لم يُنشر سابقاً
                if last_seen_github_id is not None and event_id != last_seen_github_id:
                    event_type = latest_event.get("type", "Update")
                    repo_name = latest_event.get("repo", {}).get("name", "ZynMart Repo")
                    
                    # صياغة منشور تقني واحترافي عبر Gemini
                    prompt = (
                        f"قم بصياغة منشور تقني واحترافي مشوق جداً لمجموعة تليجرام مشروع ZYNMART، "
                        f"تعلن فيه عن تحديث جديد تم إنشاؤه على GitHub الخاص بالمنصة.\n"
                        f"نوع التحديث: {event_type}\nاسم المستودع: {repo_name}\n"
                        f"اشرح بأسلوب راقٍ أن المنصة تواصل التطوير والتحديث لضمان أقصى حماية وسرعة للأرصدة والمعاملات."
                    )
                    announcement = get_gemini_response(prompt)
                    
                    group_chat_id = list(known_users.values())[0].get("chat_id") if known_users else None
                    if group_chat_id:
                        full_post = f"📢 **تحديث تقني جديد من GitHub!** 🚀\n\n{announcement}\n\n🌐 للمتابعة: {NEWS_URL}"
                        send_telegram_message(group_chat_id, full_post)
                
                last_seen_github_id = event_id
    except Exception as e:
        print(f"Error checking GitHub API: {e}")

# إعداد المجدول المكتبي لتشغيل المهام في الخلفية تلقائياً
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(task_check_usernames_daily, 'interval', hours=24)
scheduler.add_job(task_check_github_updates, 'interval', minutes=10)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# ===============================================================

@app.route("/", methods=["GET"])
def home():
    return "AI FOR ZYNMART Bot is Live!"

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return "Webhook Endpoint is Active!", 200

    data = request.get_json()
    if data and "message" in data:
        chat_id = data["message"]["chat"]["id"]
        chat_type = data["message"]["chat"]["type"]
        from_user = data["message"]["from"]
        user_id = from_user["id"]
        first_name = from_user.get("first_name", "صديقنا")
        username = from_user.get("username")
        user_message = data["message"].get("text", "")

        # حفظ العضو في الذاكرة للفحص الدوري
        if chat_type in ["group", "supergroup"]:
            known_users[user_id] = {
                "name": first_name,
                "username": username,
                "chat_id": chat_id
            }

        # المهمة 2: التعامل مع مغادرة الأعضاء وحظرهم
        if "left_chat_member" in data["message"]:
            left_member = data["message"]["left_chat_member"]
            left_name = left_member.get("first_name", "العضو")
            left_id = left_member.get("id")

            farewell_msg = (
                f"وداعاً {left_name} 👋\n\n"
                f"بما أنك اخترت المغادرة بنفسك، نعلمك بأنه قد تم حظرك رسمياً من العودة للمجموعة مجدداً.\n"
                f"نتمنى لك التوفيق!"
            )
            send_telegram_message(chat_id, farewell_msg)
            ban_telegram_member(chat_id, left_id)
            
            if left_id in known_users:
                del known_users[left_id]
            return jsonify({"status": "ok"}), 200

        if user_message:
            # 1. المحادثات الخاصة
            if chat_type == "private":
                if user_id != ADMIN_ID:
                    send_telegram_message(chat_id, "عذراً، هذا الخاص مخصص لإدارة ZYNMART فقط. الرجاء التواصل في القروب 🙏")
                    return jsonify({"status": "ok"}), 200
                else:
                    reply = get_gemini_response(user_message, is_admin_private=True, user_name=first_name)
                    send_telegram_message(chat_id, reply)
                    return jsonify({"status": "ok"}), 200

            # 2. المحادثات في المجموعات (القروب)
            clean_msg = user_message.strip().lower()

            # المهمة 1 (التنبيه اللحظي عند التفاعل بدون Username)
            if not username and chat_type in ["group", "supergroup"]:
                no_user_warn = (
                    f"أهلاً بك {first_name} ⚠️\n"
                    f"لاحظنا أن حسابك لا يملك اسم مستخدم (Username).\n"
                    f"يرجى إنشاء اسم مستخدم لحسابك فوراً لتجنب أي مشاكل في حسابك المرتبط بتعدين عملة ZYN عند إطلاق الشبكة الرسمية."
                )
                send_telegram_message(chat_id, no_user_warn)

            greetings = ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير", "السلام عليكم ورحمة الله"]

            # الترحيب التلقائي للتحيات (بدون استهلاك API)
            if any(g in clean_msg for g in greetings):
                greeting_text = f"أهلاً بك يا {first_name} 👋\n" + GREETING_RESPONSE
                send_telegram_message(chat_id, greeting_text)
                return jsonify({"status": "ok"}), 200

            # الرد فقط إذا احتوت الرسالة على المنشن
            if BOT_USERNAME.lower() in clean_msg:
                query_text = user_message.replace(BOT_USERNAME, "").strip()
                reply = get_gemini_response(query_text, is_admin_private=False, user_name=first_name)
                
                # إضافة المنشن والاسم لشد انتباه المتابعين
                formatted_reply = f"مرحباً بك {first_name} 🌟\n\n{reply}"
                send_telegram_message(chat_id, formatted_reply)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
