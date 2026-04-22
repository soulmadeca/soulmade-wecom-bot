#!/usr/bin/env python3
"""
WeCom <-> Coze AI bridge
同步回复模式：直接在callback中返回加密XML，不需要IP白名单
"""

import hashlib, time, json, struct, base64, random, string, logging, requests, os
from flask import Flask, request, Response
from Crypto.Cipher import AES

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ========== CONFIG ==========
WECOM_TOKEN            = "zwKG8qu5J9jJ"
WECOM_ENCODING_AES_KEY = "FuCdn0CIF8aIOTewc1jYz0ajQ9PcyEbxhiu5E7RC37Q"
WECOM_CORP_ID          = "ww1250414ed84f6f22"
WECOM_AGENT_ID         = 1000002
WECOM_CORP_SECRET      = "XxdI0vyDBr-WU0vlP5EE3k9VnEtcqnq4bG3lkHuqkPU"

COZE_API_KEY = os.environ.get('COZE_API_KEY', 'pat_eghsRFQVrQ8OKwZesNXwzrjgvSOcHrJWD8Qion4NzD6tzmlEqVwj58q15wtkHRHG')
COZE_BOT_ID  = "7630679730714673205"
COZE_API_URL = "https://api.coze.com/v3/chat"
# ============================

AES_KEY = base64.b64decode(WECOM_ENCODING_AES_KEY + "=")

# ---------- AES ----------
def _pkcs7_unpad(data):
    pad = data[-1]
    if pad == 0 or pad > 32:
        raise ValueError(f"Invalid pad: {pad}")
    return data[:-pad]

def _pkcs7_pad(data):
    pad_len = 32 - len(data) % 32
    return data + bytes([pad_len] * pad_len)

def wecom_decrypt(encrypt_b64):
    encrypt_b64 = encrypt_b64.replace(" ", "+")
    raw = base64.b64decode(encrypt_b64)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    plain = _pkcs7_unpad(cipher.decrypt(raw))
    plain = plain[16:]
    msg_len = struct.unpack(">I", plain[:4])[0]
    return plain[4:4 + msg_len].decode("utf-8")

def wecom_encrypt(plain_text):
    rand = ''.join(random.choices(string.ascii_letters + string.digits, k=16)).encode()
    plain_bytes = plain_text.encode("utf-8")
    msg_len = struct.pack(">I", len(plain_bytes))
    content = rand + msg_len + plain_bytes + WECOM_CORP_ID.encode()
    padded = _pkcs7_pad(content)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    return base64.b64encode(cipher.encrypt(padded)).decode()

def wecom_sign(*args):
    return hashlib.sha1("".join(sorted(args)).encode()).hexdigest()

# ---------- Build encrypted reply ----------
def build_sync_reply(from_user, to_user, content):
    """Build encrypted WeCom XML reply (no API call, no IP whitelist needed)"""
    ts = str(int(time.time()))
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))

    plain_xml = (
        f"<xml>"
        f"<ToUserName><![CDATA[{from_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
        f"<CreateTime>{ts}</CreateTime>"
        f"<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"</xml>"
    )

    encrypt = wecom_encrypt(plain_xml)
    sign = wecom_sign(WECOM_TOKEN, ts, nonce, encrypt)

    reply_xml = (
        f"<xml>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{sign}]]></MsgSignature>"
        f"<TimeStamp>{ts}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        f"</xml>"
    )
    return Response(reply_xml, content_type="application/xml")

# ---------- Coze API ----------
def ask_coze(question, user_id, timeout=25):
    headers = {"Authorization": f"Bearer {COZE_API_KEY}", "Content-Type": "application/json"}
    body = {
        "bot_id": COZE_BOT_ID,
        "user_id": user_id,
        "stream": True,
        "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": question, "content_type": "text"}]
    }
    try:
        resp = requests.post(COZE_API_URL, headers=headers, json=body, timeout=timeout, stream=True)
        if resp.status_code != 200:
            logger.error(f"[COZE] HTTP {resp.status_code}: {resp.text[:300]}")
            return None

        answer = ""
        current_event = ""

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8")

            if line.startswith("event:"):
                current_event = line[6:].strip()
                continue

            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    if (isinstance(data, dict) and
                        current_event == "conversation.message.completed" and
                        data.get("role") == "assistant" and
                        data.get("type") == "answer"):
                        content_val = data.get("content", "")
                        if content_val:
                            answer = content_val
                            logger.info(f"[COZE] answer len={len(answer)}")
                except Exception:
                    pass

        return answer if answer else None

    except requests.exceptions.Timeout:
        logger.warning("[COZE] timeout")
        return None
    except Exception as e:
        logger.exception(f"[COZE] error: {e}")
        return None

# ---------- WeCom token + send (fallback only) ----------
_token_cache = {"token": "", "expires": 0}

def get_access_token():
    if time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}"
    r = requests.get(url, timeout=10).json()
    if r.get("errcode", 0) == 0:
        _token_cache["token"] = r["access_token"]
        _token_cache["expires"] = time.time() + r["expires_in"]
        logger.info("[TOKEN] refreshed")
    else:
        logger.error(f"[TOKEN] error: {r}")
    return _token_cache["token"]

def send_message_api(to_user, content):
    """Fallback: send via WeCom API (requires IP whitelist)"""
    try:
        token = get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {"touser": to_user, "msgtype": "text",
                   "agentid": WECOM_AGENT_ID, "text": {"content": content}}
        r = requests.post(url, json=payload, timeout=10).json()
        logger.info(f"[SEND] {r}")
        return r
    except Exception as e:
        logger.error(f"[SEND] error: {e}")
        return None

# ---------- Routes ----------
@app.route("/health")
def health():
    return json.dumps({"status": "ok"})

@app.route("/diag")
def diag():
    result = {}
    try:
        import socket
        result["hostname"] = socket.gethostname()
    except Exception as e:
        result["hostname_err"] = str(e)
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        result["external_ip"] = ip.get("ip")
    except Exception as e:
        result["ip_err"] = str(e)
    try:
        tr = requests.get(
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}",
            timeout=10).json()
        result["token_ok"] = tr.get("errcode", 0) == 0
        result["token_errcode"] = tr.get("errcode", 0)
    except Exception as e:
        result["token_err"] = str(e)
    result["coze_key_prefix"] = COZE_API_KEY[:12] + "..."
    result["reply_mode"] = "sync_xml (no IP whitelist needed)"
    return json.dumps(result)

@app.route("/test-coze")
def test_coze():
    """Quick Coze connectivity test"""
    start = time.time()
    answer = ask_coze("你好，请用一句话介绍自己", "test_user", timeout=20)
    elapsed = round(time.time() - start, 1)
    if answer:
        return json.dumps({"ok": True, "answer": answer[:200], "elapsed_s": elapsed})
    return json.dumps({"ok": False, "elapsed_s": elapsed, "note": "no answer or timeout"}), 500

@app.route("/", methods=["GET", "POST"])
@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    import xml.etree.ElementTree as ET

    # ── URL验证 (GET) ──
    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        logger.info(f"[VERIFY] echostr len={len(echostr)}")
        try:
            plain = wecom_decrypt(echostr)
            logger.info(f"[VERIFY] OK len={len(plain)}")
            return plain
        except Exception as e:
            logger.exception(f"[VERIFY] failed: {e}")
            return "decrypt error", 500

    # ── 接收消息 (POST) ──
    if request.method == "POST":
        try:
            root = ET.fromstring(request.data)
            encrypt = root.find("Encrypt").text
            xml_str = wecom_decrypt(encrypt)
            msg = ET.fromstring(xml_str)

            msg_type  = msg.find("MsgType").text
            from_user = msg.find("FromUserName").text
            to_user   = msg.find("ToUserName").text

            logger.info(f"[MSG] from={from_user} type={msg_type}")

            if msg_type == "text":
                content = msg.find("Content").text.strip()
                logger.info(f"[MSG] content={content[:80]}")

                # 同步调用Coze，直接在callback里回复，不需要IP白名单
                answer = ask_coze(content, from_user, timeout=25)

                if answer:
                    logger.info(f"[REPLY] sync XML reply len={len(answer)}")
                    return build_sync_reply(from_user, to_user, answer)
                else:
                    logger.warning("[REPLY] Coze failed, fallback API")
                    send_message_api(from_user, "小助手暂时无法回复，请联系店长。")

        except Exception as e:
            logger.exception(f"[POST] error: {e}")

        return "success", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
