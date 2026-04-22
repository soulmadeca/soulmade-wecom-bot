from gevent import monkey; monkey.patch_all()

#!/usr/bin/env python3
"""WeCom <-> Coze AI bridge — gevent + sync XML reply (no IP whitelist needed)"""

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

def _pkcs7_unpad(data):
    pad = data[-1]
    if pad == 0 or pad > 32:
        raise ValueError(f"bad pad {pad}")
    return data[:-pad]

def _pkcs7_pad(data):
    pad_len = 32 - len(data) % 32
    return data + bytes([pad_len] * pad_len)

def wecom_decrypt(encrypt_b64):
    raw = base64.b64decode(encrypt_b64.replace(" ", "+"))
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    plain = _pkcs7_unpad(cipher.decrypt(raw))[16:]
    msg_len = struct.unpack(">I", plain[:4])[0]
    return plain[4:4 + msg_len].decode("utf-8")

def wecom_encrypt(plain_text):
    rand = ''.join(random.choices(string.ascii_letters + string.digits, k=16)).encode()
    pb = plain_text.encode("utf-8")
    content = rand + struct.pack(">I", len(pb)) + pb + WECOM_CORP_ID.encode()
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    return base64.b64encode(cipher.encrypt(_pkcs7_pad(content))).decode()

def wecom_sign(*args):
    return hashlib.sha1("".join(sorted(args)).encode()).hexdigest()

def build_sync_reply(from_user, to_user, content):
    ts = str(int(time.time()))
    nonce = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    plain_xml = (f"<xml><ToUserName><![CDATA[{from_user}]]></ToUserName>"
                 f"<FromUserName><![CDATA[{to_user}]]></FromUserName>"
                 f"<CreateTime>{ts}</CreateTime>"
                 f"<MsgType><![CDATA[text]]></MsgType>"
                 f"<Content><![CDATA[{content}]]></Content></xml>")
    encrypt = wecom_encrypt(plain_xml)
    sign = wecom_sign(WECOM_TOKEN, ts, nonce, encrypt)
    xml = (f"<xml><Encrypt><![CDATA[{encrypt}]]></Encrypt>"
           f"<MsgSignature><![CDATA[{sign}]]></MsgSignature>"
           f"<TimeStamp>{ts}</TimeStamp>"
           f"<Nonce><![CDATA[{nonce}]]></Nonce></xml>")
    return Response(xml, content_type="application/xml")

def ask_coze(question, user_id):
    headers = {"Authorization": f"Bearer {COZE_API_KEY}", "Content-Type": "application/json"}
    body = {"bot_id": COZE_BOT_ID, "user_id": user_id, "stream": True,
            "auto_save_history": True,
            "additional_messages": [{"role": "user", "content": question, "content_type": "text"}]}
    try:
        resp = requests.post(COZE_API_URL, headers=headers, json=body, timeout=30, stream=True)
        if resp.status_code != 200:
            logger.error(f"[COZE] HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        answer = ""
        cur_event = ""
        for raw in resp.iter_lines():
            if not raw: continue
            line = raw.decode("utf-8")
            if line.startswith("event:"):
                cur_event = line[6:].strip(); continue
            if line.startswith("data:"):
                s = line[5:].strip()
                if s == "[DONE]": break
                try:
                    d = json.loads(s)
                    if (isinstance(d, dict) and cur_event == "conversation.message.completed"
                            and d.get("role") == "assistant" and d.get("type") == "answer"):
                        v = d.get("content", "")
                        if v: answer = v; logger.info(f"[COZE] len={len(v)}")
                except Exception: pass
        return answer or None
    except Exception as e:
        logger.exception(f"[COZE] {e}")
        return None

@app.route("/health")
def health():
    return json.dumps({"status": "ok", "mode": "gevent+sync_xml"})

@app.route("/diag")
def diag():
    r = {}
    try:
        import socket; r["host"] = socket.gethostname()
    except: pass
    try:
        r["ip"] = requests.get("https://api.ipify.org?format=json", timeout=5).json().get("ip")
    except Exception as e: r["ip_err"] = str(e)
    try:
        t = requests.get(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}", timeout=10).json()
        r["token_ok"] = t.get("errcode", 0) == 0
    except Exception as e: r["token_err"] = str(e)
    r["mode"] = "gevent+sync_xml (no IP whitelist needed)"
    return json.dumps(r)

@app.route("/test-coze")
def test_coze():
    t0 = time.time()
    a = ask_coze("你好，一句话介绍自己", "test")
    return json.dumps({"ok": bool(a), "answer": (a or "")[:200], "s": round(time.time()-t0, 1)})

@app.route("/", methods=["GET", "POST"])
@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    import xml.etree.ElementTree as ET

    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        try:
            plain = wecom_decrypt(echostr)
            logger.info(f"[VERIFY] OK len={len(plain)}")
            return plain
        except Exception as e:
            logger.exception(f"[VERIFY] fail: {e}")
            return "error", 500

    if request.method == "POST":
        try:
            root = ET.fromstring(request.data)
            xml_str = wecom_decrypt(root.find("Encrypt").text)
            msg = ET.fromstring(xml_str)
            msg_type  = msg.find("MsgType").text
            from_user = msg.find("FromUserName").text
            to_user   = msg.find("ToUserName").text
            logger.info(f"[MSG] from={from_user} type={msg_type}")
            if msg_type == "text":
                content = msg.find("Content").text.strip()
                logger.info(f"[MSG] {content[:60]}")
                answer = ask_coze(content, from_user)
                if answer:
                    logger.info(f"[REPLY] sync XML len={len(answer)}")
                    return build_sync_reply(from_user, to_user, answer)
                else:
                    return build_sync_reply(from_user, to_user, "小助手暂时无法回复，请联系店长。")
        except Exception as e:
            logger.exception(f"[POST] {e}")
        return "success", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
