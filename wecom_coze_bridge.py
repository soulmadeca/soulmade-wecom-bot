#!/usr/bin/env python3
"""
WeCom (ÃÂÃÂ¤ÃÂÃÂ¼ÃÂÃÂÃÂÃÂ¤ÃÂÃÂ¸ÃÂÃÂÃÂÃÂ¥ÃÂÃÂ¾ÃÂÃÂ®ÃÂÃÂ¤ÃÂÃÂ¿ÃÂÃÂ¡) ÃÂÃÂ¢ÃÂÃÂÃÂÃÂ Coze AI ÃÂÃÂ¦ÃÂÃÂ¡ÃÂÃÂ¥ÃÂÃÂ¦ÃÂÃÂÃÂÃÂ¥ÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂ¡
"""
import hashlib, time, json, struct, base64, random, string, socket, logging, requests, threading
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ========== ÃÂÃÂ©ÃÂÃÂÃÂÃÂÃÂÃÂ§ÃÂÃÂ½ÃÂÃÂ® ==========
WECOM_TOKEN            = "OXrbKRCZP16i6lFbBQtu"
WECOM_ENCODING_AES_KEY = "F82YtGahbT4TC3ntZxv5PbjIqel1MtZdAfNi5TIsrxi"
WECOM_CORP_ID          = "ww1250414ed84f6f22"
WECOM_AGENT_ID         = 1000002
WECOM_CORP_SECRET      = "XxdI0vyDBr-WU0vlP5EE3k9VnEtcqnq4bG3lkHuqkPU"

COZE_API_KEY  = "pat_eghsRFQVrQ8OKwZesNXwzrjgvSOcHrJWD8Qion4NzD6tzmlEqVwj58q15wtkHRHG"
COZE_BOT_ID   = "7630679730714673205"
COZE_API_URL  = "https://api.coze.com/v3/chat"
# ==========================

from Crypto.Cipher import AES

AES_KEY = base64.b64decode(WECOM_ENCODING_AES_KEY + "=")

def _pkcs7_unpad(data):
    pad = data[-1]
    if pad == 0 or pad > 32:
        raise ValueError(f"Invalid PKCS7 pad byte: {pad}, last8: {data[-8:].hex()}")
    return data[:-pad]

def wecom_decrypt(encrypt_b64):
    encrypt_b64 = encrypt_b64.replace(" ", "+")
    logger.info(f"[DEBUG] echostr first30={encrypt_b64[:30]!r} last10={encrypt_b64[-10:]!r} total_len={len(encrypt_b64)}")
    raw = base64.b64decode(encrypt_b64)
    logger.info(f"[DEBUG] raw_bytes_len={len(raw)}")
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    decrypted = cipher.decrypt(raw)
    logger.info(f"[DEBUG] decrypted_len={len(decrypted)} last8_hex={decrypted[-8:].hex()} pad_byte={decrypted[-1]}")
    plain = _pkcs7_unpad(decrypted)
    logger.info(f"[DEBUG] after_unpad_len={len(plain)} first20_hex={plain[:20].hex() if plain else 'EMPTY'}")
    plain = plain[16:]
    logger.info(f"[DEBUG] after_skip16_len={len(plain)} first8_hex={plain[:8].hex() if len(plain) >= 8 else plain.hex()}")
    msg_len = struct.unpack(">I", plain[:4])[0]
    logger.info(f"[DEBUG] msg_len={msg_len}")
    return plain[4:4 + msg_len].decode("utf-8")

def wecom_encrypt(plain_text):
    plain_text = plain_text.encode("utf-8")
    rand = ''.join(random.choices(string.ascii_letters, k=16)).encode()
    msg_len = struct.pack(">I", len(plain_text))
    content = rand + msg_len + plain_text + WECOM_CORP_ID.encode()
    pad_len = 32 - len(content) % 32
    content += bytes([pad_len] * pad_len)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    return base64.b64encode(cipher.encrypt(content)).decode()

def wecom_sign(*args):
    return hashlib.sha1("".join(sorted(args)).encode()).hexdigest()

def get_access_token():
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}"
    return requests.get(url, timeout=10).json()["access_token"]

def send_message(to_user, content):
    token = get_access_token()
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {"touser": to_user, "msgtype": "text",
               "agentid": WECOM_AGENT_ID, "text": {"content": content}}
    r = requests.post(url, json=payload, timeout=10).json()
    logger.info(f"ÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ©ÃÂÃÂÃÂÃÂÃÂÃÂ§ÃÂÃÂ»ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂ: {r}")

def ask_coze(question, user_id):
    headers = {"Authorization": f"Bearer {COZE_API_KEY}", "Content-Type": "application/json"}
    body = {
        "bot_id": COZE_BOT_ID, "user_id": user_id,
        "stream": False, "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": question, "content_type": "text"}]
    }
    resp = requests.post(COZE_API_URL, headers=headers, json=body, timeout=30).json()
    if resp.get("code") != 0:
        logger.error(f"CozeÃÂÃÂ©ÃÂÃÂÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ¯: {resp}")
        return "ÃÂÃÂ¦ÃÂÃÂÃÂÃÂ±ÃÂÃÂ¦ÃÂÃÂ­ÃÂÃÂÃÂÃÂ¯ÃÂÃÂ¼ÃÂÃÂAIÃÂÃÂ¥ÃÂÃÂÃÂÃÂ©ÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂ¶ÃÂÃÂ¦ÃÂÃÂÃÂÃÂ ÃÂÃÂ¦ÃÂÃÂ³ÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂÃÂÃÂ¯ÃÂÃÂ¼ÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ·ÃÂÃÂ¨ÃÂÃÂÃÂÃÂÃÂÃÂ§ÃÂÃÂ³ÃÂÃÂ»ÃÂÃÂ¥ÃÂÃÂºÃÂÃÂÃÂÃÂ©ÃÂÃÂÃÂÃÂ¿ÃÂÃÂ£ÃÂÃÂÃÂÃÂ"

    chat_id = resp["data"]["id"]
    conv_id = resp["data"]["conversation_id"]

    for _ in range(30):
        time.sleep(1)
        poll = requests.get(
            f"https://api.coze.com/v3/chat/retrieve?conversation_id={conv_id}&chat_id={chat_id}",
            headers=headers, timeout=10).json()
        status = poll.get("data", {}).get("status")
        if status == "completed":
            msgs = requests.get(
                f"https://api.coze.com/v3/chat/message/list?conversation_id={conv_id}&chat_id={chat_id}",
                headers=headers, timeout=10).json()
            for m in msgs.get("data", []):
                if m.get("role") == "assistant" and m.get("type") == "answer":
                    return m.get("content", "ÃÂÃÂ¦ÃÂÃÂÃÂÃÂ ÃÂÃÂ¦ÃÂÃÂ³ÃÂÃÂÃÂÃÂ¨ÃÂÃÂÃÂÃÂ·ÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂ")
            break
        elif status in ("failed", "cancelled"):
            break

    return "AIÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂÃÂÃÂ§ÃÂÃÂÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¶ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂ¶ÃÂÃÂ¯ÃÂÃÂ¼ÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ·ÃÂÃÂ§ÃÂÃÂ¨ÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¨ÃÂÃÂÃÂÃÂÃÂÃÂ§ÃÂÃÂ³ÃÂÃÂ»ÃÂÃÂ¥ÃÂÃÂºÃÂÃÂÃÂÃÂ©ÃÂÃÂÃÂÃÂ¿ÃÂÃÂ£ÃÂÃÂÃÂÃÂ"

@app.route("/health")
def health():
    return json.dumps({"status": "ok", "service": "WeCom-Coze Bridge"}), 200

@app.route("/test")
def test_public():
    return "OK - ÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂ¡ÃÂÃÂ¨ÃÂÃÂ¿ÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¡ÃÂÃÂÃÂÃÂ¦ÃÂÃÂ­ÃÂÃÂ£ÃÂÃÂ¥ÃÂÃÂ¸ÃÂÃÂ¸", 200

@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    sig  = request.args.get("msg_signature", "")
    ts   = request.args.get("timestamp", "")
    nc   = request.args.get("nonce", "")

    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        logger.info(f"[ÃÂÃÂ©ÃÂÃÂªÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ] WeComÃÂÃÂ©ÃÂÃÂªÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ·ÃÂÃÂ¦ÃÂÃÂ±ÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂ°ÃÂÃÂ¨ÃÂÃÂ¾ÃÂÃÂ¾! echostrÃÂÃÂ©ÃÂÃÂÃÂÃÂ¿ÃÂÃÂ¥ÃÂÃÂºÃÂÃÂ¦={len(echostr)}")
        try:
            plain = wecom_decrypt(echostr)
            logger.info(f"[ÃÂÃÂ©ÃÂÃÂªÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ] ÃÂÃÂ¨ÃÂÃÂ§ÃÂÃÂ£ÃÂÃÂ¥ÃÂÃÂ¯ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂÃÂÃÂ¥ÃÂÃÂÃÂÃÂ")
            return plain
        except Exception as e:
            logger.exception(f"[ÃÂÃÂ©ÃÂÃÂªÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ] ÃÂÃÂ¨ÃÂÃÂ§ÃÂÃÂ£ÃÂÃÂ¥ÃÂÃÂ¯ÃÂÃÂÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂ±ÃÂÃÂ¨ÃÂÃÂ´ÃÂÃÂ¥: {e}")
            return "ÃÂÃÂ¨ÃÂÃÂ§ÃÂÃÂ£ÃÂÃÂ¥ÃÂÃÂ¯ÃÂÃÂÃÂÃÂ©ÃÂÃÂÃÂÃÂÃÂÃÂ¨ÃÂÃÂ¯ÃÂÃÂ¯", 500

    if request.method == "POST":
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(request.data)
            encrypt = root.find("Encrypt").text
            xml_str = wecom_decrypt(encrypt)
            msg = ET.fromstring(xml_str)
            msg_type  = msg.find("MsgType").text
            from_user = msg.find("FromUserName").text
            if msg_type == "text":
                content = msg.find("Content").text.strip()
                logger.info(f"[ÃÂÃÂ¦ÃÂÃÂ¶ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂ¯] {from_user}: {content}")
                def reply():
                    answer = ask_coze(content, from_user)
                    send_message(from_user, answer)
                threading.Thread(target=reply, daemon=True).start()
        except Exception as e:
            logger.exception(f"ÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂÃÂÃÂ§ÃÂÃÂÃÂÃÂÃÂÃÂ¦ÃÂÃÂ¶ÃÂÃÂÃÂÃÂ¦ÃÂÃÂÃÂÃÂ¯ÃÂÃÂ¥ÃÂÃÂ¤ÃÂÃÂ±ÃÂÃÂ¨ÃÂÃÂ´ÃÂÃÂ¥: {e}")
        return "success"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__('os').environ.get('PORT', 5000)), debug=False)
