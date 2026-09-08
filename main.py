import os, json, requests, threading, re, time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
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
    "x.com", "coingecko.com", "okx.com", "binance.com",
    "dexscreener.com", "facebook.com", "fb.com",
    "t.me", "openrouter.ai", "tavily.com"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "bot_settings.json")
WARNINGS_FILE = os.path.join(BASE_DIR, "warnings.json")
MOD_LOG_FILE = os.path.join(BASE_DIR, "moderation_log.json")
DAILY_FILE = os.path.join(BASE_DIR, "daily_messages.json")

known_users = {}
active_group_chat_id = DEFAULT_GROUP_CHAT_ID
file_lock = threading.RLock()
state_lock = threading.RLock()
background_services_started = False
background_services_lock = threading.Lock()

admin_modes = {}
pending_questions = {}
moderation_cache = {}
last_message_cache = {}
manual_exceptions = set()

DEFAULT_SETTINGS = {
    "question_delay": 60,
    "moderation_enabled": True,
    "moderation_level": "medium",
    "daily_enabled": True,
    "daily": {
        "morning": {"time": "08:00", "text": "صباح الخير 🌅 نتمنى لكم يومًا موفقًا ومليئًا بالنجاح."},
        "midday": {"time": "13:00", "text": "نهاركم طيب 🌞 نتمنى لكم يومًا جميلًا ومثمرًا."},
        "evening": {"time": "20:00", "text": "سهرة سعيدة للجميع 🌙✨ نتمنى لكم وقتًا ممتعًا."}
    },
    "last_daily_sent": {},
    "manual_exceptions": []
}

def atomic_save(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"Save Error {path}: {e}")

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
    except Exception as e:
        print(f"Load Error {path}: {e}")
    return default

def save_users_to_file():
    with file_lock:
        atomic_save(USERS_FILE, {
            "active_group_chat_id": active_group_chat_id,
            "users": known_users
        })

def load_users_from_file():
    global known_users, active_group_chat_id
    data = load_json(USERS_FILE, {})
    if isinstance(data, dict):
        known_users = data.get("users", {}) if isinstance(data.get("users", {}), dict) else {}
        if data.get("active_group_chat_id"):
            active_group_chat_id = str(data["active_group_chat_id"])

def load_settings():
    data = load_json(SETTINGS_FILE, {})
    settings = json.loads(json.dumps(DEFAULT_SETTINGS, ensure_ascii=False))
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "daily" and isinstance(v, dict):
                for name, item in v.items():
                    if name in settings["daily"] and isinstance(item, dict):
                        settings["daily"][name].update(item)
            else:
                settings[k] = v
    return settings

settings = load_settings()
manual_exceptions = set(int(x) for x in settings.get("manual_exceptions", []) if str(x).lstrip("-").isdigit())
daily_data = load_json(DAILY_FILE, {})
if isinstance(daily_data, dict) and daily_data.get("daily"):
    settings["daily"] = daily_data["daily"]
if isinstance(daily_data, dict) and isinstance(daily_data.get("last_daily_sent"), dict):
    settings["last_daily_sent"] = daily_data["last_daily_sent"]
warnings_db = load_json(WARNINGS_FILE, {})
moderation_log = load_json(MOD_LOG_FILE, [])

def save_settings():
    with file_lock:
        atomic_save(SETTINGS_FILE, settings)

def save_daily_data():
    with file_lock:
        atomic_save(DAILY_FILE, {
            "daily": settings.get("daily", {}),
            "last_daily_sent": settings.get("last_daily_sent", {})
        })

def save_warnings():
    with file_lock:
        atomic_save(WARNINGS_FILE, warnings_db)

def save_moderation_log():
    with file_lock:
        atomic_save(MOD_LOG_FILE, moderation_log[-500:])

load_users_from_file()

ZYNMART_PROMPT = """أنت مساعد AI موثوق داخل ZYNMART وبيئة Pi Network.

الأولوية:
1. الدقة والصدق.
2. لا تخترع معلومات أو أسعارًا أو أخبارًا.
3. إذا كانت المعلومة حديثة أو قابلة للتغير، اعتمد فقط على أدلة/مصادر حديثة متاحة في السياق.
4. إذا لم تستطع التحقق، قل بوضوح: «لا أستطيع التحقق من هذه المعلومة حاليًا».
5. لا تحوّل التخمين إلى حقيقة.
6. عند وجود تعارض بين المصادر، اذكر التعارض ولا تختار رقمًا عشوائيًا.
7. لا تعتبر أي معلومة داخل هذا الـprompt وحدها دليلًا حديثًا إذا كان السؤال عن واقع متغير.
8. ZYNMART وPi Network موضوعان مهمان، لكن يمكنك الإجابة عن الأسئلة العامة أيضًا.
9. لا تكرر التفاصيل التقنية القديمة بلا حاجة.
10. ابدأ بإجابة واضحة ومباشرة، ويمكن أن تضيف تحية أو خاتمة قصيرة عند ملاءمتها.
11. عند استخدام نتائج البحث، اعتبرها أدلة مرتبطة بنطاق البحث فقط، ولا تساوِ بين مصدر سوق أو تجميع أسعار وبين مصدر رسمي يثبت حالة KYB أو أي صفة رسمية.
12. إذا كانت الأدلة غير كافية أو متعارضة، اذكر ذلك صراحة ولا تستنتج معلومة غير مثبتة.
"""

def is_allowed_url(url):
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
        return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False

def sanitize_urls(text):
    if not text:
        return text
    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text()
    urls = re.findall(r'https?://[^\s<>"\']+', clean_text)
    for url in urls:
        if not is_allowed_url(url.rstrip(".,!?)]}")):
            clean_text = clean_text.replace(url, "")
    clean_text = clean_text.replace("✅ تمت المهمة", "").replace("تمت المهمة", "").strip()
    return clean_text

def telegram(method, payload=None, timeout=8):
    if not BOT_TOKEN:
        return None
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload or {},
            timeout=timeout
        )
        if r.status_code == 200:
            return r.json()
        print(f"Telegram {method}: {r.status_code} {r.text[:300]}")
    except Exception as e:
        print(f"Telegram Error {method}: {e}")
    return None

def send_message(chat_id, text, reply_to=None, reply_markup=None):
    payload = {"chat_id": chat_id, "text": str(text)[:4096]}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram("sendMessage", payload)

def get_chat_member(chat_id, user_id):
    result = telegram("getChatMember", {"chat_id": chat_id, "user_id": user_id})
    return result.get("result") if result and result.get("ok") else None

def is_moderator(chat_id, user_id):
    key = (str(chat_id), int(user_id))
    now = time.time()
    cached = moderation_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    member = get_chat_member(chat_id, user_id)
    status = bool(member and member.get("status") in ("creator", "administrator"))
    moderation_cache[key] = (now + 300, status)
    return status

def remember_user(msg):
    global known_users
    u = msg.get("from", {})
    uid = u.get("id")
    if not uid:
        return
    key = str(uid)
    old = known_users.get(key, {})
    known_users[key] = {
        "id": uid,
        "username": u.get("username", old.get("username", "")),
        "first_name": u.get("first_name", old.get("first_name", "")),
        "last_name": u.get("last_name", old.get("last_name", "")),
        "last_chat_id": msg.get("chat", {}).get("id", old.get("last_chat_id")),
        "last_seen": datetime.now(ZoneInfo("Africa/Tunis")).isoformat()
    }
    # Keep users.json current, but only for actual messages.
    save_users_to_file()

def search_official(query):
    """Search with source scoping for sensitive/current Pi and ZYNMART facts.
    General questions can still use normal web search.
    """
    if not TAVILY_API_KEY:
        return ""

    low = (query or "").lower()
    include_domains = []

    # For Pi/ZYNMART current facts, prefer known project/market domains.
    # This does not claim that a market API proves KYB status.
    is_pi = any(x in low for x in ["pi network", "pi network", "باي نتورك", "شبكة باي", "باي"] )
    is_zyn = any(x in low for x in ["zynmart", "zyn", "زين مارت"])

    if is_pi:
        include_domains = [
            "minepi.com", "coingecko.com", "okx.com", "bitget.com",
            "gate.io", "mexc.com", "pionex.com", "onramp.money",
            "onramper.com", "zypto.com", "lbank.com", "transfi.com",
            "banxa.com"
        ]
    elif is_zyn:
        include_domains = [
            "zynmartpi.github.io", "zynmart3401.pinet.com", "x.com"
        ]

    try:
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 4
        }
        if include_domains:
            payload["include_domains"] = include_domains

        res = requests.post("https://api.tavily.com/search", json=payload, timeout=6)
        if res.status_code == 200:
            results = res.json().get("results", [])
            evidence = []
            for r in results:
                url = r.get("url", "")
                title = r.get("title", "")
                content = r.get("content", "")
                evidence.append(
                    f"المصدر: {url}\nالعنوان: {title}\nالمقتطف: {content[:350]}"
                )
            return "\n\n".join(evidence)
        print(f"Search HTTP {res.status_code}: {res.text[:300]}")
    except Exception as e:
        print(f"Search Error: {e}")
    return ""

def get_latest_news():
    try:
        r = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            clean = soup.get_text(separator=" ", strip=True)
            return "محتوى صفحة أخبار ZYNMART (غير كافٍ وحده لإثبات كل ادعاء): " + clean[:700]
    except Exception:
        pass
    return ""

def get_json(url, params=None, timeout=5):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Market Fetch Error: {e}")
    return None

def fetch_pi_prices():
    sources = []

    # CoinGecko aggregator
    data = get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": "pi-network", "vs_currencies": "usd"}
    )
    try:
        p = float(data["pi-network"]["usd"])
        if p > 0:
            sources.append(("CoinGecko", p))
    except Exception:
        pass

    # OKX
    data = get_json("https://www.okx.com/api/v5/market/ticker", {"instId": "PI-USDT"})
    try:
        p = float(data["data"][0]["last"])
        if p > 0:
            sources.append(("OKX", p))
    except Exception:
        pass

    # Bitget
    data = get_json(
        "https://api.bitget.com/api/v2/spot/market/tickers",
        {"symbol": "PIUSDT"}
    )
    try:
        p = float(data["data"][0]["lastPr"])
        if p > 0:
            sources.append(("Bitget", p))
    except Exception:
        pass

    # Gate
    data = get_json(
        "https://api.gateio.ws/api/v4/spot/tickers",
        {"currency_pair": "PI_USDT"}
    )
    try:
        p = float(data[0]["last"])
        if p > 0:
            sources.append(("Gate", p))
    except Exception:
        pass

    # MEXC
    data = get_json(
        "https://api.mexc.com/api/v3/ticker/price",
        {"symbol": "PIUSDT"}
    )
    try:
        p = float(data["price"])
        if p > 0:
            sources.append(("MEXC", p))
    except Exception:
        pass

    return sources

def median(values):
    vals = sorted(values)
    n = len(vals)
    if not n:
        return None
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2

def format_pi_price():
    sources = fetch_pi_prices()
    if not sources:
        return "⚠️ لا أستطيع التحقق من سعر Pi حاليًا: لم تصلني بيانات صالحة من مصادر السوق المتاحة."

    prices = [p for _, p in sources]
    med = median(prices)
    low = min(prices)
    high = max(prices)
    spread = ((high - low) / med * 100) if med else 0
    now = datetime.now(ZoneInfo("Africa/Tunis")).strftime("%Y-%m-%d %H:%M:%S")

    lines = [f"📊 سعر Pi — آخر تحقق: {now} بتوقيت تونس"]
    for name, price in sources:
        lines.append(f"• {name}: ${price:.8f}".rstrip("0").rstrip("."))
    lines.append(f"• الوسيط بين المصادر: ${med:.8f}".rstrip("0").rstrip("."))
    lines.append(f"• فرق أعلى/أدنى مصدر: {spread:.2f}%")

    if len(sources) < 3:
        lines.append("⚠️ عدد المصادر المتاحة أقل من 3، لذلك لا أعتبر النتيجة تأكيدًا قويًا.")
    elif spread >= 5:
        lines.append("⚠️ يوجد اختلاف ملحوظ بين المصادر؛ تعامل مع السعر بحذر.")
    else:
        lines.append("✅ المصادر المتاحة متقاربة نسبيًا.")

    return "\n".join(lines)

def needs_fresh_search(text):
    low = text.lower()
    terms = [
        "الآن", "حاليا", "حاليًا", "اليوم", "آخر", "اخر", "مستجد", "خبر",
        "أخبار", "اخبار", "السعر", "سعر", "price", "latest", "today",
        "current", "news", "update", "من هو الرئيس الحالي", "رئيس حالي"
    ]
    return any(x in low for x in terms)

def fetch_real_evidence(user_message):
    low = user_message.lower()
    if any(k in low for k in ["pi", "باي", "باى"]) and any(
        k in low for k in ["سعر", "price", "usd", "دولار", "كم", "القيمة"]
    ):
        return format_pi_price()
    return ""

def get_gemini_response(user_message, user_name="", search_context=""):
    if not GEMINI_API_KEYS:
        return None

    evidence = fetch_real_evidence(user_message)
    news = get_latest_news() if ("zynmart" in user_message.lower() or "zyn" in user_message.lower()) else ""
    context = []
    if evidence:
        context.append("[بيانات سوق حية/أدلة]\n" + evidence)
    if search_context:
        context.append("[نتائج بحث حديثة]\n" + search_context[:1800])
    if news:
        context.append("[صفحة ZYNMART]\n" + news)

    full_prompt = (
        ZYNMART_PROMPT
        + "\nإذا لم يوجد دليل كافٍ، صرّح بعدم القدرة على التحقق.\n"
        + ("\n\n".join(context) if context else "[لا توجد أدلة خارجية إضافية]")
        + f"\n\nالمستخدم ({user_name}): {user_message}"
    )

    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    for k in GEMINI_API_KEYS:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + k
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=12)
            if res.status_code == 200:
                parts = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts:
                    txt = parts[0].get("text", "")
                    if txt:
                        return sanitize_urls(txt)
        except Exception as e:
            print(f"Gemini Exception: {e}")
    return None

def get_hermes_response(user_message, user_name="", search_context=""):
    if not HERMES_API_KEY:
        return None
    try:
        evidence = fetch_real_evidence(user_message)
        news = get_latest_news() if ("zynmart" in user_message.lower() or "zyn" in user_message.lower()) else ""
        context = []
        if evidence:
            context.append("[بيانات/أدلة]\n" + evidence)
        if search_context:
            context.append("[نتائج البحث]\n" + search_context[:1500])
        if news:
            context.append("[صفحة ZYNMART]\n" + news)

        system_prompt = (
            ZYNMART_PROMPT
            + "\n"
            + "\n\n".join(context)
            + "\nلا تختلق أي معلومة غير مدعومة."
        )
        payload = {
            "model": "nousresearch/hermes-3-llama-3.1-405b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_name}: {user_message}"}
            ],
            "temperature": 0.3,
            "max_tokens": 700
        }
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": "Bearer " + HERMES_API_KEY,
                "Content-Type": "application/json"
            },
            timeout=12
        )
        if res.status_code == 200:
            txt = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if txt:
                return sanitize_urls(txt)
    except Exception as e:
        print(f"Hermes Exception: {e}")
    return None

def get_ai_response(user_message, user_name="", search_context=""):
    res = get_gemini_response(user_message, user_name, search_context)
    if res:
        return res
    res_hermes = get_hermes_response(user_message, user_name, search_context)
    if res_hermes:
        return res_hermes
    return sanitize_urls(
        "⚠️ لم أتمكن من الوصول إلى نموذج الذكاء الاصطناعي أو مصدر تحقق مناسب حاليًا، لذلك لن أخمّن الإجابة."
    )

def is_clear_question(text):
    t = text.strip()
    if len(t) < 8 or len(t) > 800:
        return False
    low = t.lower()
    if any(x in low for x in ["😂", "🤣", "❤️", "❤", "هههه", "ههههه", "صباح الخير", "مساء الخير", "سلام"]):
        return False
    if "?" in t or "؟" in t:
        return True
    starters = [
        "شنو", "شنوة", "شنوا", "كيف", "لماذا", "علاش", "هل ", "ما هو", "ما هي",
        "متى", "أين", "وين", "كم ", "من هو", "من هي", "شنوّة", "عطيني", "اشرح",
        "فسر", "ما معنى", "what ", "how ", "why ", "when ", "where ", "who ",
        "which ", "can ", "is ", "are ", "best "
    ]
    return any(low.startswith(x) for x in starters)

def extract_target(text):
    m = re.search(r'@([A-Za-z0-9_]{3,32})', text)
    return m.group(1) if m else None

def find_user_by_username(username):
    if not username:
        return None
    wanted = username.lower().lstrip("@")
    for uid, u in known_users.items():
        if str(u.get("username", "")).lower().lstrip("@") == wanted:
            return int(uid)
    return None

def log_action(chat_id, admin_id, action, target_id=None, details=""):
    moderation_log.append({
        "time": datetime.now(ZoneInfo("Africa/Tunis")).isoformat(),
        "chat_id": chat_id,
        "admin_id": admin_id,
        "action": action,
        "target_id": target_id,
        "details": details
    })
    save_moderation_log()

def target_is_protected(chat_id, target_id):
    return target_id in ADMIN_IDS or is_moderator(chat_id, target_id)

def perform_restrict(chat_id, user_id, until_date):
    return telegram("restrictChatMember", {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": {
            "can_send_messages": False,
            "can_send_audios": False,
            "can_send_documents": False,
            "can_send_photos": False,
            "can_send_videos": False,
            "can_send_video_notes": False,
            "can_send_voice_notes": False,
            "can_send_polls": False,
            "can_send_other_messages": False,
            "can_add_web_page_previews": False,
            "can_change_info": False,
            "can_invite_users": False,
            "can_pin_messages": False
        },
        "until_date": int(until_date)
    })

def unmute_user(chat_id, user_id):
    return telegram("restrictChatMember", {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": {
            "can_send_messages": True,
            "can_send_audios": True,
            "can_send_documents": True,
            "can_send_photos": True,
            "can_send_videos": True,
            "can_send_video_notes": True,
            "can_send_voice_notes": True,
            "can_send_polls": True,
            "can_send_other_messages": True,
            "can_add_web_page_previews": True,
            "can_change_info": False,
            "can_invite_users": True,
            "can_pin_messages": False
        }
    })

def ban_user(chat_id, user_id):
    return telegram("banChatMember", {"chat_id": chat_id, "user_id": user_id})

def unban_user(chat_id, user_id):
    return telegram("unbanChatMember", {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True})

def delete_message(chat_id, message_id):
    return telegram("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

def add_warning(chat_id, user_id, reason=""):
    key = f"{chat_id}:{user_id}"
    item = warnings_db.get(key, {"count": 0, "stage": 0, "history": []})
    item.setdefault("history", [])
    item["count"] = int(item.get("count", 0)) + 1
    item["history"].append({
        "time": datetime.now(ZoneInfo("Africa/Tunis")).isoformat(),
        "reason": reason
    })

    action = "warning"
    stage = int(item.get("stage", 0))
    now = datetime.now(ZoneInfo("Africa/Tunis"))

    if item["count"] >= 3:
        if stage == 0:
            until = now + timedelta(hours=24)
            res = perform_restrict(chat_id, user_id, until.timestamp())
            if res and res.get("ok"):
                item["stage"] = 1
                item["count"] = 0
                item["muted_until"] = until.isoformat()
                item["manual_unmute"] = False
                action = "auto_mute_24h"
        elif stage == 1:
            until = now + timedelta(days=7)
            res = perform_restrict(chat_id, user_id, until.timestamp())
            if res and res.get("ok"):
                item["stage"] = 2
                item["count"] = 0
                item["muted_until"] = until.isoformat()
                item["stage_until"] = until.isoformat()
                item["manual_unmute"] = False
                action = "auto_mute_7d"
        else:
            # Stage 2 remains until the 7-day period is over.
            item["count"] = 0

    warnings_db[key] = item
    save_warnings()
    return action, item

def reset_warnings(chat_id, user_id):
    key = f"{chat_id}:{user_id}"
    warnings_db.pop(key, None)
    save_warnings()

def get_warning_info(chat_id, user_id):
    return warnings_db.get(f"{chat_id}:{user_id}", {"count": 0, "stage": 0, "history": []})

def manual_unmute(chat_id, user_id):
    res = unmute_user(chat_id, user_id)
    if res and res.get("ok"):
        key = f"{chat_id}:{user_id}"
        item = warnings_db.get(key, {})
        item["manual_unmute"] = True
        item["muted_until"] = None
        warnings_db[key] = item
        save_warnings()
    return res

def auto_unmute_due():
    now = datetime.now(ZoneInfo("Africa/Tunis"))
    changed = False

    for key, item in list(warnings_db.items()):
        # key format: chat_id:user_id
        try:
            chat_id, user_id = key.split(":", 1)
            user_id = int(user_id)
        except Exception:
            continue

        muted_until = item.get("muted_until")
        if muted_until:
            try:
                if datetime.fromisoformat(muted_until) <= now:
                    item["muted_until"] = None
                    changed = True
            except Exception:
                pass

        # After the 7-day escalation period, the warning cycle starts from zero.
        stage_until = item.get("stage_until")
        if int(item.get("stage", 0)) == 2 and stage_until:
            try:
                if datetime.fromisoformat(stage_until) <= now:
                    item["stage"] = 0
                    item["count"] = 0
                    item["stage_until"] = None
                    item["manual_unmute"] = False
                    changed = True
            except Exception:
                pass

    if changed:
        save_warnings()

def auto_moderation_reason(text):
    low = text.lower()
    if re.search(r'(https?://|www\.)', low):
        risky = ["login", "verify", "wallet", "seed", "recovery", "claim", "airdrop", "free pi", "password"]
        if any(x in low for x in risky):
            return "رابط قد يكون احتياليًا/تصيدًا"
    scam = ["double your", "send first", "give me your", "seed phrase", "private key", "مفتاحك الخاص", "عبارة الاسترداد", "ضاعف"]
    if any(x in low for x in scam):
        return "محتوى احتيالي أو طلب بيانات حساسة"
    insults = ["fuck you", "idiot", "stupid", "غبي", "حمار", "كلب", "سخيف"]
    if any(x in low for x in insults):
        return "إهانة مباشرة"
    return ""

def handle_auto_moderation(msg):
    if not settings.get("moderation_enabled", True):
        return False
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id")
    text = msg.get("text", "").strip()
    if not chat_id or not user_id or not text:
        return False
    if user_id in ADMIN_IDS or is_moderator(chat_id, user_id) or user_id in manual_exceptions:
        return False

    reason = auto_moderation_reason(text)

    # Repeated identical messages
    key = (chat_id, user_id)
    previous = last_message_cache.get(key)
    now = time.time()
    if previous and previous[0] > now - 20 and previous[1].strip().lower() == text.lower():
        reason = reason or "تكرار الرسالة بشكل مزعج"
    last_message_cache[key] = (now, text)

    if not reason:
        return False

    if settings.get("moderation_level") == "silent":
        log_action(chat_id, 0, "silent_detection", user_id, reason)
        return False

    # Deterministic rules only; AI has no punishment authority.
    delete_message(chat_id, msg.get("message_id"))
    action, _ = add_warning(chat_id, user_id, reason)
    log_action(chat_id, 0, action, user_id, reason)
    return True

def schedule_question(chat_id, msg):
    message_id = msg.get("message_id")
    key = (str(chat_id), int(message_id))
    delay = int(settings.get("question_delay", 60))

    def worker():
        time.sleep(delay)
        item = pending_questions.pop(key, None)
        if not item:
            return
        # If a moderator answered directly, webhook marks answered=True.
        if item.get("answered"):
            return
        text = item["text"]
        username = item["user_name"]
        search_context = search_official(text) if needs_fresh_search(text) else ""
        reply = get_ai_response(text, username, search_context)
        send_message(chat_id, reply, reply_to=message_id)

    pending_questions[key] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text_without_bot_mention(msg.get("text", "")),
        "user_name": msg.get("from", {}).get("first_name", ""),
        "answered": False,
        "created": time.time()
    }
    threading.Thread(target=worker, daemon=True).start()

def text_without_bot_mention(text):
    clean = re.sub(r'@?[A-Za-z0-9_]*zynmart_ai_bot[A-Za-z0-9_]*', '', text, flags=re.I)
    return re.sub(r'\s+', ' ', clean).strip()

def mark_pending_answered(chat_id, reply_to_message_id):
    for item in pending_questions.values():
        if item.get("chat_id") == chat_id and item.get("message_id") == reply_to_message_id:
            item["answered"] = True

def admin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "💬 دردشة خاصة", "callback_data": "admin_chat"}],
            [{"text": "📢 البث", "callback_data": "admin_broadcast"},
             {"text": "⚙️ الإعدادات", "callback_data": "admin_settings"}],
            [{"text": "🛡️ الإشراف", "callback_data": "admin_moderation"},
             {"text": "🕒 الانتظار", "callback_data": "admin_delay"}],
            [{"text": "📅 الرسائل اليومية", "callback_data": "admin_daily"}],
            [{"text": "📊 سعر Pi", "callback_data": "admin_pi"},
             {"text": "📋 السجل", "callback_data": "admin_log"}],
            [{"text": "🔙 رجوع", "callback_data": "admin_back"}]
        ]
    }

def show_admin_panel(chat_id):
    return telegram("sendMessage", {
        "chat_id": chat_id,
        "text": "🛠️ لوحة تحكم ZYNMART\nاختر العملية المطلوبة:",
        "reply_markup": admin_keyboard()
    })

def settings_keyboard():
    delay = settings.get("question_delay", 60)
    mod = "🟢" if settings.get("moderation_enabled", True) else "🔴"
    daily = "🟢" if settings.get("daily_enabled", True) else "🔴"
    return {
        "inline_keyboard": [
            [{"text": f"🕒 الانتظار: {delay}ث", "callback_data": "admin_delay"}],
            [{"text": f"{mod} الإشراف", "callback_data": "toggle_mod"},
             {"text": f"{daily} اليوميات", "callback_data": "toggle_daily"}],
            [{"text": "🔙 لوحة التحكم", "callback_data": "admin_back"}]
        ]
    }

def moderation_keyboard():
    mode = settings.get("moderation_level", "medium")
    return {
        "inline_keyboard": [
            [{"text": "🟢 متوسط", "callback_data": "mod_medium"},
             {"text": "🔇 مراقبة صامتة", "callback_data": "mod_silent"}],
            [{"text": "📋 سجل", "callback_data": "admin_log"},
             {"text": "🧩 الاستثناءات", "callback_data": "admin_exceptions"}],
            [{"text": f"الحالة: {mode}", "callback_data": "admin_moderation"}],
            [{"text": "🔙 لوحة التحكم", "callback_data": "admin_back"}]
        ]
    }

def daily_keyboard():
    d = settings.get("daily", {})
    return {
        "inline_keyboard": [
            [{"text": "🟢 تشغيل", "callback_data": "daily_on"},
             {"text": "🔴 إيقاف", "callback_data": "daily_off"}],
            [{"text": "🌅 الصباح", "callback_data": "daily_morning"},
             {"text": "🌞 الظهر", "callback_data": "daily_midday"},
             {"text": "🌙 المساء", "callback_data": "daily_evening"}],
            [{"text": "✏️ تعديل الصباح", "callback_data": "edit_daily_morning"},
             {"text": "✏️ تعديل الظهر", "callback_data": "edit_daily_midday"}],
            [{"text": "✏️ تعديل المساء", "callback_data": "edit_daily_evening"}],
            [{"text": "🔙 لوحة التحكم", "callback_data": "admin_back"}]
        ]
    }

def daily_item_text(name):
    item = settings.get("daily", {}).get(name, {})
    labels = {"morning": "🌅 الصباح", "midday": "🌞 الظهر", "evening": "🌙 المساء"}
    return f"{labels.get(name,name)}\nالوقت: {item.get('time','')}\nالنص: {item.get('text','')}"

def process_admin_text(chat_id, user_id, text):
    mode = admin_modes.get(user_id)

    if text in ("لوحة التحكم", "لوحة", "/admin", "admin"):
        admin_modes.pop(user_id, None)
        show_admin_panel(chat_id)
        return True

    if text == "رجوع":
        admin_modes.pop(user_id, None)
        show_admin_panel(chat_id)
        return True

    if mode == "chat":
        search_context = search_official(text) if needs_fresh_search(text) else ""
        send_message(chat_id, get_ai_response(text, "", search_context))
        return True

    if mode == "broadcast_topic":
        target_group = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
        if target_group:
            search_results = search_official(text)
            creative_order = f"اكتب منشور ابداعي كامل ومحفز وجاهز للنشر عن: {text}"
            broadcast_reply = get_ai_response(creative_order, "", search_context=search_results)
            send_message(target_group, broadcast_reply)
            send_message(chat_id, "✅ تم النشر في المجموعة بنجاح!")
        else:
            send_message(chat_id, "⚠️ لم يتم التعرف على المجموعة بعد.")
        admin_modes.pop(user_id, None)
        return True

    if isinstance(mode, str) and mode.startswith("daily_text:"):
        name = mode.split(":", 1)[1]
        if name in settings.get("daily", {}):
            settings["daily"][name]["text"] = text[:1000]
            save_settings()
            save_daily_data()
            admin_modes.pop(user_id, None)
            send_message(chat_id, "✅ تم تحديث النص.\n\n" + daily_item_text(name),
                         )
        return True

    if isinstance(mode, str) and mode.startswith("daily_time:"):
        name = mode.split(":", 1)[1]
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            settings["daily"][name]["time"] = text
            save_settings()
            save_daily_data()
            admin_modes.pop(user_id, None)
            send_message(chat_id, "✅ تم تحديث الوقت.\n\n" + daily_item_text(name))
        else:
            send_message(chat_id, "⚠️ اكتب الوقت بهذا الشكل فقط: HH:MM\nمثال: 08:30")
        return True

    if isinstance(mode, str) and mode.startswith("exception_add"):
        username = text.strip().lstrip("@")
        target_id = find_user_by_username(username)
        if not target_id:
            send_message(chat_id, "⚠️ المستخدم غير موجود في users.json. لن أخمّن هويته.")
        else:
            manual_exceptions.add(target_id)
            settings["manual_exceptions"] = sorted(manual_exceptions)
            save_settings()
            send_message(chat_id, f"✅ تمت إضافة @{username} إلى الاستثناءات.")
        admin_modes.pop(user_id, None)
        return True

    if isinstance(mode, str) and mode.startswith("exception_remove"):
        username = text.strip().lstrip("@")
        target_id = find_user_by_username(username)
        if target_id is not None:
            manual_exceptions.discard(target_id)
            settings["manual_exceptions"] = sorted(manual_exceptions)
            save_settings()
            send_message(chat_id, f"✅ تمت إزالة @{username} من الاستثناءات.")
        else:
            send_message(chat_id, "⚠️ المستخدم غير موجود في users.json.")
        admin_modes.pop(user_id, None)
        return True

    return False

def parse_moderation_command(text):
    patterns = [
        ("ban", r"^(?:حظر)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("kick", r"^(?:طرد)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("mute", r"^(?:كتم)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("unmute", r"^(?:فك الكتم)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("warn", r"^(?:إنذار|نبه)\s+(@[A-Za-z0-9_]{3,32})(?:\s+(.+))?$"),
        ("warnings", r"^(?:سجل)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("reset", r"^(?:تصفير)\s+(@[A-Za-z0-9_]{3,32})$"),
        ("unban", r"^(?:رفع الحظر)\s+(@[A-Za-z0-9_]{3,32})$")
    ]
    for action, pattern in patterns:
        m = re.match(pattern, text.strip(), re.I)
        if m:
            return action, m.groups()
    return None, None

pending_moderation = {}

def execute_moderation_command(chat_id, admin_id, text):
    action, groups = parse_moderation_command(text)
    if not action:
        return False
    if chat_id is None:
        send_message(admin_id, "⚠️ لا توجد مجموعة معروفة لتنفيذ الأمر.")
        return True

    username = groups[0]
    target_id = find_user_by_username(username)
    if not target_id:
        send_message(chat_id, "⚠️ لم أجد هذا المستخدم في users.json. لن أخمّن هويته.")
        return True
    if target_is_protected(chat_id, target_id):
        send_message(chat_id, "⚠️ لا يمكن تنفيذ إجراء يدوي على أدمن أو مشرف.")
        return True

    if action in ("ban", "kick", "mute"):
        key = f"{admin_id}:{chat_id}:{target_id}:{action}"
        pending_moderation[key] = {"created": time.time(), "chat_id": chat_id,
                                   "admin_id": admin_id, "target_id": target_id,
                                   "username": username, "action": action,
                                   "reason": groups[1] if len(groups) > 1 else ""}
        labels = {"ban": "الحظر", "kick": "الطرد", "mute": "الكتم 24 ساعة"}
        telegram("sendMessage", {
            "chat_id": chat_id,
            "text": f"⚠️ تأكيد الإجراء على @{username}: {labels[action]}؟",
            "reply_markup": {"inline_keyboard": [
                [{"text": "✅ تأكيد", "callback_data": "confirm:" + key},
                 {"text": "❌ إلغاء", "callback_data": "cancel:" + key}]
            ]}
        })
        return True

    if action == "unban":
        res = unban_user(chat_id, target_id)
        ok = bool(res and res.get("ok"))
        send_message(chat_id, "✅ تم رفع الحظر." if ok else "⚠️ تعذر رفع الحظر.")
        if ok: log_action(chat_id, admin_id, "unban", target_id)
    elif action == "unmute":
        res = manual_unmute(chat_id, target_id)
        ok = bool(res and res.get("ok"))
        send_message(chat_id, "✅ تم فك الكتم." if ok else "⚠️ تعذر فك الكتم.")
        if ok: log_action(chat_id, admin_id, "unmute", target_id)
    elif action == "warn":
        reason = groups[1] or "بدون سبب محدد"
        result, item = add_warning(chat_id, target_id, reason)
        if result.startswith("auto_mute"):
            msg = "⚠️ اكتمل حد 3 إنذارات وتم تطبيق " + ("كتم 24 ساعة." if result == "auto_mute_24h" else "كتم أسبوع.")
        else:
            msg = f"⚠️ تم تسجيل الإنذار. الإنذارات الحالية: {item.get('count', 0)}."
        send_message(chat_id, msg)
        log_action(chat_id, admin_id, result, target_id, reason)
    elif action == "warnings":
        item = get_warning_info(chat_id, target_id)
        history = item.get("history", [])[-5:]
        lines = [f"📋 سجل @{username}",
                 f"الإنذارات الحالية: {item.get('count', 0)}",
                 f"المرحلة: {item.get('stage', 0)}",
                 f"الكتم حتى: {item.get('muted_until') or 'لا يوجد'}"]
        if history:
            lines.append("آخر الإنذارات:")
            for h in history:
                lines.append(f"• {h.get('time','')} — {h.get('reason','')}")
        send_message(chat_id, "\n".join(lines))
    elif action == "reset":
        reset_warnings(chat_id, target_id)
        send_message(chat_id, "✅ تم تصفير سجل الإنذارات.")
        log_action(chat_id, admin_id, "reset_warnings", target_id)
    return True

def confirm_moderation(key, approved):
    item = pending_moderation.pop(key, None)
    if not item:
        return "⚠️ انتهت صلاحية التأكيد أو لم يعد موجودًا."
    if time.time() - item["created"] > 120:
        return "⚠️ انتهت صلاحية التأكيد."
    if not approved:
        return "❌ تم إلغاء الإجراء."

    chat_id = item["chat_id"]
    admin_id = item["admin_id"]
    target_id = item["target_id"]
    action = item["action"]
    username = item["username"]

    if target_is_protected(chat_id, target_id):
        return "⚠️ المستخدم أصبح أدمن/مشرفًا؛ تم رفض الإجراء."

    if action == "ban":
        res = ban_user(chat_id, target_id)
        ok = bool(res and res.get("ok"))
        if ok: log_action(chat_id, admin_id, "ban", target_id)
        return "✅ تم الحظر." if ok else "⚠️ تعذر تنفيذ الحظر."
    if action == "kick":
        res = ban_user(chat_id, target_id)
        ok = bool(res and res.get("ok"))
        if ok:
            unban_user(chat_id, target_id)
            log_action(chat_id, admin_id, "kick", target_id)
        return "✅ تم الطرد." if ok else "⚠️ تعذر تنفيذ الطرد."
    if action == "mute":
        until = datetime.now(ZoneInfo("Africa/Tunis")) + timedelta(hours=24)
        res = perform_restrict(chat_id, target_id, until.timestamp())
        ok = bool(res and res.get("ok"))
        if ok:
            item2 = get_warning_info(chat_id, target_id)
            item2["manual_unmute"] = False
            item2["muted_until"] = until.isoformat()
            warnings_db[f"{chat_id}:{target_id}"] = item2
            save_warnings()
            log_action(chat_id, admin_id, "mute_24h", target_id)
        return "✅ تم الكتم 24 ساعة." if ok else "⚠️ تعذر تنفيذ الكتم."
    return "⚠️ إجراء غير معروف."

def ensure_background_services():
    """Start one scheduler thread per application process.
    Called from the first HTTP request so it also works under Gunicorn/Render.
    """
    global background_services_started
    if background_services_started:
        return
    with background_services_lock:
        if background_services_started:
            return
        threading.Thread(target=daily_scheduler, daemon=True, name="zynmart-daily-scheduler").start()
        background_services_started = True
        print("Background scheduler started.")


def daily_scheduler():
    tz = ZoneInfo("Africa/Tunis")
    while True:
        try:
            auto_unmute_due()
            if settings.get("daily_enabled", True) and (active_group_chat_id or DEFAULT_GROUP_CHAT_ID):
                now = datetime.now(tz)
                day_key = now.strftime("%Y-%m-%d")
                for name, item in settings.get("daily", {}).items():
                    if not isinstance(item, dict):
                        continue
                    hhmm = item.get("time", "")
                    if hhmm != now.strftime("%H:%M"):
                        continue
                    last = settings.get("last_daily_sent", {}).get(name)
                    if last == day_key:
                        continue
                    target = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
                    result = send_message(target, item.get("text", ""))
                    if result and result.get("ok"):
                        settings.setdefault("last_daily_sent", {})[name] = day_key
                        save_settings()
                        save_daily_data()
        except Exception as e:
            print(f"Scheduler Error: {e}")
        time.sleep(30)

def handle_callback(data):
    query = data.get("callback_query", {})
    if not query:
        return
    user_id = query.get("from", {}).get("id")
    chat_id = query.get("message", {}).get("chat", {}).get("id")
    callback_id = query.get("id")
    action = query.get("data", "")

    telegram("answerCallbackQuery", {"callback_query_id": callback_id})

    if user_id not in ADMIN_IDS:
        return

    if action.startswith("confirm:"):
        key = action.split(":", 1)[1]
        result = confirm_moderation(key, True)
        send_message(chat_id, result)
        return
    if action.startswith("cancel:"):
        key = action.split(":", 1)[1]
        result = confirm_moderation(key, False)
        send_message(chat_id, result)
        return

    if action == "admin_chat":
        admin_modes[user_id] = "chat"
        send_message(chat_id, "💬 دخلت وضع الدردشة الخاصة.\nاكتب سؤالك مباشرة.\nاكتب «رجوع» للعودة إلى لوحة التحكم.")
    elif action == "admin_broadcast":
        admin_modes[user_id] = "broadcast_topic"
        send_message(chat_id, "📢 أرسل موضوع المنشور الإبداعي.\nللعودة اكتب «رجوع».")
    elif action == "admin_settings":
        telegram("sendMessage", {"chat_id": chat_id, "text": "⚙️ الإعدادات", "reply_markup": settings_keyboard()})
    elif action == "admin_moderation":
        telegram("sendMessage", {"chat_id": chat_id, "text": "🛡️ الإشراف", "reply_markup": moderation_keyboard()})
    elif action == "admin_delay":
        telegram("sendMessage", {"chat_id": chat_id, "text": "اختر مدة انتظار السؤال:", "reply_markup": {
            "inline_keyboard": [
                [{"text": "30ث", "callback_data": "delay_30"},
                 {"text": "60ث", "callback_data": "delay_60"},
                 {"text": "90ث", "callback_data": "delay_90"}],
                [{"text": "120ث", "callback_data": "delay_120"},
                 {"text": "300ث", "callback_data": "delay_300"}],
                [{"text": "🔙 لوحة التحكم", "callback_data": "admin_back"}]
            ]
        }})
    elif action.startswith("delay_"):
        settings["question_delay"] = int(action.split("_")[1])
        save_settings()
        send_message(chat_id, f"✅ تم ضبط انتظار الأسئلة على {settings['question_delay']} ثانية.")
    elif action == "toggle_mod":
        settings["moderation_enabled"] = not settings.get("moderation_enabled", True)
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "⚙️ الإشراف", "reply_markup": settings_keyboard()})
    elif action == "toggle_daily":
        settings["daily_enabled"] = not settings.get("daily_enabled", True)
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "⚙️ الإعدادات", "reply_markup": settings_keyboard()})
    elif action == "mod_medium":
        settings["moderation_level"] = "medium"
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "🛡️ الإشراف متوسط.", "reply_markup": moderation_keyboard()})
    elif action == "mod_silent":
        settings["moderation_level"] = "silent"
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "🔇 المراقبة الصامتة مفعلة: تسجيل الاكتشافات فقط دون عقوبة.", "reply_markup": moderation_keyboard()})
    elif action == "daily_on":
        settings["daily_enabled"] = True
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "✅ الرسائل اليومية مفعلة.", "reply_markup": daily_keyboard()})
    elif action == "daily_off":
        settings["daily_enabled"] = False
        save_settings()
        telegram("sendMessage", {"chat_id": chat_id, "text": "⏸️ الرسائل اليومية متوقفة.", "reply_markup": daily_keyboard()})
    elif action in ("daily_morning", "daily_midday", "daily_evening"):
        name = action.replace("daily_", "")
        send_message(chat_id, daily_item_text(name), reply_markup={
            "inline_keyboard": [
                [{"text": "✏️ النص", "callback_data": "edit_daily_text:" + name},
                 {"text": "🕒 الوقت", "callback_data": "edit_daily_time:" + name}],
                [{"text": "🔙 الرسائل اليومية", "callback_data": "admin_daily"}]
            ]
        })
    elif action.startswith("edit_daily_text:"):
        name = action.split(":",1)[1]
        if name in settings.get("daily", {}):
            admin_modes[user_id] = "daily_text:" + name
            send_message(chat_id, f"✏️ أرسل النص الجديد لـ {name}.\nاكتب «رجوع» للإلغاء.")
    elif action.startswith("edit_daily_time:"):
        name = action.split(":",1)[1]
        if name in settings.get("daily", {}):
            admin_modes[user_id] = "daily_time:" + name
            send_message(chat_id, f"🕒 أرسل الوقت الجديد لـ {name} بصيغة HH:MM.\nمثال: 08:30")
    elif action == "admin_exceptions":
        ex = []
        for uid in sorted(manual_exceptions):
            u = known_users.get(str(uid), {})
            ex.append("@" + u.get("username","") if u.get("username") else str(uid))
        send_message(chat_id, "🧩 الاستثناءات الحالية:\n" + ("\n".join(ex) if ex else "لا توجد."),
                     reply_markup={"inline_keyboard": [
                         [{"text":"➕ إضافة","callback_data":"exception_add"},
                          {"text":"➖ إزالة","callback_data":"exception_remove"}],
                         [{"text":"🔙 الإشراف","callback_data":"admin_moderation"}]
                     ]})
    elif action == "exception_add":
        admin_modes[user_id] = "exception_add"
        send_message(chat_id, "➕ أرسل @username لإضافته للاستثناءات.")
    elif action == "exception_remove":
        admin_modes[user_id] = "exception_remove"
        send_message(chat_id, "➖ أرسل @username لإزالته من الاستثناءات.")
    elif action == "admin_daily":
        telegram("sendMessage", {"chat_id": chat_id, "text": "📅 الرسائل اليومية", "reply_markup": daily_keyboard()})
    elif action == "admin_pi":
        send_message(chat_id, format_pi_price())
    elif action == "admin_log":
        recent = moderation_log[-10:]
        if not recent:
            send_message(chat_id, "📋 لا يوجد سجل بعد.")
        else:
            lines = ["📋 آخر عمليات الإشراف:"]
            for x in recent:
                lines.append(f"{x.get('time')} | {x.get('action')} | user={x.get('target_id')} | {x.get('details','')}")
            send_message(chat_id, "\n".join(lines))
    elif action == "admin_back":
        show_admin_panel(chat_id)

@app.route("/", methods=["GET"])
def index():
    ensure_background_services()
    return "Zynmart Bot Status: Online", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    global active_group_chat_id
    ensure_background_services()
    data = request.get_json(force=True, silent=True)

    if not data:
        return jsonify({"status": "ok"}), 200

    if "callback_query" in data:
        handle_callback(data)
        return jsonify({"status": "ok"}), 200

    if "message" not in data:
        return jsonify({"status": "ok"}), 200

    msg = data["message"]
    chat_id = msg.get("chat", {}).get("id")
    chat_type = msg.get("chat", {}).get("type", "private")
    user_id = msg.get("from", {}).get("id")
    text = msg.get("text", "").strip()
    user_name = msg.get("from", {}).get("first_name", "")

    if not chat_id or not BOT_TOKEN:
        return jsonify({"status": "ok"}), 200

    remember_user(msg)

    if chat_type in ["group", "supergroup"]:
        if active_group_chat_id != chat_id:
            active_group_chat_id = chat_id
            save_users_to_file()

        # Moderator response to a pending question: direct reply only.
        reply_to = msg.get("reply_to_message", {})
        if reply_to and user_id and is_moderator(chat_id, user_id):
            mark_pending_answered(chat_id, reply_to.get("message_id"))

        # Auto moderation first, but never for moderators/admins.
        if handle_auto_moderation(msg):
            return jsonify({"status": "ok"}), 200

        # Explicit moderation commands from admins/moderators.
        if text and (user_id in ADMIN_IDS or is_moderator(chat_id, user_id)):
            if execute_moderation_command(chat_id, user_id, text):
                return jsonify({"status": "ok"}), 200

        # Mention => answer immediately.
        low = text.lower()
        bot_handle = BOT_USERNAME.lower()
        clean_handle = bot_handle.replace("@", "")
        mentioned = bot_handle in low or clean_handle in low

        if mentioned:
            question = text_without_bot_mention(text)
            search_res = search_official(question) if needs_fresh_search(question) else ""
            reply = get_ai_response(question, user_name, search_context=search_res)
            send_message(chat_id, reply, reply_to=msg.get("message_id"))
            return jsonify({"status": "ok"}), 200

        # Clear questions without mention => wait configured delay.
        if text and is_clear_question(text):
            schedule_question(chat_id, msg)

        return jsonify({"status": "ok"}), 200

    if chat_type == "private":
        # Preserve original private protection.
        if user_id not in ADMIN_IDS:
            return jsonify({"status": "ok"}), 200

        # Original broadcast command behavior is preserved exactly.
        if text.startswith("ابدا البث") or text.startswith("ابدأ البث"):
            target_group = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
            if target_group:
                raw_cmd = text.replace("ابدا البث", "", 1).replace("ابدأ البث", "", 1).strip()

                if raw_cmd.startswith(":"):
                    broadcast_reply = sanitize_urls(raw_cmd[1:].strip())
                else:
                    search_query = raw_cmd if raw_cmd else "اخبار Pi Network و ZYNMART"
                    creative_order = f"اكتب منشور ابداعي كامل ومحفز وجاهز للنشر عن: {search_query}"
                    search_results = search_official(search_query)
                    broadcast_reply = get_ai_response(creative_order, user_name, search_context=search_results)

                send_message(target_group, broadcast_reply)
                send_message(chat_id, "✅ تم النشر في المجموعة بنجاح!")
            else:
                send_message(chat_id, "⚠️ لم يتم التعرف على المجموعة بعد.")
            return jsonify({"status": "ok"}), 200

        # Admin commands/menu modes.
        if process_admin_text(chat_id, user_id, text):
            return jsonify({"status": "ok"}), 200

        # Admin moderation commands may also be issued in private by sending them
        # only when a target group is known.
        if execute_moderation_command(active_group_chat_id or DEFAULT_GROUP_CHAT_ID, user_id, text):
            return jsonify({"status": "ok"}), 200

        # Preserve original ordinary private AI reply.
        search_res = search_official(text) if needs_fresh_search(text) else ""
        direct_reply = get_ai_response(text, user_name, search_context=search_res)
        send_message(chat_id, direct_reply)
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    ensure_background_services()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
