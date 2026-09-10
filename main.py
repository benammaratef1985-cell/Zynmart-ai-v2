import os, json, requests, threading, re, time, hmac, hashlib, html
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
GROQ_API_KEYS = []
for k, v in os.environ.items():
    if k.startswith("GROQ_API_KEY") and v:
        for x in v.split(","):
            x = x.strip()
            if x and x not in GROQ_API_KEYS:
                GROQ_API_KEYS.append(x)
groq_key_index = 0
groq_key_lock = threading.Lock()
groq_key_cooldowns = {}
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

GEMINI_API_KEYS = []
current_key_index = 0
gemini_key_lock = threading.Lock()
gemini_key_cooldowns = {}
for k, v in os.environ.items():
    if k.startswith("GEMINI_API_KEY") and v:
        for x in v.split(","):
            x = x.strip()
            if x and x not in GEMINI_API_KEYS:
                GEMINI_API_KEYS.append(x)

OWNER_ID = 7560871853  # Secret owner of the AI for ZYNMART bot only; not ZynMart ownership.
ADMIN_IDS = [OWNER_ID, 6283667477]
BOT_USERNAME = "@zynmart_ai_bot"
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://ai-for-zynmart.onrender.com/app")
WEBAPP_MENU_TEXT = os.environ.get("WEBAPP_MENU_TEXT", "📱 ZYNMART")
WEBAPP_INITDATA_MAX_AGE = int(os.environ.get("WEBAPP_INITDATA_MAX_AGE", "86400"))
webapp_menu_configured = False
webapp_menu_lock = threading.Lock()
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
    "question_delay": 30,
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
settings.setdefault("emergency_mode", False)
settings.setdefault("emergency_reason", "")
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

def telegram(method, payload=None, timeout=6):
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

        res = requests.post("https://api.tavily.com/search", json=payload, timeout=4)
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
        r = requests.get(NEWS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            clean = soup.get_text(separator=" ", strip=True)
            return "محتوى صفحة أخبار ZYNMART (غير كافٍ وحده لإثبات كل ادعاء): " + clean[:700]
    except Exception:
        pass
    return ""

def get_json(url, params=None, timeout=2.5):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Market Fetch Error: {e}")
    return None

def fetch_pi_prices():
    # Fetch all public market sources in parallel: much faster than five sequential timeouts.
    def fetch_one(name, url, params=None):
        data = get_json(url, params)
        try:
            if name == "CoinGecko":
                p = float(data["pi-network"]["usd"])
            elif name == "OKX":
                p = float(data["data"][0]["last"])
            elif name == "Bitget":
                p = float(data["data"][0]["lastPr"])
            elif name == "Gate":
                p = float(data[0]["last"])
            elif name == "MEXC":
                p = float(data["price"])
            else:
                return None
            return (name, p) if p > 0 else None
        except Exception:
            return None

    jobs = [
        ("CoinGecko", "https://api.coingecko.com/api/v3/simple/price", {"ids": "pi-network", "vs_currencies": "usd"}),
        ("OKX", "https://www.okx.com/api/v5/market/ticker", {"instId": "PI-USDT"}),
        ("Bitget", "https://api.bitget.com/api/v2/spot/market/tickers", {"symbol": "PIUSDT"}),
        ("Gate", "https://api.gateio.ws/api/v4/spot/tickers", {"currency_pair": "PI_USDT"}),
        ("MEXC", "https://api.mexc.com/api/v3/ticker/price", {"symbol": "PIUSDT"}),
    ]
    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(fetch_one, *job) for job in jobs]
        for future in futures:
            try:
                item = future.result(timeout=3)
                if item:
                    results.append(item)
            except Exception:
                pass
    return results

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

def _gemini_retry_after_seconds(res):
    """Read a useful retry delay from Gemini without exposing key data."""
    try:
        data = res.json()
        details = data.get("error", {}).get("details", [])
        for item in details:
            retry_delay = item.get("retryDelay")
            if retry_delay:
                m = re.search(r"(\d+(?:\.\d+)?)", str(retry_delay))
                if m:
                    return max(30, min(300, int(float(m.group(1))) + 5))
    except Exception:
        pass
    return 60

def _pick_gemini_key(exclude=None):
    """Pick one non-cooled key in round-robin order; never expose the key itself."""
    global current_key_index
    exclude = set(exclude or [])
    total = len(GEMINI_API_KEYS)
    if total == 0:
        return None, None

    now = time.time()
    with gemini_key_lock:
        start = current_key_index % total
        for offset in range(total):
            idx = (start + offset) % total
            if idx in exclude:
                continue
            if gemini_key_cooldowns.get(idx, 0) > now:
                continue
            current_key_index = (idx + 1) % total
            return idx, GEMINI_API_KEYS[idx]
    return None, None

def _build_ai_context(user_message, search_context=""):
    evidence = fetch_real_evidence(user_message)
    news = get_latest_news() if ("zynmart" in user_message.lower() or "zyn" in user_message.lower()) else ""
    context = []
    if evidence:
        context.append("[بيانات/أدلة]\n" + evidence)
    if search_context:
        context.append("[نتائج حديثة]\n" + search_context[:1000])
    if news:
        context.append("[ZYNMART]\n" + news[:450])
    return "\n\n".join(context) if context else "[لا توجد أدلة خارجية إضافية]"

def get_gemini_response(user_message, user_name="", search_context="", context_override=None):
    if not GEMINI_API_KEYS:
        return None
    context_text = context_override if context_override is not None else _build_ai_context(user_message, search_context)
    full_prompt = (
        ZYNMART_PROMPT
        + "\nإذا لم يوجد دليل كافٍ، صرّح بعدم القدرة على التحقق ولا تخمّن.\n"
        + context_text
        + f"\n\nالمستخدم ({user_name}): {user_message}"
    )
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    global current_key_index
    total_keys = len(GEMINI_API_KEYS)
    if total_keys == 0:
        return None
    attempted = set()
    max_attempts = 2 if total_keys > 1 else 1
    for _ in range(max_attempts):
        idx, k = _pick_gemini_key(exclude=attempted)
        if k is None:
            break
        attempted.add(idx)
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=" + k
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=7)
            if res.status_code == 200:
                parts = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts:
                    txt = parts[0].get("text", "")
                    if txt:
                        current_key_index = (idx + 1) % total_keys
                        return sanitize_urls(txt)
                return None
            if res.status_code == 429:
                retry_for = _gemini_retry_after_seconds(res)
                with gemini_key_lock:
                    gemini_key_cooldowns[idx] = time.time() + retry_for
                print(f"Gemini HTTP 429 - key index {idx}; cooldown {retry_for}s")
                continue
            if res.status_code in (401, 403):
                with gemini_key_lock:
                    gemini_key_cooldowns[idx] = time.time() + 300
                print(f"Gemini HTTP {res.status_code} - key index {idx}; cooldown 300s")
                continue
            print(f"Gemini HTTP {res.status_code} - key index {idx}")
            return None
        except Exception as e:
            # Timeout/network failure does not consume another key.
            print(f"Gemini Exception: {e} - key index {idx}")
            return None
    return None

AI_PRIVATE_FAILURE_MESSAGE = (
    "⚠️ يوجد حاليًا خلل تقني في خدمة الذكاء الاصطناعي.\n"
    "Telegram وRender يعملان بشكل طبيعي، والمشكلة تقنية في خدمة الذكاء الاصطناعي.\n"
    "لن أخمّن الإجابة حتى تعود الخدمة للعمل."
)

MENTION_AI_FAILURE_MESSAGE = (
    "⚠️ فهمت سؤالك، لكن تعذّر عليّ الحصول على إجابة موثوقة الآن.\n"
    "لن أخمّن أو أعطيك معلومة غير مؤكدة. حاول مرة أخرى بعد قليل. 🤝"
)

def _pick_groq_key(exclude=None):
    global groq_key_index
    exclude = exclude or set()
    total = len(GROQ_API_KEYS)
    if total == 0:
        return None, None
    now = time.time()
    with groq_key_lock:
        start = groq_key_index % total
        for offset in range(total):
            idx = (start + offset) % total
            if idx in exclude:
                continue
            if groq_key_cooldowns.get(idx, 0) > now:
                continue
            groq_key_index = (idx + 1) % total
            return idx, GROQ_API_KEYS[idx]
    return None, None

def get_groq_response(user_message, user_name="", search_context="", context_override=None):
    """Second AI provider. Free-tier aware: one request per key attempt; 429 cooldown follows server headers.
    Multiple keys are supported for resilience, but Groq rate limits are organization-level, so keys are NOT treated as quota multipliers.
    """
    if not GROQ_API_KEYS:
        return None
    context_text = context_override if context_override is not None else _build_ai_context(user_message, search_context)
    system_prompt = (
        ZYNMART_PROMPT
        + "\nإذا لم يوجد دليل كافٍ، صرّح بعدم القدرة على التحقق ولا تخمّن."
        + "\nأجب بالعربية المناسبة للسؤال، وكن دقيقًا ومختصرًا."
        + "\n" + context_text[:1800]
    )
    payload = {
        "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_name}: {user_message}"}
        ],
        "temperature": 0.2,
        "max_completion_tokens": 700
    }
    attempted = set()
    max_attempts = min(len(GROQ_API_KEYS), 2)
    for _ in range(max_attempts):
        idx, key = _pick_groq_key(exclude=attempted)
        if key is None:
            break
        attempted.add(idx)
        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                timeout=5
            )
            if res.status_code == 200:
                txt = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                if txt:
                    return sanitize_urls(txt)
                return None
            if res.status_code == 429:
                retry_after = 30
                try:
                    retry_after = int(float(res.headers.get("retry-after", "30")))
                except Exception:
                    pass
                with groq_key_lock:
                    groq_key_cooldowns[idx] = time.time() + max(10, min(retry_after, 3600))
                print(f"Groq HTTP 429 - key index {idx}; cooldown {retry_after}s")
                continue
            if res.status_code in (401, 403):
                with groq_key_lock:
                    groq_key_cooldowns[idx] = time.time() + 300
                print(f"Groq HTTP {res.status_code} - key index {idx}; cooldown 300s")
                continue
            print(f"Groq HTTP {res.status_code}: {res.text[:300]}")
            return None
        except Exception as e:
            print(f"Groq Exception: {e} - key index {idx}")
            return None
    return None

def get_groq_admin_agent_response(admin_id, chat_id, task):
    """Admin-only autonomous task runner using Groq local tool calling.
    The model can request only the explicitly whitelisted tools below. The caller must already be an ADMIN_ID.
    """
    if admin_id not in ADMIN_IDS or not GROQ_API_KEYS or emergency_active():
        return None
    tools = [
        {"type":"function","function":{"name":"search_web","description":"Search current public web information using the bot's existing verified search pipeline.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
        {"type":"function","function":{"name":"get_pi_status","description":"Get the bot's current Pi market/source summary.","parameters":{"type":"object","properties":{}}}},
        {"type":"function","function":{"name":"send_group_message","description":"Send a text message to the known active Telegram group. Use only when the administrator explicitly asks to send/publish something.","parameters":{"type":"object","properties":{"text":{"type":"string","maxLength":4000}},"required":["text"]}}}
    ]
    messages = [
        {"role":"system","content":(
            "أنت وكيل تنفيذ خاص بالإدارة فقط. صاحب الطلب تم التحقق منه مسبقًا كـ ADMIN_ID. "
            "نفّذ فقط الأدوات المسموح بها. لا تنفذ أي حذف أو حظر أو تغيير صلاحيات. "
            "لا تخمّن. عند نقص الدليل استخدم search_web. "
            "لا ترسل للمجموعة إلا إذا طلب المدير ذلك صراحة."
        )},
        {"role":"user","content":task}
    ]
    attempted=set()
    idx,key=_pick_groq_key(exclude=attempted)
    if key is None:
        return None
    try:
        res=requests.post("https://api.groq.com/openai/v1/chat/completions",json={
            "model":os.environ.get("GROQ_AGENT_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")),
            "messages":messages,"tools":tools,"tool_choice":"auto","temperature":0.1,"max_completion_tokens":700
        },headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},timeout=7)
        if res.status_code!=200:
            print(f"Groq Agent HTTP {res.status_code}: {res.text[:300]}")
            return None
        data=res.json(); msg=data.get("choices",[{}])[0].get("message",{})
        tool_calls=msg.get("tool_calls") or []
        if not tool_calls:
            return sanitize_urls(msg.get("content","") or "") or None
        messages.append(msg)
        for tc in tool_calls[:3]:
            fn=tc.get("function",{}).get("name","")
            try: args=json.loads(tc.get("function",{}).get("arguments","{}"))
            except Exception: args={}
            if fn=="search_web":
                result=search_official(str(args.get("query","")[:500]))
            elif fn=="get_pi_status":
                result=format_pi_price()
            elif fn=="send_group_message":
                if not (active_group_chat_id or DEFAULT_GROUP_CHAT_ID):
                    result="ERROR: no active group known"
                else:
                    target=active_group_chat_id or DEFAULT_GROUP_CHAT_ID
                    r=send_message(target,str(args.get("text","")[:4000]))
                    result="SENT" if r and r.get("ok") else "ERROR: Telegram send failed"
            else:
                result="ERROR: tool not allowed"
            messages.append({"role":"tool","tool_call_id":tc.get("id",""),"name":fn,"content":str(result)[:6000]})
        final=requests.post("https://api.groq.com/openai/v1/chat/completions",json={
            "model":os.environ.get("GROQ_AGENT_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")),
            "messages":messages,"tools":tools,"tool_choice":"none","temperature":0.1,"max_completion_tokens":500
        },headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},timeout=7)
        if final.status_code==200:
            return sanitize_urls(final.json().get("choices",[{}])[0].get("message",{}).get("content","") or "") or "✅ تم تنفيذ المهمة."
        print(f"Groq Agent final HTTP {final.status_code}: {final.text[:300]}")
    except Exception as e:
        print(f"Groq Agent Exception: {e}")
    return None

def get_hermes_response(user_message, user_name="", search_context="", context_override=None):
    if not HERMES_API_KEY:
        return None
    try:
        context_text = context_override if context_override is not None else _build_ai_context(user_message, search_context)
        system_prompt = (
            ZYNMART_PROMPT
            + "\n" + context_text
            + "\nلا تختلق أي معلومة غير مدعومة."
        )
        payload = {
            "model": "nousresearch/hermes-3-llama-3.1-405b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_name}: {user_message}"}
            ],
            "temperature": 0.3,
            "max_tokens": 600
        }
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer " + HERMES_API_KEY, "Content-Type": "application/json"},
            timeout=7
        )
        if res.status_code == 200:
            txt = res.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if txt:
                return sanitize_urls(txt)
        else:
            print(f"Hermes HTTP {res.status_code}: {res.text[:300]}")
    except Exception as e:
        print(f"Hermes Exception: {e}")
    return None

def get_ai_response(user_message, user_name="", search_context=""):
    if emergency_active():
        return None
    # Current/time-sensitive questions require external evidence; never guess when evidence is unavailable.
    if needs_fresh_search(user_message) and not search_context:
        search_context = search_official(user_message)
        if not search_context and not fetch_real_evidence(user_message):
            print("Fresh-evidence gate: no verifiable evidence available")
            return None
    # Build external evidence once, then reuse it for Gemini -> Groq -> Hermes fallback.
    context_text = _build_ai_context(user_message, search_context)
    res = get_gemini_response(user_message, user_name, search_context, context_override=context_text)
    if res:
        return res
    # Second provider: Groq free tier. It is deliberately after Gemini and before Hermes.
    res_groq = get_groq_response(user_message, user_name, search_context, context_override=context_text)
    if res_groq:
        return res_groq
    res_hermes = get_hermes_response(user_message, user_name, search_context, context_override=context_text)
    if res_hermes:
        return res_hermes
    return None

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

ai_executor = ThreadPoolExecutor(max_workers=4)

def run_ai_job(fn):
    try:
        return ai_executor.submit(fn)
    except Exception as e:
        print(f"AI worker submit error: {e}")
        return None

def schedule_question(chat_id, msg):
    message_id = msg.get("message_id")
    key = (str(chat_id), int(message_id))
    delay = max(30, int(settings.get("question_delay", 30)))

    pending_questions[key] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text_without_bot_mention(msg.get("text", "")),
        "user_name": msg.get("from", {}).get("first_name", ""),
        "answered": False,
        "created": time.time(),
        "prepared_reply": None
    }

    def worker():
        # No question classification and no AI/search call at message arrival.
        # Around second 20, perform only the local deterministic analysis.
        prep_wait = min(20, delay)
        time.sleep(prep_wait)

        item = pending_questions.get(key)
        if not item or item.get("answered"):
            return

        text = item["text"]
        if not is_clear_question(text):
            pending_questions.pop(key, None)
            return

        # Start search/AI preparation around second 20 to reduce wasted quota.
        search_context = search_official(text) if needs_fresh_search(text) else ""
        reply = get_ai_response(text, item["user_name"], search_context)
        item["prepared_reply"] = reply

        # Send at the configured delay when possible. If AI/search took longer,
        # send immediately after preparation, but only if nobody replied.
        elapsed = time.time() - item.get("created", time.time())
        remaining = delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

        item = pending_questions.pop(key, None)
        if not item or item.get("answered"):
            return

        reply = item.get("prepared_reply")
        # Group remains completely silent when all AI services fail.
        if not reply:
            return
        send_message(chat_id, reply, reply_to=message_id)

    run_ai_job(worker)

def text_without_bot_mention(text):
    clean = re.sub(r'@?[A-Za-z0-9_]*zynmart_ai_bot[A-Za-z0-9_]*', '', text, flags=re.I)
    return re.sub(r'\s+', ' ', clean).strip()

def mark_pending_answered(chat_id, reply_to_message_id):
    for item in pending_questions.values():
        if item.get("chat_id") == chat_id and item.get("message_id") == reply_to_message_id:
            item["answered"] = True

def is_owner(user_id):
    try:
        return int(user_id) == OWNER_ID
    except Exception:
        return False

def emergency_active():
    return bool(settings.get("emergency_mode", False))

def set_emergency_mode(enabled, reason=""):
    settings["emergency_mode"] = bool(enabled)
    settings["emergency_reason"] = str(reason or "")[:500]
    save_settings()

def owner_security_keyboard():
    active = emergency_active()
    state = "🔴 طوارئ مفعلة" if active else "🟢 الوضع الطبيعي"
    return {
        "inline_keyboard": [
            [{"text": "🛑 إيقاف طوارئ" if not active else "🔴 الطوارئ مفعلة", "callback_data": "owner_emergency_on" if not active else "owner_emergency_status"},
             {"text": "▶️ فتح / استئناف", "callback_data": "owner_emergency_off"}],
            [{"text": state, "callback_data": "owner_emergency_status"}],
            [{"text": "🧾 سجل أمني", "callback_data": "admin_log"}],
            [{"text": "🔙 لوحة التحكم", "callback_data": "admin_back"}]
        ]
    }

def show_owner_security(chat_id):
    state = "🔴 وضع الطوارئ مفعّل" if emergency_active() else "🟢 النظام في الوضع الطبيعي"
    reason = settings.get("emergency_reason")
    text = ("🔐 مركز التحكم السري\n\n"
            "هذه المنطقة خاصة بصاحب التحكم في بوت AI for ZYNMART فقط.\n"
            f"الحالة: {state}")
    if reason:
        text += f"\nالسبب: {reason}"
    telegram("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": owner_security_keyboard()})

def platform_keyboard(owner=False):
    rows = [
        [{"text":"🤖 مركز الذكاء الاصطناعي","callback_data":"platform_ai"},{"text":"🔎 ZYN Search","callback_data":"platform_search"}],
        [{"text":"🛒 السوق ZynMart","callback_data":"platform_market"},{"text":"🏪 المتاجر","callback_data":"platform_stores"}],
        [{"text":"👥 المجتمع","callback_data":"platform_community"},{"text":"💬 الرسائل","callback_data":"platform_messages"}],
        [{"text":"📰 الأخبار","callback_data":"platform_news"},{"text":"🟣 Pi & Markets","callback_data":"platform_pi"}],
        [{"text":"🎨 Content Studio","callback_data":"platform_content"},{"text":"📊 التحليلات والبيانات","callback_data":"platform_analytics"}],
        [{"text":"🧰 الأدوات","callback_data":"platform_tools"},{"text":"🎮 الترفيه","callback_data":"platform_fun"}],
        [{"text":"⭐ ZYNMART+","callback_data":"platform_plus"},{"text":"📣 الإعلانات","callback_data":"platform_ads"}],
        [{"text":"🎁 المكافآت","callback_data":"platform_rewards"},{"text":"👤 الحساب","callback_data":"platform_account"}],
        [{"text":"🛡️ الأمان والثقة","callback_data":"platform_security"},{"text":"📚 مركز المعرفة","callback_data":"platform_knowledge"}],
        [{"text":"🆘 الدعم","callback_data":"platform_support"},{"text":"🧪 ZYN LAB","callback_data":"platform_lab"}],
    ]
    if owner:
        rows.append([{"text":"👑 إدارة البوت","callback_data":"admin_bot"}])
    rows.append([{ "text":"🔙 لوحة التحكم", "callback_data":"admin_back"}])
    return {"inline_keyboard": rows}

def show_platform_center(chat_id, owner=False):
    telegram("sendMessage", {"chat_id": chat_id, "text": "🌐 مركز منصة AI for ZYNMART\n\nتم تفعيل الوظائف المتاحة حاليًا. الوظائف التي تحتاج بنية خارجية تظهر 🚧 قريبًا بدل أن يتم الادعاء بأنها تعمل.", "reply_markup": platform_keyboard(owner)})

def platform_section(chat_id, key):
    sections = {
        "ai": ("🤖 مركز الذكاء الاصطناعي", ["💬 دردشة خاصة — 🟢", "🔎 بحث موثوق — 🟢", "🧠 تحليل/كتابة/تلخيص/ترجمة — 🟢 عبر محرك AI", "💻 برمجة وأفكار ومشاريع — 🟢", "🖼️ الصور — 🚧 قريبًا", "🎬 الفيديو — 🚧 قريبًا"]),
        "search": ("🔎 ZYN Search", ["🌐 بحث الويب — 🟢", "📰 الأخبار — 🟢 عند توفر المصدر", "🟣 بحث Pi — 🟢", "🛒 المنتجات/المتاجر — 🚧 قريبًا"]),
        "market": ("🛒 سوق ZynMart", ["🔎 البحث عن المنتجات — 🚧 قريبًا", "🏪 المتاجر والعروض — 🚧 قريبًا", "🛍️ السلة — 🚧 قريبًا", "➕ إضافة منتج — 🚧 قريبًا", "🏬 إنشاء متجر — 🚧 قريبًا"]),
        "stores": ("🏪 المتاجر", ["🔎 بحث المتاجر — 🚧 قريبًا", "⭐ المميزة — 🚧 قريبًا", "✅ الموثقة — 🚧 قريبًا", "➕ إنشاء متجر — 🚧 قريبًا"]),
        "community": ("👥 المجتمع", ["🏠 الرئيسية — 🚧 قريبًا", "👥 المجموعات والقنوات والمنشورات — 🚧 قريبًا", "🔔 الإشعارات والمتابعة — 🚧 قريبًا"]),
        "messages": ("💬 الرسائل", ["💬 رسائل المستخدمين — 🚧 قريبًا", "🤝 محادثات العملاء — 🚧 قريبًا", "🏪 محادثات التجار — 🚧 قريبًا"]),
        "news": ("📰 الأخبار", ["🌍 العالم / تقنية / AI / Crypto / Pi / تجارة — 🟢 عبر البحث عند الطلب", "🔥 الأكثر قراءة — 🚧 قريبًا", "🔎 بحث الأخبار — 🟢 عبر البحث"]),
        "pi": ("🟣 Pi & Markets", ["🟣 Pi Network — 🟢", "💵 أسعار الأسواق العامة — 🟢", "📊 مقارنة المصادر — 🟢", "📰 أخبار Pi — 🟢 عبر البحث", "🧠 تحليل — 🟢 مع أدلة"]),
        "content": ("🎨 Content Studio", ["✍️ كتابة — 🟢", "📣 منشورات وإعلانات — 🟢", "📄 مستندات — 🟢 حسب الإدخال", "🖼️ توليد صور — 🚧 قريبًا داخل البوت", "🎬 فيديو — 🚧 قريبًا", "🎙️ صوت — 🚧 قريبًا"]),
        "analytics": ("📊 مركز التحليلات والبيانات", ["🧮 حسابات ومقارنات — 🟢", "📈 تحليل بيانات — 🟢 عندما تُقدّم البيانات", "📑 تقارير — 🟢 نصيًا", "📊 تحليل سوق متقدم — 🚧 قريبًا"]),
        "tools": ("🧰 الأدوات", ["🧮 حاسبة — 🟢 عبر AI", "🌐 ترجمة — 🟢", "📅 تاريخ/وقت — 🟢", "💱 عملات — 🚧 بيانات مباشرة تحتاج مصدر", "📏 تحويل وحدات — 🟢", "🔗 أدوات الروابط — 🟢", "📁 أدوات الملفات — 🚧 قريبًا", "🔐 أدوات الأمان — 🟢 للمراقبة الحالية"]),
        "fun": ("🎮 الترفيه", ["🎮 ألعاب — 🚧 قريبًا", "🏆 تحديات وترتيب — 🚧 قريبًا", "🎁 مكافآت — 🚧 قريبًا"]),
        "plus": ("⭐ ZYNMART+", ["⭐ العضوية — 🚧 قريبًا", "🚀 مزايا AI متقدمة — 🚧 قريبًا", "🎁 عروض خاصة — 🚧 قريبًا"]),
        "ads": ("📣 مركز الإعلانات", ["➕ إنشاء إعلان — 🚧 قريبًا", "📋 إعلاناتي — 🚧 قريبًا", "📣 حملات ونتائج — 🚧 قريبًا", "💰 الميزانية — 🚧 قريبًا"]),
        "rewards": ("🎁 المكافآت", ["🎁 المكافآت والنشاط — 🚧 قريبًا", "🏆 الترتيب — 🚧 قريبًا", "📝 المهام والإحالات والنقاط — 🚧 قريبًا"]),
        "account": ("👤 الحساب", ["👤 الملف والنشاط — 🚧 قريبًا", "❤️ المفضلة والمشتريات — 🚧 قريبًا", "🏪 المتجر والإعلانات — 🚧 قريبًا", "🔔 الإشعارات والإعدادات — 🟢 إعدادات البوت الحالية"]),
        "security": ("🛡️ الأمان والثقة", ["🛡️ حماية الإدارة — 🟢", "🚫 مكافحة الاحتيال والمحتوى المشبوه — 🟢", "✅ التحقق من التجار — 🚧 قريبًا", "⭐ التقييمات والشروط والخصوصية — 🚧 قريبًا"]),
        "knowledge": ("📚 مركز المعرفة", ["📚 موسوعة وبحث — 🟢 عبر AI/ويب", "🎓 التعلم والدورات — 🚧 قريبًا", "📖 الأدلة والأسئلة الشائعة — 🟢 نصيًا"]),
        "support": ("🆘 الدعم", ["❓ المساعدة — 🟢", "🐞 الإبلاغ عن مشكلة — 🚧 قريبًا", "📞 التواصل — 🚧 قريبًا", "📊 حالة النظام — 🟢"]),
        "lab": ("🧪 ZYN LAB", ["🟢 الوظائف الحالية — AI / Search / Pi / Moderation / Daily / Broadcast", "🚧 القادم — Marketplace / Stores / Community / Messaging / Media / Membership / Rewards", "كل ميزة غير متاحة لا تُقدَّم للمستخدم على أنها مفعلة."]),
    }
    title, items = sections.get(key, ("ZYN LAB", ["🚧 قريبًا"]))
    text = title + "\n\n" + "\n".join("• " + x for x in items)
    send_message(chat_id, text, reply_markup={"inline_keyboard":[[{"text":"🔙 المنصة","callback_data":"admin_platform"}]]})

def admin_keyboard(owner=False):
    rows = [
        [{"text": "💬 دردشة خاصة", "callback_data": "admin_chat"}, {"text": "🤖 تنفيذ مهمة", "callback_data": "admin_agent"}],
        [{"text": "🌐 مركز المنصة", "callback_data": "admin_platform"}, {"text": "📢 البث", "callback_data": "admin_broadcast"}],
        [{"text": "⚙️ الإعدادات", "callback_data": "admin_settings"}, {"text": "🛡️ الإشراف", "callback_data": "admin_moderation"}],
        [{"text": "🕒 الانتظار", "callback_data": "admin_delay"}, {"text": "📅 الرسائل اليومية", "callback_data": "admin_daily"}],
        [{"text": "📊 سعر Pi", "callback_data": "admin_pi"}, {"text": "📋 السجل", "callback_data": "admin_log"}],
    ]
    if owner:
        rows.append([{ "text": "🔐 مركز التحكم السري", "callback_data": "owner_security"}])
    rows.append([{ "text": "🔙 رجوع", "callback_data": "admin_back"}])
    return {"inline_keyboard": rows}

def show_admin_panel(chat_id):
    return telegram("sendMessage", {
        "chat_id": chat_id,
        "text": "🛠️ لوحة تحكم ZYNMART\nاختر العملية المطلوبة:",
        "reply_markup": admin_keyboard(is_owner(chat_id))
    })

def settings_keyboard():
    delay = settings.get("question_delay", 30)
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

    if mode == "agent":
        def job():
            reply = get_groq_admin_agent_response(user_id, chat_id, text)
            send_message(chat_id, reply if reply else "⚠️ تعذّر تنفيذ المهمة حاليًا عبر وكيل المهام.")
        run_ai_job(job)
        return True

    if mode == "chat":
        def job():
            search_context = search_official(text) if needs_fresh_search(text) else ""
            reply = get_ai_response(text, "", search_context)
            send_message(chat_id, reply if reply else AI_PRIVATE_FAILURE_MESSAGE)
        run_ai_job(job)
        return True

    if mode == "broadcast_topic":
        target_group = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
        if target_group:
            creative_order = f"اكتب منشور ابداعي كامل ومحفز وجاهز للنشر عن: {text}"
            def job():
                search_results = search_official(text)
                broadcast_reply = get_ai_response(creative_order, "", search_context=search_results)
                if not broadcast_reply:
                    send_message(chat_id, AI_PRIVATE_FAILURE_MESSAGE)
                    return
                send_message(target_group, broadcast_reply)
                send_message(chat_id, "✅ تم النشر في المجموعة بنجاح!")
            run_ai_job(job)
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


# ---------------- Telegram Mini App / Web App ----------------
PLATFORM_SECTION_META = {
    "ai": ("🤖", "مركز الذكاء الاصطناعي", "AI / بحث موثوق / تحليل / كتابة / ترجمة / برمجة"),
    "search": ("🔎", "ZYN Search", "بحث الويب والأخبار والمصادر الموثوقة"),
    "market": ("🛒", "سوق ZynMart", "المنتجات والعروض والسوق"),
    "stores": ("🏪", "المتاجر", "المتاجر والتجار والعروض"),
    "community": ("👥", "المجتمع", "المجموعات والقنوات والمنشورات"),
    "messages": ("💬", "الرسائل", "المحادثات والرسائل"),
    "news": ("📰", "الأخبار", "العالم والتقنية والذكاء الاصطناعي وPi"),
    "pi": ("🟣", "Pi & Markets", "Pi والأسعار ومقارنة المصادر"),
    "content": ("🎨", "Content Studio", "الكتابة والمنشورات والإعلانات والمحتوى"),
    "analytics": ("📊", "التحليلات والبيانات", "الحسابات والمقارنات والتقارير"),
    "tools": ("🧰", "الأدوات", "الحاسبة والترجمة والتحويلات وأدوات الروابط"),
    "fun": ("🎮", "الترفيه", "الألعاب والتحديات والترتيب"),
    "plus": ("⭐", "ZYNMART+", "العضوية والمزايا المتقدمة"),
    "ads": ("📣", "الإعلانات", "الإعلانات والحملات والنتائج"),
    "rewards": ("🎁", "المكافآت", "النشاط والمهام والإحالات والنقاط"),
    "account": ("👤", "الحساب", "الملف والنشاط والإعدادات"),
    "security": ("🛡️", "الأمان والثقة", "الحماية ومكافحة الاحتيال"),
    "knowledge": ("📚", "مركز المعرفة", "الموسوعة والتعلم والأدلة"),
    "support": ("🆘", "الدعم", "المساعدة وحالة النظام"),
    "lab": ("🧪", "ZYN LAB", "الوظائف الحالية والقادمة"),
}
PLATFORM_STATUS = {
    "ai": {"active": ["دردشة AI", "بحث موثوق", "تحليل", "كتابة", "تلخيص", "ترجمة", "برمجة"], "soon": ["توليد الصور داخل التطبيق", "الفيديو", "الصوت"]},
    "search": {"active": ["بحث الويب", "بحث المصادر", "الأخبار عند توفر المصدر", "بحث Pi"], "soon": ["بحث المنتجات والمتاجر المدمج"]},
    "market": {"active": [], "soon": ["البحث عن المنتجات", "السلة", "العروض", "إضافة منتج", "إنشاء متجر", "المعاملات"]},
    "stores": {"active": [], "soon": ["البحث", "المتاجر المميزة", "التجار الموثقون", "لوحة التاجر"]},
    "community": {"active": [], "soon": ["المنشورات", "المجموعات", "القنوات", "المتابعة", "الإشعارات"]},
    "messages": {"active": [], "soon": ["الرسائل", "محادثات العملاء", "محادثات التجار"]},
    "news": {"active": ["بحث الأخبار عبر المصادر"], "soon": ["الأكثر قراءة", "خلاصة أخبار مخصصة"]},
    "pi": {"active": ["Pi Network", "أسعار المصادر العامة", "مقارنة المصادر", "أخبار Pi", "تحليل بالأدلة"], "soon": ["بيانات سوق داخلية متقدمة"]},
    "content": {"active": ["الكتابة", "المنشورات", "الإعلانات النصية", "المستندات حسب الإدخال"], "soon": ["توليد الصور", "الفيديو", "الصوت"]},
    "analytics": {"active": ["الحسابات", "المقارنات", "تحليل البيانات المقدمة", "تقارير نصية"], "soon": ["لوحات بيانات متقدمة"]},
    "tools": {"active": ["الحسابات", "الترجمة", "التاريخ والوقت", "تحويل الوحدات", "أدوات الروابط", "المراقبة الأمنية الحالية"], "soon": ["ملفات متقدمة", "بيانات عملات مباشرة مخصصة"]},
    "fun": {"active": [], "soon": ["الألعاب", "التحديات", "الترتيب", "المكافآت"]},
    "plus": {"active": [], "soon": ["العضوية", "مزايا AI متقدمة", "عروض خاصة"]},
    "ads": {"active": [], "soon": ["إنشاء إعلان", "حملات", "النتائج", "الميزانية"]},
    "rewards": {"active": [], "soon": ["المكافآت", "النشاط", "الترتيب", "المهام", "الإحالات", "النقاط"]},
    "account": {"active": ["إعدادات البوت الحالية"], "soon": ["الملف داخل المنصة", "المفضلة", "المشتريات", "المتجر"]},
    "security": {"active": ["حماية الإدارة", "مكافحة المحتوى المشبوه", "المراقبة الأمنية"], "soon": ["التحقق من التجار", "التقييمات", "مركز النزاعات"]},
    "knowledge": {"active": ["الموسوعة والبحث عبر AI/ويب", "الأدلة والأسئلة الشائعة"], "soon": ["الدورات التعليمية"]},
    "support": {"active": ["المساعدة", "حالة النظام"], "soon": ["بلاغات داخل التطبيق", "مركز تواصل متكامل"]},
    "lab": {"active": ["AI", "Search", "Pi", "Moderation", "Daily", "Broadcast", "Mini App"], "soon": ["Marketplace", "Stores", "Community", "Messaging", "Media", "Membership", "Rewards"]},
}

def _webapp_data_check(init_data):
    if not BOT_TOKEN or not isinstance(init_data, str) or not init_data:
        return None
    try:
        from urllib.parse import parse_qsl
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        auth_date = int(pairs.get("auth_date", "0"))
        if not received_hash or not auth_date or abs(time.time() - auth_date) > WEBAPP_INITDATA_MAX_AGE:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user = json.loads(pairs.get("user", "{}"))
        return user if isinstance(user, dict) and user.get("id") else None
    except Exception as e:
        print(f"WebApp initData validation error: {e}")
        return None

def _webapp_auth():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = _webapp_data_check(init_data)
    if not user:
        return None, jsonify({"ok": False, "error": "invalid_webapp_auth"}), 401
    uid = int(user.get("id"))
    if uid not in ADMIN_IDS:
        return None, jsonify({"ok": False, "error": "admin_only"}), 403
    return user, None, None

def _webapp_set_menu_button():
    global webapp_menu_configured
    if webapp_menu_configured or not BOT_TOKEN:
        return
    with webapp_menu_lock:
        if webapp_menu_configured:
            return
        result = telegram("setChatMenuButton", {"menu_button": {"type": "web_app", "text": WEBAPP_MENU_TEXT, "web_app": {"url": WEBAPP_URL}}})
        if result and result.get("ok"):
            webapp_menu_configured = True
            print(f"Telegram Mini App menu configured: {WEBAPP_URL}")
        else:
            print("Telegram Mini App menu configuration failed.")

def _webapp_platform_payload(user):
    sections = []
    for key, (icon, title, desc) in PLATFORM_SECTION_META.items():
        st = PLATFORM_STATUS.get(key, {"active": [], "soon": ["قريبًا"]})
        sections.append({"key": key, "icon": icon, "title": title, "description": desc,
                         "active": st.get("active", []), "soon": st.get("soon", []),
                         "state": "active" if st.get("active") else "soon"})
    return {"ok": True, "user": {"id": int(user.get("id")), "first_name": user.get("first_name", ""), "username": user.get("username", "")},
            "role": "owner" if is_owner(user.get("id")) else "admin", "sections": sections,
            "emergency": emergency_active(), "system": {"bot": bool(BOT_TOKEN), "webapp": True, "version": "platform-1"}}

WEBAPP_HTML = r'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no"><meta name="theme-color" content="#101329"><title>AI for ZYNMART</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#090b1b;--panel:#121631;--panel2:#171b3e;--text:#f7f8ff;--muted:#a6abc9;--gold:#ffd21a;--purple:#9d4edd;--green:#00e676;--line:#282d58}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#26235b 0,#11132d 36%,var(--bg) 75%);color:var(--text);font-family:Arial,"Noto Sans Arabic",sans-serif;min-height:100vh}.app{max-width:760px;margin:auto;padding-bottom:92px}.top{position:sticky;top:0;z-index:5;background:rgba(9,11,27,.94);backdrop-filter:blur(12px);padding:14px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}.brand{font-size:20px;font-weight:800;flex:1}.sub{font-size:11px;color:var(--muted)}button{font:inherit;color:inherit;border:0}.iconbtn{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:10px 13px}.hero{padding:20px 16px 10px}.hero h1{margin:0 0 7px;font-size:28px}.hero p{margin:0;color:var(--muted);line-height:1.7}.banner{margin:10px 16px;padding:16px;border:1px solid #3a3f78;border-radius:20px;background:linear-gradient(135deg,#1d1746,#10152f);box-shadow:0 10px 30px #0005}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;padding:12px 16px}.card{background:linear-gradient(160deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:20px;padding:16px;min-height:135px;text-align:right;cursor:pointer;transition:.15s}.card:active{transform:scale(.98)}.card .ico{font-size:30px}.card h3{margin:10px 0 6px;font-size:16px}.card p{margin:0;color:var(--muted);font-size:12px;line-height:1.5}.badge{display:inline-block;margin-top:10px;padding:4px 8px;border-radius:10px;font-size:11px;background:#073d27;color:#5dffac}.soon{background:#392c0a;color:#ffd84d}.bottom{position:fixed;bottom:0;left:0;right:0;z-index:10;background:rgba(9,11,27,.97);border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:9px 5px calc(9px + env(safe-area-inset-bottom))}.nav{background:none;padding:5px 8px;min-width:18%;color:#aab0d0;font-size:11px}.nav.active{color:var(--gold)}.nav b{display:block;font-size:20px;margin-bottom:3px}.back{margin:14px 16px;background:var(--panel2);border:1px solid var(--line);padding:10px 14px;border-radius:13px}.detail{padding:8px 16px}.sectionTitle{font-size:25px;font-weight:800;margin:14px 0 8px}.statusBox{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:15px;margin:10px 0}.row{padding:10px 0;border-bottom:1px solid #25294b}.row:last-child{border-bottom:0}.ok{color:var(--green)}.warn{color:#ffd84d}.center{text-align:center;padding:55px 20px}.loader{font-size:35px}.action{width:100%;background:linear-gradient(135deg,#6f36c5,#9d4edd);padding:13px;border-radius:14px;margin-top:10px;font-weight:700}.small{font-size:11px;color:var(--muted);line-height:1.6}@media(max-width:420px){.grid{gap:9px;padding:10px}.card{padding:13px;min-height:125px}.hero h1{font-size:24px}}
</style></head>
<body><div class="app"><div class="top"><button class="iconbtn" onclick="goHome()">⌂</button><div class="brand">AI for ZYNMART<div class="sub" id="userline">جاري التحقق...</div></div><button class="iconbtn" onclick="tg.close()">✕</button></div><main id="view"><div class="center"><div class="loader">⏳</div><p>جاري فتح المنصة...</p></div></main></div>
<nav class="bottom"><button class="nav active" id="n-home" onclick="goHome()"><b>⌂</b>الرئيسية</button><button class="nav" id="n-ai" onclick="openSection('ai')"><b>🤖</b>AI</button><button class="nav" id="n-search" onclick="openSection('search')"><b>🔎</b>بحث</button><button class="nav" id="n-more" onclick="more()"><b>▦</b>المزيد</button><button class="nav" id="n-admin" onclick="admin()"><b>⚙️</b>الإدارة</button></nav>
<script>
const tg=window.Telegram?.WebApp;let state=null;if(tg){tg.ready();tg.expand();}
async function api(path,opts={}){opts.headers=Object.assign({'Content-Type':'application/json','X-Telegram-Init-Data':tg?.initData||''},opts.headers||{});let r=await fetch(path,opts);let d=await r.json();if(!r.ok)throw new Error(d.error||'request_failed');return d}
function setNav(id){document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));document.getElementById(id)?.classList.add('active')}
function goHome(){setNav('n-home');renderHome()}
function renderHome(){document.getElementById('view').innerHTML=`<section class="hero"><h1>🌐 منصة AI for ZYNMART</h1><p>واجهة منصة داخل Telegram. الوظائف المتاحة تعمل، وغير المتاحة موضحة بوضوح: 🚧 قريبًا.</p></section><div class="banner"><b>🟢 النظام متصل</b><div class="small">الصلاحية: ${state.role==='owner'?'تحكم سري':'Admin'} · Mini App مفعل</div></div><div class="grid">${state.sections.map(card).join('')}</div>`}
function card(s){return `<button class="card" onclick="openSection('${s.key}')"><div class="ico">${s.icon}</div><h3>${esc(s.title)}</h3><p>${esc(s.description)}</p><span class="badge ${s.state==='soon'?'soon':''}">${s.state==='active'?'🟢 متاح':'🚧 قريبًا'}</span></button>`}
function openSection(key){setNav(key==='ai'?'n-ai':key==='search'?'n-search':'n-more');let s=state.sections.find(x=>x.key===key);if(!s)return;document.getElementById('view').innerHTML=`<button class="back" onclick="goHome()">← رجوع</button><section class="detail"><div class="sectionTitle">${s.icon} ${esc(s.title)}</div><p class="small">${esc(s.description)}</p><div class="statusBox"><b>الحالة</b>${s.active.map(x=>`<div class="row"><span class="ok">✓</span> ${esc(x)}</div>`).join('')}${s.soon.map(x=>`<div class="row"><span class="warn">🚧</span> ${esc(x)} — قريبًا</div>`).join('')}</div>${key==='pi'?'<button class="action" onclick="piStatus()">📊 عرض حالة Pi الحالية</button>':''}${key==='ai'?'<button class="action" onclick="aiBox()">💬 اختبار مركز الذكاء</button>':''}</section>`}
function more(){setNav('n-more');document.getElementById('view').innerHTML=`<section class="hero"><h1>المزيد</h1><p>كل أقسام المنصة في مكان واحد.</p></section><div class="grid">${state.sections.map(card).join('')}</div>`}
function admin(){setNav('n-admin');document.getElementById('view').innerHTML=`<button class="back" onclick="goHome()">← المنصة</button><section class="detail"><div class="sectionTitle">⚙️ مركز الإدارة</div><div class="statusBox"><div class="row">الدور: ${state.role==='owner'?'تحكم سري':'Admin'}</div><div class="row">🛡️ الحماية: <span class="ok">مفعلة</span></div><div class="row">🤖 الذكاء: <span class="ok">متاح</span></div><div class="row">🔎 البحث: <span class="ok">متاح</span></div><div class="row">🟣 Pi: <span class="ok">متاح</span></div>${state.role==='owner'?'<div class="row">🔐 مركز التحكم السري: <span class="ok">متاح لك فقط</span></div>':''}</div><button class="action" onclick="telegramPanel()">📋 فتح لوحة الإدارة في Telegram</button>${state.role==='owner'?'<button class="action" onclick="emergency()">🔐 مركز التحكم السري</button>':''}</section>`}
async function piStatus(){try{let d=await api('/api/app/pi');alert(d.text||'تعذر الحصول على بيانات Pi الموثوقة الآن.')}catch(e){alert('⚠️ لا توجد بيانات موثوقة متاحة الآن. لن نخمن.')}}
function aiBox(){document.getElementById('view').innerHTML=`<button class="back" onclick="openSection('ai')">← رجوع</button><section class="detail"><div class="sectionTitle">💬 دردشة AI</div><p class="small">الأسئلة التي تحتاج معلومات حديثة تمر عبر بوابة التحقق قبل الإجابة.</p><textarea id="q" style="width:100%;min-height:130px;background:#0e1230;color:white;border:1px solid #303665;border-radius:14px;padding:12px;font:inherit"></textarea><button class="action" onclick="askAI()">إرسال</button><div id="ans"></div></section>`}
async function askAI(){let q=document.getElementById('q').value.trim(),a=document.getElementById('ans');if(!q)return;a.innerHTML='<div class="statusBox">⏳ جاري التحقق...</div>';try{let d=await api('/api/app/ai',{method:'POST',body:JSON.stringify({question:q})});a.innerHTML='<div class="statusBox">'+esc(d.text||'')+'</div>'}catch(e){a.innerHTML='<div class="statusBox">⚠️ تعذر الحصول على إجابة موثوقة الآن. لن أخمّن.</div>'}}
function telegramPanel(){tg?.close();setTimeout(()=>{try{window.location.href='tg://resolve?domain=zynmart_ai_bot&start=admin'}catch(e){}},50)}
async function emergency(){try{let d=await api('/api/app/emergency');alert(d.text||'الحالة غير متاحة')}catch(e){alert('⚠️ تعذر قراءة حالة الطوارئ')}}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
async function start(){try{state=await api('/api/app/bootstrap');document.getElementById('userline').textContent=(state.user.first_name||'')+(state.user.username?' · @'+state.user.username:'');renderHome()}catch(e){document.getElementById('view').innerHTML='<div class="center"><div style="font-size:40px">🔒</div><h2>الوصول غير متاح</h2><p class="small">هذه المنصة مخصصة للإدارة في المرحلة الحالية.</p></div>'}}start();
</script></body></html>'''

@app.route("/app", methods=["GET"])
def webapp():
    ensure_background_services()
    return WEBAPP_HTML, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}

@app.route("/api/app/bootstrap", methods=["GET","POST"])
def webapp_bootstrap():
    user, err, code = _webapp_auth()
    if err: return err, code
    return jsonify(_webapp_platform_payload(user))

@app.route("/api/app/pi", methods=["GET"])
def webapp_pi():
    user, err, code = _webapp_auth()
    if err: return err, code
    if emergency_active(): return jsonify({"ok": False, "text": "⚠️ وضع الطوارئ مفعّل حاليًا."}), 503
    try:
        text = format_pi_price()
        return jsonify({"ok": True, "text": text or "⚠️ لا توجد بيانات Pi موثوقة متاحة الآن."})
    except Exception:
        return jsonify({"ok": False, "text": "⚠️ تعذر الحصول على بيانات Pi الموثوقة الآن."}), 503

@app.route("/api/app/ai", methods=["POST"])
def webapp_ai():
    user, err, code = _webapp_auth()
    if err: return err, code
    if emergency_active(): return jsonify({"ok": False, "text": "⚠️ وضع الطوارئ مفعّل حاليًا."}), 503
    body = request.get_json(silent=True) or {}
    question = str(body.get("question", "")).strip()
    if not question or len(question) > 4000: return jsonify({"ok": False, "error": "invalid_question"}), 400
    try:
        search_res = search_official(question) if needs_fresh_search(question) else ""
        reply = get_ai_response(question, user.get("first_name", ""), search_context=search_res)
        return jsonify({"ok": True, "text": reply or AI_PRIVATE_FAILURE_MESSAGE})
    except Exception as e:
        print(f"WebApp AI error: {e}")
        return jsonify({"ok": False, "text": "⚠️ تعذر الحصول على إجابة موثوقة الآن. لن أخمّن."}), 503

@app.route("/api/app/emergency", methods=["GET"])
def webapp_emergency():
    user, err, code = _webapp_auth()
    if err: return err, code
    if not is_owner(user.get("id")): return jsonify({"ok": False, "error": "owner_only"}), 403
    return jsonify({"ok": True, "text": "🔴 وضع الطوارئ مفعّل." if emergency_active() else "🟢 النظام في الوضع الطبيعي."})

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
        _webapp_set_menu_button()
        background_services_started = True
        print("Background scheduler started.")


def daily_scheduler():
    tz = ZoneInfo("Africa/Tunis")
    while True:
        try:
            auto_unmute_due()
            if (not emergency_active()) and settings.get("daily_enabled", True) and (active_group_chat_id or DEFAULT_GROUP_CHAT_ID):
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

    if action == "owner_security":
        if not is_owner(user_id):
            return
        show_owner_security(chat_id)
    elif action == "owner_emergency_on":
        if not is_owner(user_id):
            return
        set_emergency_mode(True, "تفعيل يدوي من مركز التحكم السري")
        log_action(chat_id, user_id, "owner_emergency_on", details="Emergency mode enabled")
        show_owner_security(chat_id)
    elif action == "owner_emergency_off":
        if not is_owner(user_id):
            return
        set_emergency_mode(False, "")
        log_action(chat_id, user_id, "owner_emergency_off", details="Emergency mode disabled")
        show_owner_security(chat_id)
    elif action == "owner_emergency_status":
        if not is_owner(user_id):
            return
        show_owner_security(chat_id)
    elif action == "admin_platform":
        show_platform_center(chat_id, is_owner(user_id))
    elif action.startswith("platform_"):
        platform_section(chat_id, action.split("_", 1)[1])
    elif action == "admin_bot":
        if not is_owner(user_id):
            return
        show_owner_security(chat_id)
    elif action == "admin_chat":
        admin_modes[user_id] = "chat"
        send_message(chat_id, "💬 دخلت وضع الدردشة الخاصة.\nاكتب سؤالك مباشرة.\nاكتب «رجوع» للعودة إلى لوحة التحكم.")
    elif action == "admin_agent":
        admin_modes[user_id] = "agent"
        send_message(chat_id, "🤖 وضع تنفيذ المهام — للإدارة فقط.\nاكتب المهمة المطلوبة وسأنفذ فقط الأدوات المسموح بها.\n«رجوع» للعودة إلى لوحة التحكم.")
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

    if chat_type in ["group", "supergroup"]:
        remember_user(msg)
        if active_group_chat_id != chat_id:
            active_group_chat_id = chat_id
            save_users_to_file()

        # Any group member's direct reply cancels the pending AI answer.
        reply_to = msg.get("reply_to_message", {})
        if reply_to:
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
            if not question:
                send_message(chat_id, "👋 أنا هنا. اكتب سؤالك وسأحاول مساعدتك.", reply_to=msg.get("message_id"))
                return jsonify({"status": "ok"}), 200
            message_id = msg.get("message_id")
            def job():
                search_res = search_official(question) if needs_fresh_search(question) else ""
                reply = get_ai_response(question, user_name, search_context=search_res)
                send_message(chat_id, reply if reply else MENTION_AI_FAILURE_MESSAGE, reply_to=message_id)
            run_ai_job(job)
            return jsonify({"status": "ok"}), 200

        # Non-mention group messages are intentionally ignored by AI.
        # This protects response speed and API quota; moderation/security monitoring above remains active.
        return jsonify({"status": "ok"}), 200

    if chat_type == "private":
        # Preserve original private protection.
        if user_id not in ADMIN_IDS:
            return jsonify({"status": "ok"}), 200

        # Original broadcast command behavior is preserved exactly.
        if text.startswith("ابدا البث") or text.startswith("ابدأ البث"):
            if emergency_active():
                send_message(chat_id, "🛑 وضع الطوارئ مفعّل مؤقتًا؛ تم إيقاف البث والعمليات الآلية الحساسة.")
                return jsonify({"status": "ok"}), 200
            target_group = active_group_chat_id or DEFAULT_GROUP_CHAT_ID
            if target_group:
                raw_cmd = text.replace("ابدا البث", "", 1).replace("ابدأ البث", "", 1).strip()

                if raw_cmd.startswith(":"):
                    broadcast_reply = sanitize_urls(raw_cmd[1:].strip())
                    send_message(target_group, broadcast_reply)
                    send_message(chat_id, "✅ تم النشر في المجموعة بنجاح!")
                else:
                    search_query = raw_cmd if raw_cmd else "اخبار Pi Network و ZYNMART"
                    creative_order = f"اكتب منشور ابداعي كامل ومحفز وجاهز للنشر عن: {search_query}"
                    def job():
                        search_results = search_official(search_query)
                        broadcast_reply = get_ai_response(creative_order, user_name, search_context=search_results)
                        if not broadcast_reply:
                            send_message(chat_id, AI_PRIVATE_FAILURE_MESSAGE)
                            return
                        send_message(target_group, broadcast_reply)
                        send_message(chat_id, "✅ تم النشر في المجموعة بنجاح!")
                    run_ai_job(job)
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

        # Preserve ordinary private AI reply, but process it outside /webhook so
        # slow AI/search calls can never make Telegram/Render wait for the result.
        def job():
            search_res = search_official(text) if needs_fresh_search(text) else ""
            direct_reply = get_ai_response(text, user_name, search_context=search_res)
            send_message(chat_id, direct_reply if direct_reply else AI_PRIVATE_FAILURE_MESSAGE)
        run_ai_job(job)
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    ensure_background_services()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
