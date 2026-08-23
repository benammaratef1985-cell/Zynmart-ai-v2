import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# المتغيرات البيئية
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_ID = 7560871853  # معرف الأدمن المصرح له بالخاص

# قاعدة البيانات والتعليمات الشاملة للمساعد الذكي
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
4. تشجيع أي تجار أو بائعين يرغبون في الانضمام إلى متجر ZYNMART.
5. الرد على رسائل التحية بطريقة محترمة ودودة.

[قواعد وقوانين الرد]
- الأسلوب: ودود، محترم، وبسيط (بالعربية أو الدارجة التونسية السلسة).
- إذا سألك عضو عن سؤال لا تعرف إجابته، قل له بالضبط: "سؤالك مهم، دقيقة نخلي الأدمن يجاوبك".
- حافظ على الاختصار وتجنب التكرار الطويل إذا كانت المحادثة مستمرة.

مثال للترحيب:
"مرحبا بيك في عائلة ZYNMART 🥳 أنا المساعد متاعكم AI for ZYNMART. تنجم تدخل للمتجر من هنا: zynmart.pages.dev ومتنساش تفعل بوت التعدين: https://t.me/zynpibot"
"""

# الرسالة الاحتياطية العامة للقروب في حال فشل الذكاء الاصطناعي
DEFAULT_FALLBACK_TEXT = "مرحباً بك في ZYNMART! يمكنكم متابعة التحديثات عبر التطبيق في Pi Browser: zynmart.pages.dev وبوت التعدين: https://t.me/zynpibot"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def get_gemini_response(user_message, is_admin_private=False):
    if not GEMINI_API_KEY:
        if is_admin_private:
            return "تنبيه للأدمن: مفتاح GEMINI_API_KEY غير مضاف في إعدادات Render!"
        return DEFAULT_FALLBACK_TEXT

    # تجربة النماذج الحديثة والمعتمدة
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-pro"
    ]

    headers = {"Content-Type": "application/json"}
    prompt_text = f"{ZYNMART_PROMPT}\n\nالمستخدم: {user_message}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ]
    }

    last_error = ""
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            res_data = response.json()

            if response.status_code == 200:
                candidates = res_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", DEFAULT_FALLBACK_TEXT)
            
            # تسجيل الخلل وتجربة النموذج التالي
            error_info = res_data.get("error", {}).get("message", response.text)
            last_error = f"{model_name} -> {error_info}"

        except Exception as e:
            last_error = f"{model_name} Exception -> {str(e)}"
            continue

    # في حال فشل كل النماذج
    if is_admin_private:
        return f"تنبيه للأدمن (خطأ في النظام):\nالسبب: {last_error}"
    else:
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
                    # الأدمن فقط يرى الأخطاء في الخاص
                    reply = get_gemini_response(user_message, is_admin_private=True)
                    send_telegram_message(chat_id, reply)
                    return jsonify({"status": "ok"}), 200
            
            # 2. المجموعة العامة (رد عادي بدون إظهار أي أخطاء للأعضاء)
            reply = get_gemini_response(user_message, is_admin_private=False)
            send_telegram_message(chat_id, reply)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
