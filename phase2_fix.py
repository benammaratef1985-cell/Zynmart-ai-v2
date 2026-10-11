import io
with io.open("main.py", "r", encoding="utf-8") as f:
    src = f.read()
orig = len(src)
applied, failed = [], []

def ap(name, old, new):
    global src
    if old not in src:
        failed.append(name); return
    n = src.count(old)
    src = src.replace(old, new, n)
    applied.append(f"{name} (x{n})")

# ============================================================
# FIX A: _platform_db_query — إعادة محاولة واحدة عند فشل الاتصال
# ============================================================
ap("A_db_query_retry",
'''def _platform_db_query(fn):
    conn=None
    try:
        conn=_membership_db_connect()
        if not conn: return None
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                return fn(cur)
    except Exception as e:
        print(f"Platform DB error: {e}")
        return None
    finally:
        _membership_db_release(conn)''',
'''def _platform_db_query(fn):
    """Central DB helper: retries once on transient connection failures,
    surfaces the actual exception in logs, and always closes its connection."""
    last_err = None
    for attempt in range(2):
        conn=None
        try:
            conn=_membership_db_connect()
            if not conn:
                last_err = "no_connection"
                if attempt == 0:
                    try: ensure_database_ready()
                    except Exception: pass
                    continue
                return None
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    return fn(cur)
        except Exception as e:
            last_err = e
            import traceback
            print(f"Platform DB error [attempt {attempt+1}]: {e}")
            traceback.print_exc()
            if attempt == 0:
                continue
            return None
        finally:
            _membership_db_release(conn)
    print(f"Platform DB final failure: {last_err}")
    return None''')

# ============================================================
# FIX B: _record_reputation_event — حماية row من None
# ============================================================
ap("B_record_reputation_safe",
'''            cur.execute("SELECT score,level FROM ai_for_reputation WHERE identity_key=%s",(identity,)); row=cur.fetchone() or {"score":0,"level":1}
            return {"recorded":inserted,"points":points if inserted else 0,"score":int(row["score"]),"level":int(row["level"])}''',
'''            cur.execute("SELECT score,level FROM ai_for_reputation WHERE identity_key=%s",(identity,)); row=cur.fetchone()
            score_val = int(row["score"]) if row and row.get("score") is not None else 0
            level_val = int(row["level"]) if row and row.get("level") is not None else 1
            return {"recorded":inserted,"points":points if inserted else 0,"score":score_val,"level":level_val}''')

# ============================================================
# FIX C: _reputation_snapshot — حماية من None
# ============================================================
ap("C_reputation_snapshot_safe",
'''        return {"score":int(row["score"]) if row else 0,"level":int(row["level"]) if row else 1,"updated_at":row["updated_at"].isoformat() if row and row.get("updated_at") else None,"events":events}''',
'''        return {"score":int(row["score"]) if row and row.get("score") is not None else 0,"level":int(row["level"]) if row and row.get("level") is not None else 1,"updated_at":row["updated_at"].isoformat() if row and row.get("updated_at") else None,"events":events}''')

# ============================================================
# FIX D: _platform_message_send — حماية row["user_id"] و row["account_id"]
# ============================================================
ap("D_message_send_guard",
'''            cur.execute("SELECT user_id FROM ai_for_members WHERE user_id=%s LIMIT 1",(uid,))
            row=cur.fetchone(); resolved=("tg:"+str(row["user_id"])) if row else None''',
'''            cur.execute("SELECT user_id FROM ai_for_members WHERE user_id=%s LIMIT 1",(uid,))
            row=cur.fetchone()
            try: resolved=("tg:"+str(row["user_id"])) if row and row.get("user_id") is not None else None
            except Exception: resolved=None''')

ap("D_message_send_digit",
'''            cur.execute("SELECT user_id FROM ai_for_members WHERE user_id=%s LIMIT 1",(int(recipient),))
            row=cur.fetchone(); resolved=("tg:"+str(row["user_id"])) if row else None''',
'''            cur.execute("SELECT user_id FROM ai_for_members WHERE user_id=%s LIMIT 1",(int(recipient),))
            row=cur.fetchone()
            try: resolved=("tg:"+str(row["user_id"])) if row and row.get("user_id") is not None else None
            except Exception: resolved=None''')

ap("D_message_send_username",
'''            if row: resolved="tg:"+str(row["user_id"])
            else:
                cur.execute("SELECT account_id FROM ai_for_web_accounts WHERE lower(username)=lower(%s) AND status='active' LIMIT 1",(recipient,))
                row=cur.fetchone(); resolved=("web:"+str(row["account_id"])) if row else None''',
'''            try: resolved=("tg:"+str(row["user_id"])) if row and row.get("user_id") is not None else None
            except Exception: resolved=None
            if not resolved:
                cur.execute("SELECT account_id FROM ai_for_web_accounts WHERE lower(username)=lower(%s) AND status='active' LIMIT 1",(recipient,))
                row=cur.fetchone()
                try: resolved=("web:"+str(row["account_id"])) if row and row.get("account_id") is not None else None
                except Exception: resolved=None''')

# ============================================================
# FIX E: platform_identity_status — قبول Bearer token
# ============================================================
ap("E_identity_status_bearer",
'''@app.route("/api/platform/identity/status", methods=["GET"])
def platform_identity_status():
    account=_get_web_account_from_request()
    if not account:return jsonify({"ok":False,"error":"not_authenticated"}),401''',
'''@app.route("/api/platform/identity/status", methods=["GET"])
def platform_identity_status():
    account=_get_web_account_from_request()
    if not account:
        # Pi Browser WebView may drop the cookie between page loads; accept the
        # Pi SDK bearer token as an alternate proof of identity.
        auth = str(request.headers.get("Authorization","")).strip()
        if auth.lower().startswith("bearer "):
            account = _web_account_from_pi_access_token(auth[7:].strip())
    if not account:return jsonify({"ok":False,"error":"not_authenticated"}),401''')

# ============================================================
# FIX F: /api/platform/me — قبول Bearer token
# ============================================================
ap("F_me_bearer",
'''@app.route("/api/platform/me", methods=["GET"])
def platform_me():
    account = _get_web_account_from_request()
    if not account:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401''',
'''@app.route("/api/platform/me", methods=["GET"])
def platform_me():
    account = _get_web_account_from_request()
    if not account:
        # Same tolerant fallback as identity/status: allow Pi SDK bearer token
        # when the WebView drops the session cookie.
        auth = str(request.headers.get("Authorization","")).strip()
        if auth.lower().startswith("bearer "):
            account = _web_account_from_pi_access_token(auth[7:].strip())
    if not account:
        return jsonify({"ok": False, "error": "not_authenticated"}), 401''')

# ============================================================
# FIX G: _webapp_auth — قبول Bearer في الواجهة الرئيسية أيضًا
# ============================================================
ap("G_webapp_auth_bearer",
'''    channel = str(request.headers.get("X-AI-For-Channel", "")).strip().lower()
    account = _get_web_account_from_request()
    if channel in ("pi", "telegram"):
        if account:''',
'''    channel = str(request.headers.get("X-AI-For-Channel", "")).strip().lower()
    account = _get_web_account_from_request()
    if not account:
        # Pi Browser sometimes drops the session cookie; use the Pi SDK token.
        auth = str(request.headers.get("Authorization","")).strip()
        if auth.lower().startswith("bearer "):
            account = _web_account_from_pi_access_token(auth[7:].strip())
    if channel in ("pi", "telegram"):
        if account:''')

# ============================================================
# FIX H: webapp_account_wallet — قراءة أفضل للـ wallet
# ============================================================
ap("H_wallet_double_fallback",
'''                token=str(request.headers.get("Authorization","")).strip()
                if not token.lower().startswith("bearer "): return jsonify({"ok":False,"error":"pi_auth_required"}),401
                verified,verr=_verified_pi_user(token[7:].strip())
                if verr or not verified: return jsonify({"ok":False,"error":verr or "pi_identity_missing"}),401
                body=request.get_json(silent=True) or {}
                # Pi /v2/me may not include wallet_address unless the wallet_address scope
                # was requested during Pi.authenticate. Trust the SDK-provided address
                # only after the same bearer token has been verified against the same UID.
                wallet_address=str(verified.get("wallet_address") or body.get("wallet_address") or body.get("walletAddress") or "").strip()
                if not re.fullmatch(r"G[A-Z2-7]{55}", wallet_address): return jsonify({"ok":False,"error":"wallet_scope_required"}),400''',
'''                token=str(request.headers.get("Authorization","")).strip()
                if not token.lower().startswith("bearer "): return jsonify({"ok":False,"error":"pi_auth_required"}),401
                verified,verr=_verified_pi_user(token[7:].strip())
                if verr or not verified: return jsonify({"ok":False,"error":verr or "pi_identity_missing"}),401
                body=request.get_json(silent=True) or {}
                # Pi /v2/me may not include wallet_address unless the wallet_address
                # scope was requested during Pi.authenticate. Trust the SDK-provided
                # address only after the same bearer token was verified against the
                # same UID (which is what `verified` already proves).
                wallet_address=str(
                    verified.get("wallet_address")
                    or body.get("wallet_address")
                    or body.get("walletAddress")
                    or ""
                ).strip()
                # Final safety net: read the wallet address from the Pi account
                # directly, in case /v2/me omitted it but the account has it.
                if not re.fullmatch(r"G[A-Z2-7]{55}", wallet_address):
                    try:
                        extra = requests.get("https://api.minepi.com/v2/me",
                                             headers={"Authorization": f"Bearer {token[7:].strip()}"},
                                             timeout=6).json()
                        u = extra.get("user") if isinstance(extra.get("user"), dict) else extra
                        wallet_address = str(u.get("wallet_address") or u.get("walletAddress") or "").strip()
                    except Exception:
                        pass
                if not re.fullmatch(r"G[A-Z2-7]{55}", wallet_address):
                    return jsonify({"ok":False,"error":"wallet_scope_required",
                                    "hint":"Use Pi.authenticate with scopes ['username','payments','wallet_address']"}),400''')

# ============================================================
# FIX I: pi login binding — bind owner pi_uid in metadata for owner detection
# ============================================================
ap("I_pi_owner_meta",
'''                            meta_owner["telegram_bridge_id"] = str(OWNER_ID)
                            meta_owner["telegram_bridge_role"] = "owner"
                            meta_owner["pi_owner_uid"] = PI_OWNER_UID''',
'''                            meta_owner["telegram_bridge_id"] = str(OWNER_ID)
                            meta_owner["telegram_bridge_role"] = "owner"
                            meta_owner["pi_owner_uid"] = PI_OWNER_UID
                            meta_owner["pi_uid"] = str(verified.get("uid") or "")''')

with io.open("main.py", "w", encoding="utf-8") as f:
    f.write(src)

print("=" * 60)
print(f"Original: {orig:,}")
print(f"New     : {len(src):,}")
print(f"Diff    : {len(src)-orig:+,}")
print("=" * 60)
for a in applied: print(f"  ✅ {a}")
for x in failed:  print(f"  ❌ {x}")
print("=" * 60)

# فحص syntax
import ast
try:
    ast.parse(open("main.py", encoding="utf-8").read())
    print("SYNTAX_OK")
except SyntaxError as e:
    print(f"SYNTAX_ERROR line {e.lineno}: {e.msg}")
