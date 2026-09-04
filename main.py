import os
import json
import requests
import threading
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY")
GEMINI_API_KEYS = []
for key, val in os.environ.items():
    if key.startswith("GEMINI_API_KEY") and val:
        for k in val.split(","):
            k = k.strip()
            if k and k not in GEMINI_API_KEYS:
                GEMINI_API_KEYS.append(k)

ADMIN_ID = 7560871853
ADMIN_IDS = [7560871853, 6283667477]
BOT_USERNAME = "@zynmart_ai_bot"
BOT_ID = BOT_TOKEN.split(":")[0] if BOT_TOKEN and ":" in BOT_TOKEN else "0"
NEWS_URL = "https://zynmartpi.github.io/"
RENDER_APP_URL = "https://ai-for-zynmart.onrender.com"
DEFAULT_GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID")
known_users = {}
active_group_chat_id = DEFAULT_GROUP_CHAT_ID
file_lock = threading.Lock()

def save_users_to_file():
    try:
        with file_lock:
            with open("users.json", "w", encoding="utf-8") as f:
                json.dump({"active_group_chat_id": active_group_chat_id, "users": known_users}, f, ensure_ascii=False, indent=2)
    except: pass

def load_users_from_file():
    global known_users, active_group_chat_id
    try:
        if os.path.exists("users.json"):
            with open("users.json", "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "users" in loaded:
                    known_users = loaded.get("users", {})
                    if loaded.get("active_group_chat_id"):
                        active_group_chat_id = loaded.get("active_group_chat_id")
    except: pass

load_users_from_file()

GROUP_RULE_TEXT = """📜 *قوانين Zynmart:*
1️⃣ الاحترام واجب
2️⃣ الرسمي فقط: http://zynmart3401.pinet.com و @zynpibot
3️⃣ لازم @username"""

ZYNMART_PROMPT = """أنت ZYNMART Sovereign Engine.
1- سؤال ZYNMART: جاوب من الحقائق:
- ZYNMART سوق عالمي في Pi Network
- صاحبه صالح التونسي - المطور أيوب - العملة ZYN
- المتجر: http://zynmart3401.pinet.com (Pi Browser)
- التعدين: https://t.me/zynpibot
- الاخبار: https://zynmartpi.github.io/
2- سؤال تقني: مهندس بلوكتشين، جاوب بمعادلة وكود مختصر. اذا غير متأكد قل "حسب خبرتي:"
قوانين: عربي مبسط، قصير 5-12 سطر، ممنوع "لا املك معلومة".
[الاخبار] {DYNAMIC_NEWS}"""

GREETING_RESPONSE = "🛒 http://zynmart3401.pinet.com\n⛏️ https://t.me/zynpibot\n🌐 https://zynmartpi.github.io/"
DEFAULT_FALLBACK_TEXT = "ZYNMART: http://zynmart3401.pinet.com | تعدين: https://t.me/zynpibot"

def get_latest_news():
    try:
        r = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            try:
                from bs4 import BeautifulSoup
                txt = BeautifulSoup(r.text, "html.parser").get_text(separator=" ", strip=True)
                return f"اخبار: {txt[:800]}"
            except:
                return f"اخبار: {r.text[:800]}"
    except: pass
    return "التحديثات: https://zynmartpi.github.io/"

def fetch_real_evidence(user_message):
    evidences = []
    low = user_message.lower()
    try:
        token = None
        if "0x" in user_message:
            token = "0x" + user_message.split("0x")[1].split()[0].replace(",","").replace(")","")
        elif "pi" in low: token = "pi"
        elif "zyn" in low: token = "zyn"
        if token:
            r = requests.get(f"https://api.dexscreener.com/latest/dex/search/?q={token}", timeout=7).json()
            if r.get('pairs'):
                p = r['pairs'][0]
                evidences.append(f"دليل DEX حقيقي: {p.get('url')} | سيولة ${p['liquidity']['usd']:,.0f} | حجم ${p['volume']['h24']:,.0f} | سعر ${p['priceUsd']}")
    except: pass
    try:
        r = requests.get(NEWS_URL, timeout=5)
        if r.status_code == 200:
            evidences.append(f"دليل ZYNMART حقيقي: {NEWS_URL} OK 200")
    except: pass
    if "pi" in low:
        try:
            cg = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pi-network&vs_currencies=usd", timeout=5).json()
            price = cg.get('pi-network',{}).get('usd')
            if price:
                evidences.append(f"دليل Coingecko Pi: ${price} https://www.coingecko.com/en/coins/pi-network")
        except: pass
    return "\n".join(evidences) if evidences else "خبرة ZYNMART الداخلية"

def get_hermes_response(user_message, user_name=""):
    if not HERMES_API_KEY: return None
    try:
        evidence = fetch_real_evidence(user_message)
        system_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", get_latest_news())
        system_prompt += f"""
قانون LIVE لإتمام المهام على أكمل وجه:
- الأدلة الحقيقية التي يجب ان تبني عليها: {evidence}
- أي مهمة تطلب منك: ابدأ بـ ⏳ وطبق ونفذ كود/جدول/قرار بالأرقام من الأدلة
- اذكر الروابط كدليل
- اختم دائما بـ ✅ تمت المهمة واغلقت - القرار النهائي + السبب
- ممنوع تترك المهمة معلقة او كلام عام
"""
        payload = {"model": "nousresearch/hermes-3-llama-3.1-405b","messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"{user_name}: {user_message}"}],"temperature": 0.1, "top_p": 0.7, "max_tokens": 900, "frequency_penalty": 0.3}
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {HERMES_API_KEY}", "Content-Type": "application/json"}, timeout=15)
        if res.status_code == 200:
            txt = res.json()['choices'][0]['message']['content']
            if any('\u4e00' <= c <= '\u9fff' for c in txt): return None
            return txt
    except: pass
    return None

def get_gemini_response(user_message, user_name=""):
    if not GEMINI_API_KEYS: return DEFAULT_FALLBACK_TEXT
    system_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", get_latest_news())
    payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_name}: {user_message}"}]}], "generationConfig": {"temperature": 0.1, "top_p": 0.7}}
    for api_key in GEMINI_API_KEYS:
        for model in ["gemini-1.5-flash", "gemini-2.0-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
                if r.status_code == 200:
                    cand = r.json().get("candidates", [])
                    if cand:
                        parts = cand[0].get("content", {}).get("parts", [])
                        if parts: return parts[0].get("text", DEFAULT_FALLBACK_TEXT)
            except: continue
    return DEFAULT_FALLBACK_TEXT

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    if not chat_id or not BOT_TOKEN: return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to_message_id: payload["reply_to_message_id"] = reply_to_message_id
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=5)
        return r.status_code == 200
    except: return False

def ban_telegram_member(chat_id, user_id):
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember", json={"chat_id": chat_id, "user_id": int(user_id)}, timeout=5)
    except: pass

def find_user_by_username(username):
    if not username: return None
    username = username.replace("@","").lower()
    for uid, info in known_users.items():
        if isinstance(info, dict) and info.get("username","").lower() == username:
            return uid, info
    return None

def task_check_usernames_daily():
    lst = [f"• {v.get('name','عضو').split()[0]}" for v in known_users.values() if isinstance(v, dict) and not v.get("username")]
    target = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if lst and target:
        return send_telegram_message(target, f"⚠️ **تنبيه دوري**\nبدون @username:\n" + "\n".join(lst[:20]))
    return False

def task_keep_alive():
    try: requests.get(f"{RENDER_APP_URL}/", timeout=5)
    except: pass

def task_send_group_rules():
    target = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
    if target: return send_telegram_message(target, GROUP_RULE_TEXT)
    return False

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(task_check_usernames_daily, 'interval', hours=24)
scheduler.add_job(task_keep_alive, 'interval', minutes=10)
scheduler.add_job(task_send_group_rules, 'interval', hours=6)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

@app.route("/", methods=["GET", "HEAD"])
def home(): return "ZYNMART Sovereign v7 - Admin Private Only! + LIVE Evidence Engine", 200

@app.route("/webhook", methods=["POST", "GET", "HEAD"])
def webhook():
    global active_group_chat_id
    if request.method in ["GET", "HEAD"]: return "Webhook Active!", 200
    data = request.get_json(silent=True)
    if not data or "message" not in data: return jsonify({"status": "ok"}), 200
    msg_obj = data["message"]
    if "from" not in msg_obj: return jsonify({"status": "ok"}), 200
    chat_id = msg_obj["chat"]["id"]
    chat_type = msg_obj["chat"]["type"]
    from_user = msg_obj["from"]
    user_id = str(from_user["id"])
    try: is_admin = int(user_id) in ADMIN_IDS
    except: is_admin = False
    first_name = from_user.get("first_name", "صديقنا")
    username = from_user.get("username")
    user_message = msg_obj.get("text") or msg_obj.get("caption") or ""
    message_id = msg_obj.get("message_id")
    if chat_type == "private":
        if not is_admin:
            return jsonify({"status": "ok - private blocked"}), 200
        if len(user_message) > 1000: user_message = user_message[:1000]
        if user_message.startswith("/reset_warnings"):
            parts = user_message.split()
            if len(parts) >= 2:
                found = find_user_by_username(parts[1])
                if found:
                    uid, info = found
                    known_users[uid]["leave_count"] = 0
                    save_users_to_file()
                    send_telegram_message(chat_id, f"✅ تم مسح انذارات {parts[1]}\nالاسم: {info.get('name')}", reply_to_message_id=message_id)
                else: send_telegram_message(chat_id, f"❌ لم اجد {parts[1]}", reply_to_message_id=message_id)
            else: send_telegram_message(chat_id, "استعمل: /reset_warnings @username", reply_to_message_id=message_id)
            return jsonify({"status": "ok"}), 200
        if user_message.strip() == "/warnings":
            warn_list = [f"• {v.get('name','مجهول')} (@{v.get('username','بدون')}) : {v.get('leave_count')}/2" for v in known_users.values() if isinstance(v, dict) and v.get("leave_count",0)>0]
            if warn_list: send_telegram_message(chat_id, "📋 **قائمة الانذارات (سيادي - سري):**\n" + "\n".join(warn_list[:30]), reply_to_message_id=message_id)
            else: send_telegram_message(chat_id, "✅ لا يوجد انذارات", reply_to_message_id=message_id)
            return jsonify({"status": "ok"}), 200
        if user_message.strip() == "/stats":
            total = len(known_users)
            with_warn = len([u for u in known_users.values() if isinstance(u, dict) and u.get("leave_count",0)>0])
            send_telegram_message(chat_id, f"📊 **احصائيات سيادية:**\nالاجمالي: {total}\nعليهم انذارات: {with_warn}\nالقروب النشط: {active_group_chat_id}\nID السيادة: {ADMIN_ID} + {ADMIN_IDS}", reply_to_message_id=message_id)
            return jsonify({"status": "ok"}), 200
        if user_message:
            reply = get_hermes_response(user_message, user_name=first_name)
            if not reply: reply = get_gemini_response(user_message, user_name=first_name)
            send_telegram_message(chat_id, reply, reply_to_message_id=message_id)
            return jsonify({"status": "ok"}), 200
    if len(user_message) > 1000: user_message = user_message[:1000]
    if chat_type in ["group", "supergroup"]:
        active_group_chat_id = chat_id
        if user_id not in known_users:
            known_users[user_id] = {"name": first_name, "username": username, "chat_id": chat_id, "leave_count": 0}
        else:
            known_users[user_id]["name"] = first_name
            known_users[user_id]["username"] = username
        save_users_to_file()
        if "new_chat_members" in msg_obj:
            for nm in msg_obj["new_chat_members"]:
                nm_id = str(nm["id"])
                if nm_id == BOT_ID: continue
                existing = known_users.get(nm_id, {})
                known_users[nm_id] = {"name": nm.get("first_name","عضو"), "username": nm.get("username"), "chat_id": chat_id, "leave_count": existing.get("leave_count", 0)}
            save_users_to_file()
        if "left_chat_member" in msg_obj:
            left_member = msg_obj["left_chat_member"]
            left_id = str(left_member.get("id"))
            left_name = left_member.get("first_name", "العضو")
            if left_id == BOT_ID: return jsonify({"status": "ok"}), 200
            leave_count = known_users.get(left_id, {}).get("leave_count", 0) + 1
            if left_id in known_users: known_users[left_id]["leave_count"] = leave_count
            else: known_users[left_id] = {"name": left_name, "username": None, "leave_count": leave_count, "chat_id": chat_id}
            save_users_to_file()
            if leave_count == 1: send_telegram_message(chat_id, f"⚠️ {left_name} خرج (إنذار 1/2). اذا عاد وخرج سيتم حظره.")
            elif leave_count == 2:
                send_telegram_message(chat_id, f"🚫 {left_name} تم حظره (إنذار 2/2).")
                ban_telegram_member(chat_id, left_id)
            return jsonify({"status": "ok"}), 200
        if user_message:
            clean_msg = user_message.strip().lower()
            if clean_msg in ["السلام عليكم", "سلام عليكم", "صباح الخير", "مساء الخير"]:
                send_telegram_message(chat_id, f"أهلا بك يا {first_name} 👋\n{GREETING_RESPONSE}")
                return jsonify({"status": "ok"}), 200
            is_mentioned = BOT_USERNAME.lower() in clean_msg
            reply_to = msg_obj.get("reply_to_message", {})
            is_reply_to_bot = reply_to.get("from", {}).get("username","").lower() == BOT_USERNAME.replace("@","").lower()
            if is_mentioned or is_reply_to_bot:
                query_text = user_message.replace(BOT_USERNAME, "").strip() or user_message
                reply = get_hermes_response(query_text, user_name=first_name)
                if not reply: reply = get_gemini_response(query_text, user_name=first_name)
                send_telegram_message(chat_id, reply, reply_to_message_id=message_id)
                return jsonify({"status": "ok"}), 200
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
