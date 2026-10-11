import io
with io.open("main.py","r",encoding="utf-8") as f:
    src = f.read()
orig = len(src)
applied, failed = [], []

def ap(name, old, new):
    global src
    if old not in src:
        failed.append(name); return
    src = src.replace(old, new, 1)
    applied.append(name)

# ============================================================
# FIX N: route جديد لربط المحفظة يدويًا + تحقق blockchain
# ============================================================
# نضيف route جديد بعد route الحالي
marker = '''@app.route("/api/app/account/wallet", methods=["GET","POST"])'''
if marker in src:
    new_route = '''@app.route("/api/app/account/wallet/manual", methods=["POST"])
def webapp_account_wallet_manual():
    """Link a Pi wallet address by manual input with real blockchain verification.

    This bypasses Pi SDK wallet_address scope limitations by validating the
    address directly against the Pi Horizon API. The address is stored only
    after the network confirms it exists and holds a valid account.
    """
    user, err, code = _webapp_auth()
    if err: return err, code
    account_id = str(user.get("platform_account_id") or "").strip()
    if not account_id:
        return jsonify({"ok":False,"error":"account_required"}), 401
    body = request.get_json(silent=True) or {}
    wallet_address = str(body.get("wallet_address") or "").strip()
    if not re.fullmatch(r"G[A-Z2-7]{55}", wallet_address):
        return jsonify({"ok":False,"error":"invalid_pi_wallet_format",
                        "hint":"Pi wallet address must start with G and be 56 characters"}), 400
    # Verify on Pi Horizon (testnet or mainnet depending on env)
    horizon_base = NFT_HORIZON_URL if NFT_HORIZON_URL else "https://api.testnet.minepi.com"
    verified = False
    detail = ""
    try:
        r = requests.get(horizon_base.rstrip("/") + "/accounts/" + wallet_address, timeout=10)
        if r.status_code == 200:
            verified = True
            detail = "account_exists_on_pi_network"
        else:
            detail = f"pi_horizon_{r.status_code}"
    except Exception as e:
        detail = f"horizon_unreachable: {str(e)[:100]}"
    if not verified:
        return jsonify({"ok":False,"error":"wallet_not_verified_on_pi_network",
                        "detail":detail,"network":"testnet" if "testnet" in horizon_base else "mainnet"}), 400
    # Persist the verified address
    conn = None
    try:
        conn = _membership_db_connect()
        if not conn:
            return jsonify({"ok":False,"error":"database_unavailable"}), 503
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT 1 FROM ai_for_identity_links WHERE account_id=%s AND provider='pi' AND verified=TRUE LIMIT 1",
                            (account_id,))
                if not cur.fetchone():
                    return jsonify({"ok":False,"error":"pi_identity_not_linked"}), 409
                cur.execute("""UPDATE ai_for_identity_links
                               SET wallet_address=%s, last_seen=NOW()
                               WHERE account_id=%s AND provider='pi' AND verified=TRUE
                               RETURNING provider_username""",
                            (wallet_address[:160], account_id))
                row = cur.fetchone()
                if not row:
                    return jsonify({"ok":False,"error":"pi_identity_not_linked"}), 409
        control_audit(user.get("id", 0), "wallet_manual_link", account_id,
                      {"wallet_address": wallet_address[:20]+"..."})
        return jsonify({"ok":True,"wallet_address":wallet_address,
                        "verified":True,"source":"manual_with_horizon_check"})
    except Exception as e:
        print(f"Manual wallet link error: {e}")
        return jsonify({"ok":False,"error":"wallet_link_failed"}), 503
    finally:
        _membership_db_release(conn)


@app.route("/api/app/account/wallet", methods=["GET","POST"])'''
    src = src.replace(marker, new_route, 1)
    applied.append("N_manual_wallet_route")
else:
    failed.append("N_manual_wallet_route")

# ============================================================
# FIX O: الواجهة — إضافة نموذج لصق العنوان اليدوي
# ============================================================
# نجد loadWalletStatus ونضيف نموذجًا بديلًا
old_load = '''async function loadWalletStatus(){let box=document.getElementById('walletBox');if(!box)return;try{let r=await fetch('/api/app/account/wallet',{headers:authHeaders(),cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'wallet_failed');box.innerHTML=d.linked&&d.wallet_address?'<b>👛 محفظة Pi المرتبطة</b><div class="small" style="word-break:break-all;margin-top:6px">'+esc(d.wallet_address)+'</div><span class="badge">مرتبطة</span>':'<b>👛 محفظتي</b><p class="small">اربط محفظة Pi المرتبطة بهويتك. لن نطلب أي مفتاح خاص أو عبارة سرية.</p><button class="action" onclick="linkUserWallet()">🟣 ربط محفظة Pi</button>'}catch(e){box.innerHTML='<b>👛 محفظتي</b><p class="small">اربط محفظة Pi من داخل Pi Browser. لن نطلب أي مفتاح خاص أو عبارة سرية.</p><button class="action" onclick="linkUserWallet()">🟣 ربط محفظة Pi</button>'}}'''

new_load = '''async function loadWalletStatus(){let box=document.getElementById('walletBox');if(!box)return;try{let r=await fetch('/api/app/account/wallet',{headers:authHeaders(),cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'wallet_failed');if(d.linked&&d.wallet_address){box.innerHTML='<b>👛 محفظة Pi المرتبطة</b><div class="small" style="word-break:break-all;margin-top:6px">'+esc(d.wallet_address)+'</div><span class="badge">مرتبطة ✓</span>'}else{box.innerHTML='<b>👛 محفظتي</b><p class="small">اربط محفظتك بإحدى الطريقتين:</p><button class="action" onclick="linkUserWallet()">🟣 ربط تلقائي عبر Pi</button><div style="margin-top:14px;padding-top:12px;border-top:1px solid #ddd"><b class="small">أو أدخل العنوان يدويًا:</b><input id="manualWallet" placeholder="GXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" style="width:100%;margin-top:8px;padding:10px;font-size:12px" maxlength="56"><button class="action dark" onclick="linkWalletManual()">🔗 ربط وتحقق من الشبكة</button><div id="manualWalletResult" class="small" style="margin-top:6px"></div></div>'}}catch(e){box.innerHTML='<b>👛 محفظتي</b><p class="small">اربط محفظتك:</p><button class="action" onclick="linkUserWallet()">🟣 ربط تلقائي عبر Pi</button><div style="margin-top:14px;padding-top:12px;border-top:1px solid #ddd"><b class="small">أو أدخل العنوان يدويًا:</b><input id="manualWallet" placeholder="GXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" style="width:100%;margin-top:8px;padding:10px;font-size:12px" maxlength="56"><button class="action dark" onclick="linkWalletManual()">🔗 ربط وتحقق من الشبكة</button><div id="manualWalletResult" class="small" style="margin-top:6px"></div></div>'}}

async function linkWalletManual(){let inp=document.getElementById('manualWallet'),res=document.getElementById('manualWalletResult');if(!inp||!res)return;let addr=inp.value.trim().toUpperCase();if(!/^G[A-Z2-7]{55}$/.test(addr)){res.innerHTML='<span class="danger">⚠️ العنوان يجب أن يبدأ بـG ويكون 56 حرفًا</span>';return}res.innerHTML='⏳ جاري التحقق من الشبكة...';try{let r=await fetch('/api/app/account/wallet/manual',{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},cache:'no-store',body:JSON.stringify({wallet_address:addr})});let d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'link_failed');res.innerHTML='<span class="ok">✅ تم الربط والتحقق من الشبكة</span>';setTimeout(()=>loadWalletStatus(),600)}catch(e){res.innerHTML='<span class="danger">⚠️ '+esc(e.message||'فشل')+'</span>'}}'''

ap("O_wallet_ui_manual", old_load, new_load)

with io.open("main.py","w",encoding="utf-8") as f:
    f.write(src)

print("=" * 55)
print(f"Diff: {len(src)-orig:+,}")
print("=" * 55)
for a in applied: print(f"  ✅ {a}")
for x in failed:  print(f"  ❌ {x}")
import ast
try:
    ast.parse(open("main.py",encoding="utf-8").read())
    print("SYNTAX_OK")
except SyntaxError as e:
    print(f"SYNTAX_ERROR line {e.lineno}: {e.msg}")
