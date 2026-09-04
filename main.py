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
- صاحبه صالح التونسي
- المطور أيوب
- العملة ZYN
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
    # Pi سعر حقيقي
    if "pi" in low:
        try:
            cg = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pi-network&vs_currencies=usd&include_24hr_vol=true", timeout=7).json()
            price = cg.get('pi-network',{}).get('usd')
            vol = cg.get('pi-network',{}).get('usd_24h_vol')
            if price:
                evidences.append(f"دليل Coingecko الحقيقي والحصري والوحيد: Pi Network = ${price} | حجم 24س ${vol:,.0f} | الرابط https://www.coingecko.com/en/coins/pi-network - هذا هو السعر الصحيح الوحيد، ممنوع ذكر أي سعر آخر غير {price} دولار")
        except Exception as e:
            print(f"CG error {e}")
    # ZYN سعر حقيقي
    if "zyn" in low or "0x" in user_message:
        try:
            r = requests.get("https://api.dexscreener.com/latest/dex/search/?q=zyn", timeout=8).json()
            if r.get('pairs'):
                p = r['pairs'][0]
                evidences.append(f
