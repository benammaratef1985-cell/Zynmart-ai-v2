import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEYS = os.environ.get("GEMINI_API_KEY", "").split(",")
ADMIN_ID = 7560871853
BOT_USERNAME = "@zynmart_ai_bot"

ZYNMART_PROMPT = """
أنت المساعد الذكي الرسمي "AI for ZYNMART"، وظيفتك هي إرشاد ومساعدة رواد متجر "ZYNMART" داخل مجموعة التليجرام.

[معلومات المشروع والمنظومة]
- اسم المنصة/المتجر: ZYNMART (سوق عالمي مرخص ضمن شبكة Pi Network).
- صاحب المشروع: صالح التونسي.
- مطور التطبيق: أيوب.
- العملة الرسمية: ZYN (حالية في انتظار Testnet الخاص بـ Pi Network في الماينت).
- رابط المتجر التطبيقي: zynmart.pages.dev (يفتح حصرياً داخل Pi Browser عبر الرابط: zynmart.pages.dev).
- رابط بوت التعدين: https://t.me/zynpibot (تذكر الأعضاء بتفعيل بوت التعدين والمهام اليومية).

[مهامك الأساسية]
1. مساعدة رواد متجر ZYNMART وشرح كيفية الدخول للتطبيق والتعامل مع الأيقونات.
2. شرح بوت التعدين zynboot ورابطه https://t.me/zynpibot وكيفية التفاعل مع مهامه اليومية.
3. الترحيب بالأعضاء الجدد باسم متجر ZYNMART وتذكيرهم بالروابط الرسمية.
4. الإجابة على جميع الاستفسارات التقنية العامة المتعلقة بالبلوكشين، العقود الذكية، المفاهيم المالية، والعملات المشفرة بشكل احترافي ومبسط.
5. تشجيع أي تجار أو بائعين يرغبون في الانضمام إلى متجر ZYNMART.
6. الرد على رسائل التحية بطريقة محترمة ودودة.

[قواعد وقوانين الرد]
- الأسلوب: ودود، محترم، احترافي وبسيط (بالعربية أو الدارجة التونسية السلسة).
- تجيب بثقة وعمق على الأسئلة التقنية والمعرفية.
- فقط إذا كان السؤال يتعلق بحساب شخصي خاص بعضو محدد أو مشكلة تنفيذية معقدة جداً تتطلب تدخل الإدارة، قل: "سؤالك مهم، دقيقة نخلي الأدمن يجاوبك".
- حافظ على الاختصار والوضوح وتجنب التكرار الطويل.
"""

# رسالة الترحيب التلقائية وعرض الخدمات
GREETING_RESPONSE = """وعليكم السلام ورحمة الله وبركاته! 🌸
مرحباً بك في عائلة ZYNMART 🚀

أنا المساعد الذكي الخاص بالمشروع، وفي خدمتك دائماً:
🛒 **رابط المتجر (في Pi Browser):** zynmart.pages.dev
⛏️ **بوت التعدين والمهام اليومية:** https://t.me/zynpibot

إذا كان لديك أي سؤال تفصيلي، يمكنك الإشارة لي بالمنشن: @zynmart_ai_bot وسأجيبك فوراً!"""

DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! 🚀\nتنجم تدخل للمتجر التفاعلي عبر Pi Browser: zynmart.pages.dev\nولبدء تعدين عملة ZYN والمهام اليومية افتح البوت: https://t.me/zynpibot"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def get_gemini_response(user_message, is_admin_private=False):
    keys = [k.strip() for k in GEMINI_API_KEYS if k.strip()]
    if not keys:
        if is_admin_private:
            return "تنبيه للأدمن: مفتاح GEMINI_API_KEY غير مضاف في إعدادات Render!"
        return DEFAULT_FALLBACK_TEXT

    model_name = "gemini-3.6-flash"
    headers = {"Content-Type": "application/json"}
    prompt_text = f"{ZYNMART_PROMPT}\n\nالمستخدم: {user_message}"
    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

    last_error = ""

    for api_key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            # رفع مهلة الانتظار إلى 30 ثانية لتلقي الإجابات التقنية الطويلة
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
        user_message = data["message"].get("text", "")

        if user_message:
            # 1. المحادثات الخاصة
            if chat_type == "private":
                if user_id != ADMIN_ID:
                    send_telegram_message(chat_id, "عذراً، هذا الخاص مخصص لإدارة ZYNMART فقط. الرجاء التواصل في القروب 🙏")
                    return jsonify({"status": "ok"}), 200
                else:
                    reply = get_gemini_response(user_message, is_admin_private=True)
                    send_telegram_message(chat_id, reply)
                    return jsonify({"status": "ok"}), 200

            # 2. المحادثات في المجموعات (القروب)
            clean_msg = user_message.strip().lower()
            greetings = ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير", "السلام عليكم ورحمة الله"]

            # الترحيب التلقائي للتحيات (بدون استهلاك API)
            if any(g in clean_msg for g in greetings):
                send_telegram_message(chat_id, GREETING_RESPONSE)
                return jsonify({"status": "ok"}), 200

            # لا يجيب على باقي الأسئلة إلا إذا احتوت الرسالة على المنشن
            if BOT_USERNAME.lower() in clean_msg:
                # إزالة المنشن من نص السؤال حتى لا يربك الذكاء الاصطناعي
                query_text = user_message.replace(BOT_USERNAME, "").strip()
                reply = get_gemini_response(query_text, is_admin_private=False)
                send_telegram_message(chat_id, reply)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
