import os, json, requests, threading
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)
BOT_TOKEN = os.environ.get("BOT_TOKEN","")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY","")
GEMINI_API_KEYS=[]
for k,v in os.environ.items():
    if k.startswith("GEMINI_API_KEY") and v:
        for x in v.split(","):
            x=x.strip()
            if x and x not in GEMINI_API_KEYS: GEMINI_API_KEYS.append(x)

ADMIN_IDS=[7560871853,6283667477]
BOT_USERNAME="@zynmart_ai_bot"
BOT_ID=BOT_TOKEN.split(":")[0] if ":" in BOT_TOKEN else "0"
NEWS_URL="https://zynmartpi.github.io/"
RENDER_APP_URL="https://ai-for-zynmart.onrender.com"
DEFAULT_GROUP_CHAT_ID=os.environ.get("GROUP_CHAT_ID","")
known_users={}
active_group_chat_id=DEFAULT_GROUP_CHAT_ID
file_lock=threading.Lock()

def save_users_to_file():
    try:
        with file_lock:
            with open("users.json","w",encoding="utf-8") as f:
                json.dump({"active_group_chat_id":active_group_chat_id,"users":known_users},f,ensure_ascii=False,indent=2)
    except: pass

def load_users_from_file():
    global known_users,active_group_chat_id
    try:
        if os.path.exists("users.json"):
            with open("users.json","r",encoding="utf-8") as f:
                d=json.load(f)
                if isinstance(d,dict) and "users" in d:
                    known_users=d.get("users",{})
                    if d.get("active_group_chat_id"): active_group_chat_id=d.get("active_group_chat_id")
    except: pass

load_users_from_file()

ZYNMART_PROMPT="انت ZYNMART Sovereign Engine. حقائق: سوق عالمي في Pi Network - صاحبه صالح التونسي - المطور ايوب - العملة ZYN - المتجر http://zynmart3401.pinet.com - التعدين https://t.me/zynpibot - الاخبار https://zynmartpi.github.io/ قوانين: عربي مبسط 5-12 سطر ممنوع لا املك معلومة [الاخبار] {DYNAMIC_NEWS}"
GREETING_RESPONSE="http://zynmart3401.pinet.com\nhttps://t.me/zynpibot\nhttps://zynmartpi.github.io/"
DEFAULT_FALLBACK_TEXT="ZYNMART: http://zynmart3401.pinet.com | تعدين: https://t.me/zynpibot"

def get_latest_news():
    try:
        r=requests.get(NEWS_URL,headers={"User-Agent":"Mozilla/5.0"},timeout=5)
        if r.status_code==200: return "اخبار: "+r.text[:800]
    except: pass
    return "https://zynmartpi.github.io/"

def fetch_real_evidence(user_message):
    evidences=[]
    low=user_message.lower()
    if "pi" in low:
        try:
            cg=requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pi-network&vs_currencies=usd&include_24hr_vol=true",timeout=7).json()
            price=cg.get("pi-network",{}).get("usd")
            vol=cg.get("pi-network",{}).get("usd_24h_vol",0)
            if price:
                evidences.append("دليل Coingecko الحقيقي: Pi = $"+str(price)+" حجم $"+str(int(vol))+" https://www.coingecko.com/en/coins/pi-network - السعر الوحيد الصحيح هو "+str(price))
        except: pass
    if "zyn" in low or "0x" in user_message:
        try:
            r=requests.get("https://api.dexscreener.com/latest/dex/search/?q=zyn",timeout=8).json()
            if r.get("pairs"):
                p=r["pairs"][0]
                evidences.append("دليل DEX: ZYN سعر $"+str(p.get("priceUsd","N/A"))+" سيولة $"+str(p.get("liquidity",{}).get("usd",0))+" رابط "+str(p.get("url","")))
        except: pass
    return "\n".join(evidences) if evidences else "خبرة ZYNMART"

# 1. دالة تصحيح وهلوسة الأسعار
def fix_price_hallucination(text):
    if not text:
        return text
    low = text.lower()
    if "pi" in low and ("$32" in text or "32.27" in text or "32.35" in text):
        try:
            cg = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pi-network&vs_currencies=usd", timeout=5).json()
            real = cg.get("pi-network",{}).get("usd",0.34)
            text = text.replace("$32.27","$"+str(real))
            text = text.replace("$32.35","$"+str(real))
            text = text.replace("$32","$"+str(real))
            text = text.replace("32.27",""+str(real))
            text = text.replace("32.35",""+str(real))
            text = text + "\n\nتصحيح Live: السعر الحقيقي $"+str(real)+" من Coingecko"
        except:
            pass
    return text

# 2. دالة Hermes مع التعديل
def get_hermes_response(user_message,user_name=""):
    if not HERMES_API_KEY: return None
    try:
        evidence=fetch_real_evidence(user_message)
        system_prompt=ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}",get_latest_news())+" قانون LIVE: الادلة "+evidence+" ممنوع اختراع اسعار انسخ الرقم حرفيا ابدا ب ⏳ واختم ب ✅ تمت المهمة"
        payload={"model":"nousresearch/hermes-3-llama-3.1-405b","messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_name+": "+user_message}],"temperature":0.1,"max_tokens":900}
        res=requests.post("https://openrouter.ai/api/v1/chat/completions",json=payload,headers={"Authorization":"Bearer "+HERMES_API_KEY,"Content-Type":"application/json"},timeout=15)
        if res.status_code==200:
            txt = res.json()["choices"][0]["message"]["content"]
            txt = fix_price_hallucination(txt)
            return txt
    except: pass
    return None

# 3. دالة Gemini مع التعديل
def get_gemini_response(user_message,user_name=""):
    if not GEMINI_API_KEYS: return DEFAULT_FALLBACK_TEXT
    system_prompt=ZYNMART_PROMPT.replace("{DYNAMIC_NEWS}",get_latest_news())
    payload={"contents":[{"parts":[{"text":system_prompt+"\n\n"+user_name+": "+user_message}]}]}
    for k in GEMINI_API_KEYS:
        try:
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key="+k
            res=requests.post(url,json=payload,headers={"Content-Type":"application/json"},timeout=10)
            if res.status_code==200:
                parts = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts:
                    txt = parts[0].get("text",DEFAULT_FALLBACK_TEXT)
                    txt = fix_price_hallucination(txt)
                    return txt
        except: continue
    return DEFAULT_FALLBACK_TEXT

def get_ai_response(user_message,user_name=""):
    res = get_hermes_response(user_message, user_name)
    if res: return res
    return get_gemini_response(user_message, user_name)

@app.route("/", methods=["GET"])
def index():
    return "Zynmart Bot Status: Online", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data or "message" not in data:
        return jsonify({"status": "ok"}), 200
    
    msg = data["message"]
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    user_name = msg.get("from", {}).get("first_name", "")

    if text and chat_id and BOT_TOKEN:
        reply = get_ai_response(text, user_name)
        requests.post("https://api.telegram.org/bot"+BOT_TOKEN+"/sendMessage", json={"chat_id": chat_id, "text": reply})

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
