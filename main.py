import os, json, requests, threading, re
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

GEMINI_API_KEYS = []
for k, v in os.environ.items():
    if k.startswith("GEMINI_API_KEY") and v:
        for x in v.split(","):
            x = x.strip()
            if x and x not in GEMINI_API_KEYS:
                GEMINI_API_KEYS.append(x)

ADMIN_IDS = [7560871853, 6283667477]
BOT_USERNAME = "@zynmart_ai_bot"
NEWS_URL = "https://zynmartpi.github.io/"
DEFAULT_GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")

ALLOWED_DOMAINS = [
    "minepi.com", "zynmart3401.pinet.com", "zynmartpi.github.io",
    "x.com/ZYNMART", "coingecko.com", "okx.com", "binance.com", "dexscreener.com",
    "facebook.com", "www.facebook.com", "fb.com", "m.facebook.com"
]

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
                d = json.load(f)
                if isinstance(d, dict) and "users" in d:
                    known_users = d.get("users", {})
                    if d.get("active_group_chat_id"):
                        active_group_chat_id = d.get("active_group_chat_id")
    except: pass

load_users_from_file()

ZYNMART_PROMPT = """أنت ZYNMART Sovereign Engine.
حقائق أساسية:
- سوق عالمي ضمن منظومة Pi Network.
- صاحبه: صالح التونسي | المطور: أيوب | العملة الداخلية: ZYN.
- المنصة: http://zynmart3401.pinet.com
- منصة X: https://x.com/ZYNMART
- البريد: zyntrawalletp@gmail.com
- بوت التعدين: https://t.me/zynpibot
- الأخبار: https://zynmartpi.github.io/

قواعد التفاعل:
1. الترحيب والمقدمة: ابدأ بإلقاء تحية أو مقدمة راقية تناسب السؤال.
2. الخاتمة: انهِ الرد بخاتمة محترفة تعكس جودة الخدمات وتستقبل استفسارات الأعضاء.
3. الحياد والواقعية: وضح أن ZYN هي عملة المنصة الداخلية للتداول وأن ZYNMART ينتمي لبيئة Pi Network كلياً، فهما يتكاملان وليسا متنافسين.
4. يمنع التكرار الآلي للتفاصيل التقنية القديمة.

[الأخبار الحية] {DYNAMIC_NEWS}"""

DEFAULT_FALLBACK_TEXT = "ZYNMART: http://zynmart3401.pinet.com | تعدين: https://t.me/zynpibot"

def sanitize_urls(text):
    if not text: return text
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text()
    url_pattern = r'https?://[^\s]+'
    found_urls = re.findall(url_pattern, clean_text)
    for url in found_urls:
        is_allowed = any(domain in url for domain in ALLOWED_DOMAINS)
        if not is_allowed:
            clean_text = clean_text.replace(url, "")
    clean_text = clean_text.replace("✅ تمت المهمة", "").replace("تمت المهمة", "").strip()
    return clean_text

def search_official(query):
    if not TAVILY_API_KEY: return ""
    try:
        payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 2}
        res = requests.post("https://api.tavily.com/search", json=payload, timeout=5)
        if res.status_code == 200:
            results = res.json().get("results", [])
            evidence = []
            for r in results:
                content_snippet = r.get('content', '')[:200]
                evidence.append(f"المصدر: {r.get('url')} - {content_snippet}")
            return "\n".join(evidence)
    except Exception as e:
        print(f"Search Error: {e}")
    return ""

def get_latest_news():
    try:
        r = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            clean = soup.get_text(separator=" ", strip=True)
            return "اخبار: " + clean[:300]
    except: pass
    return "https://zynmartpi.github.io/"

def fetch_real_evidence(user_message):
    evidences = []
    low = user_message.lower()
    if any(k in low for k in ["pi", "باي", "باى", "سعر", "price", "okx"]):
        try:
            cg = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pi-network&vs_currencies=usd", timeout=4).json()
            price = cg.get("pi-network", {}).get("usd")
            if price:
                evidences.append(f"سعر Pi الحالي على Coingecko/OKX هو ${price} - https://www.coingecko.com/en/coins/pi-network")
                return "\n".join(evidences)
        except Exception as e:
            print(f"Fetch Error: {e}")
            
        evidences.append("سعر Pi المتاح حالياً يدور حول 0.35$ - https://www.coingecko.com/en/coins/pi-network")
    return "\n".join(evidences) if evidences else ""

def get_gemini_response(user_message, user_name="", search_context=""):
    if not GEMINI_API_KEYS: 
        return None
    
    evidence = fetch_real_evidence(user_message)
    news = get_latest_news()
    system_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", news)
    
    context_block = ""
    if evidence: context_block += "\n[الأدلة]: " + evidence
    if search_context: context_block += "\n[نتائج البحث]: " + search_context[:500]

    full_prompt = f"{system_prompt}\n{context_block}\n\nالمستخدم ({user_name}): {user_message}"

    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    for k in GEMINI_API_KEYS:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + k
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            if res.status_code == 200:
                parts = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts:
                    txt = parts[0].get("text", "")
                    if txt:
                        return sanitize_urls(txt)
        except Exception as e:
            print(f"Gemini Exception: {e}")
            continue
    return None

def get_hermes_response(user_message, user_name="", search_context=""):
    if not HERMES_API_KEY: return None
    try:
        evidence = fetch_real_evidence(user_message)
        if search_context:
            evidence += "\n" + search_context[:400]

        news = get_latest_news()
        system_prompt = ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}", news)

        if evidence:
            system_prompt += f"\n[أدلة موثوقة]:\n{evidence}\nأجب بناءً عليها بمقدمة وخاتمة مناسبة."

        payload = {
            "model": "nousresearch/hermes-3-llama-3.1-405b",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_name + ": " + user_message}],
            "temperature": 0.4,
            "max_tokens": 600
        }
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers={"Authorization": "Bearer " + HERMES_API_KEY, "Content-Type": "application/json"}, timeout=10)
        if res.status_code == 200:
            txt = res.json()["choices"][0]["message"]["content"]
            return sanitize_urls(txt)
    except Exception as e:
        print(f"Hermes Exception: {e}")
    return None

def get_ai_response(user_message, user_name="", search_context=""):
    res = get_gemini_response(user_message, user_name, search_context)
    if res: return res
    
    res_hermes = get_hermes_response(user_message, user_name, search_context)
    if res_hermes: return res_hermes

    return sanitize_urls(DEFAULT_FALLBACK_TEXT)

@app.route("/", methods=["GET"])
def index():
    return "Zynmart Bot Status: Online", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    global active_group_chat_id
    data = request.get_json(force=True, silent=True)
    if not data or "message" not in data:
        return jsonify({"status": "ok"}), 200
    
    msg = data["message"]
    chat_id = msg.get("chat", {}).get("id")
    chat_type = msg.get("chat", {}).get("type", "private")
    user_id = msg.get("from", {}).get("id")
    text = msg.get("text", "").strip()
    user_name = msg.get("from", {}).get("first_name", "")

    if text and chat_id and BOT_TOKEN:
        if chat_type in ["group", "supergroup"]:
            if active_group_chat_id != chat_id:
                active_group_chat_id = chat_id
                save_users_to_file()

        # التعامل مع الخاص
        if chat_type == "private":
            # 1. حماية الخاص: تجاهل أي شخص ليس أدمن
            if user_id not in ADMIN_IDS:
                return jsonify({"status": "ok"}), 200

            # 2. إذا كتب الأدمن أمر البث (بنسختيه)
            if text.startswith("ابدا البث") or text.startswith("ابدأ البث"):
                target_group = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
                if target_group:
                    raw_cmd = text.replace("ابدا البث", "").replace("ابدأ البث", "").strip()
                    
                    # نشر حرفي مع النقطتين :
                    if raw_cmd.startswith(":"):
                        broadcast_reply = raw_cmd[1:].strip()
                        broadcast_reply = sanitize_urls(broadcast_reply)
                    # نشر إبداعي بدون نقطتين
                    else:
                        search_query = raw_cmd if raw_cmd else "اخبار Pi Network و ZYNMART"
                        creative_order = f"اكتب منشور ابداعي كامل ومحفز وجاهز للنشر عن: {search_query}"
                        search_results = search_official(search_query)
                        broadcast_reply = get_ai_response(creative_order, user_name, search_context=search_results)

                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": target_group, "text": broadcast_reply})
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "✅ تم النشر في المجموعة بنجاح!"})
                else:
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "⚠️ لم يتم التعرف على المجموعة بعد."})
                return jsonify({"status": "ok"}), 200

            # 3. إذا كتب الأدمن رسالة عادية في الخاص (بدون كلمة ابدأ البث)، يجيبه البوت مباشرة
            search_res = ""
            if any(k in text.lower() for k in ["سعر", "اخبار", "أخبار", "news", "pi", "zyn"]):
                search_res = search_official(text)

            direct_reply = get_ai_response(text, user_name, search_context=search_res)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": direct_reply})
            return jsonify({"status": "ok"}), 200

        # التعامل مع المجموعات (عند الإشارة فقط)
        if chat_type in ["group", "supergroup"]:
            bot_handle = BOT_USERNAME.lower()
            clean_handle = bot_handle.replace("@", "")
            if bot_handle not in text.lower() and clean_handle not in text.lower():
                return jsonify({"status": "ok"}), 200

            search_res = ""
            if any(k in text.lower() for k in ["سعر", "اخبار", "أخبار", "news", "pi", "zyn"]):
                search_res = search_official(text)

            reply = get_ai_response(text, user_name, search_context=search_res)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": reply})

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
