#!/usr/bin/env python3
"""
WeCom (企业微信) ↔ Coze AI 桥接服务
"""
import hashlib, time, json, struct, base64, random, string, socket, logging, requests, threading
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ========== 配置 ==========
WECOM_TOKEN            = "OXrbKRCZP16i6lFbBQtu"
WECOM_ENCODING_AES_KEY = "F82YtGahbT4TC3ntZxv5PbjlqeI1MtZdAfNi5TIsrxi"
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
    return data[:-pad]

def wecom_decrypt(encrypt_b64):
    raw = base64.b64decode(encrypt_b64)
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_KEY[:16])
    plain = _pkcs7_unpad(cipher.decrypt(raw))
    plain = plain[16:]
    msg_len = struct.unpack(">I", plain[:4])[0]
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
    logger.info(f"发送结果: {r}")

def ask_coze(question, user_id):
    headers = {"Authorization": f"Bearer {COZE_API_KEY}", "Content-Type": "application/json"}
    body = {
        "bot_id": COZE_BOT_ID, "user_id": user_id,
        "stream": False, "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": question, "content_type": "text"}]
    }
    resp = requests.post(COZE_API_URL, headers=headers, json=body, timeout=30).json()
    if resp.get("code") != 0:
        logger.error(f"Coze错误: {resp}")
        return "抱歉，AI助手暂时无法回复，请联系店长。"

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
                    return m.get("content", "无法获取回复")
            break
        elif status in ("failed", "cancelled"):
            break

    return "AI处理超时，请稍后再试或联系店长。"

@app.route("/health")
def health():
    return json.dumps({"status": "ok", "service": "WeCom-Coze Bridge"}), 200

@app.route("/test")
def test_public():
    return "OK - 服务运行正常", 200

@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    sig  = request.args.get("msg_signature", "")
    ts   = request.args.get("timestamp", "")
    nc   = request.args.get("nonce", "")

    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        logger.info(f"[验证] WeCom验证请求到达! echostr长度={len(echostr)}")
        try:
            plain = wecom_decrypt(echostr)
            logger.info(f"[验证] 解密成功")
            return plain
        except Exception as e:
            logger.exception(f"[验证] 解密失败: {e}")
            return "解密错误", 500

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
                logger.info(f"[消息] {from_user}: {content}")
                def reply():
                    answer = ask_coze(content, from_user)
                    send_message(from_user, answer)
                threading.Thread(target=reply, daemon=True).start()
        except Exception as e:
            logger.exception(f"处理消息失败: {e}")
        return "success"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__('os').environ.get('PORT', 5000)), debug=False)
