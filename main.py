import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEYS = os.environ.get("GEMINI_API_KEY", "").split(",")
ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"

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
            # اقتطاع أول 1500 حرف لضمان عدم تجاوز حدود الـ API وسرعة الاستجابة
            return response.text[:1500]
    except Exception as e:
        print(f"Error fetching news site: {e}")
    return "تابعوا أحدث التحديثات والأخبار الرسمية عبر الموقع: https://zynmartpi.github.io/"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def get_gemini_response(user_message, is_admin_private=False, user_name=""):
    keys = [k.strip() for k in GEMINI_API_KEYS if k.strip()]
    if not keys:
        if is_admin_private:
            return "تنبيه للأدمن: مفتاح GEMINI_API_KEY غير مضاف في إعدادات Render!"
        return DEFAULT_FALLBACK_TEXT

    # جلب التحديثات الحينية من موقع الأخبار الرسمي
    latest_news = get_latest_news()
    active_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", latest_news)

    model_name = "gemini-3.6-flash"
    headers = {"Content-Type": "application/json"}
    
    # إضافة اسم العضو للتعليمات ليوجه له الرد مباشرة
    context_prefix = f"اسم العضو السائل: {user_name}\n" if user_name else ""
    prompt_text = f"{active_prompt}\n\n{context_prefix}المستخدم: {user_message}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    last_error = ""

    for api_key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            # مهلة الانتظار 30 ثانية للإجابات المعقدة
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
        user_id = data["message"]["from"]["id"]
        first_name = data["message"]["from"].get("first_name", "صديقنا")
        user_message = data["message"].get("text", "")

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
