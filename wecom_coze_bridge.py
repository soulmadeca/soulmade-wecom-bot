from gevent import monkey; monkey.patch_all()

#!/usr/bin/env python3
"""
WeCom <-> Coze AI bridge  ·  正确架构版
架构: 立即返回 "success" → 后台greenlet调Coze → 主动发消息给用户
不再用被动回复(被动XML)，因为WeCom只等5秒而Coze需要5-20秒
"""

import hashlib, time, json, struct, base64, random, string, logging, requests, os
import gevent
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

# ---------- AES 加解密 ----------
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

# ---------- WeCom 主动发消息 (需要IP白名单) ----------
_token_cache = {"token": "", "expires": 0}

def get_access_token():
    if time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}"
    r = requests.get(url, timeout=10).json()
    if r.get("errcode", 0) == 0:
        _token_cache["token"] = r["access_token"]
        _token_cache["expires"] = time.time() + r["expires_in"]
        logger.info("[TOKEN] 刷新成功")
    else:
        logger.error(f"[TOKEN] 获取失败: {r}")
    return _token_cache["token"]

def send_message(to_user, content):
    """主动发消息给企业微信用户（需要本机IP在企业微信白名单中）"""
    try:
        token = get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": WECOM_AGENT_ID,
            "text": {"content": content}
        }
        r = requests.post(url, json=payload, timeout=10).json()
        if r.get("errcode") == 0:
            logger.info(f"[发送] ✅ 成功 → {to_user}")
        else:
            logger.error(f"[发送] ❌ 失败: {r}")
        return r
    except Exception as e:
        logger.error(f"[发送] 异常: {e}")
        return None

# ---------- Coze AI ----------
def ask_coze(question, user_id):
    headers = {"Authorization": f"Bearer {COZE_API_KEY}", "Content-Type": "application/json"}
    body = {
        "bot_id": COZE_BOT_ID,
        "user_id": user_id,
        "stream": True,
        "auto_save_history": True,
        "additional_messages": [{"role": "user", "content": question, "content_type": "text"}]
    }
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
                cur_event = line[6:].strip()
                continue
            if line.startswith("data:"):
                s = line[5:].strip()
                if s == "[DONE]": break
                try:
                    d = json.loads(s)
                    if (isinstance(d, dict) and
                        cur_event == "conversation.message.completed" and
                        d.get("role") == "assistant" and
                        d.get("type") == "answer"):
                        v = d.get("content", "")
                        if v:
                            answer = v
                            logger.info(f"[COZE] 获得回答，长度={len(v)}")
                    if isinstance(d, dict) and d.get("last_error"):
                        logger.error(f"[COZE] 错误: {d['last_error']}")
                except Exception:
                    pass
        return answer or None

    except requests.exceptions.Timeout:
        logger.warning("[COZE] 超时")
        return None
    except Exception as e:
        logger.exception(f"[COZE] 异常: {e}")
        return None

# ---------- 后台处理消息（gevent greenlet） ----------
def handle_in_background(from_user, content):
    t0 = time.time()
    logger.info(f"[后台] 开始处理: {from_user} → {content[:40]}")
    answer = ask_coze(content, from_user)
    elapsed = round(time.time() - t0, 1)
    if answer:
        logger.info(f"[后台] Coze回答 {elapsed}s，发送中...")
        send_message(from_user, answer)
    else:
        logger.warning(f"[后台] Coze失败 {elapsed}s，发送错误提示")
        send_message(from_user, "小助手暂时遇到问题，请稍后再试或联系店长。")

# ---------- Flask 路由 ----------
@app.route("/health")
def health():
    return json.dumps({"status": "ok", "mode": "async+wecom-api"})

@app.route("/diag")
def diag():
    r = {"mode": "async (立即返回success + 后台调Coze + 主动发消息)"}
    try:
        import socket; r["host"] = socket.gethostname()
    except: pass
    try:
        ip_resp = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        r["external_ip"] = ip_resp.get("ip")
        r["whitelist_tip"] = f"请将此IP加入企业微信白名单: {ip_resp.get('ip')}"
    except Exception as e:
        r["ip_err"] = str(e)
    try:
        t = requests.get(
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}",
            timeout=10).json()
        r["wecom_token_ok"] = t.get("errcode", 0) == 0
        r["wecom_errcode"] = t.get("errcode", 0)
        if t.get("errcode") == 60020:
            r["wecom_error"] = "❌ IP未在白名单！请将external_ip加入企业微信IP白名单"
        elif t.get("errcode") == 0:
            r["wecom_error"] = "✅ IP白名单正常"
    except Exception as e:
        r["wecom_err"] = str(e)
    r["coze_key"] = COZE_API_KEY[:12] + "..."
    return json.dumps(r, ensure_ascii=False)

@app.route("/test-coze")
def test_coze():
    t0 = time.time()
    answer = ask_coze("请用一句话介绍你自己", "test_diag")
    elapsed = round(time.time() - t0, 1)
    if answer:
        return json.dumps({"ok": True, "answer": answer[:200], "elapsed_s": elapsed, "note": f"Coze响应{elapsed}秒"}, ensure_ascii=False)
    return json.dumps({"ok": False, "elapsed_s": elapsed, "note": "Coze无回答或超时"}, ensure_ascii=False), 500

@app.route("/test-send")
def test_send():
    to_user = request.args.get("user", "")
    if not to_user:
        return json.dumps({"error": "需要参数: ?user=企业微信用户ID"}, ensure_ascii=False), 400
    r = send_message(to_user, "【测试】服务器主动发消息成功！IP白名单配置正确 ✅")
    return json.dumps({"result": r}, ensure_ascii=False)

@app.route("/", methods=["GET", "POST"])
@app.route("/wecom", methods=["GET", "POST"])
def wecom():
    import xml.etree.ElementTree as ET

    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        logger.info(f"[验证] echostr长度={len(echostr)}")
        try:
            plain = wecom_decrypt(echostr)
            logger.info(f"[验证] ✅ 成功，长度={len(plain)}")
            return plain
        except Exception as e:
            logger.exception(f"[验证] ❌ 失败: {e}")
            return "error", 500

    if request.method == "POST":
        try:
            root = ET.fromstring(request.data)
            xml_str = wecom_decrypt(root.find("Encrypt").text)
            msg = ET.fromstring(xml_str)

            msg_type  = msg.find("MsgType").text
            from_user = msg.find("FromUserName").text

            logger.info(f"[消息] from={from_user} type={msg_type}")

            if msg_type == "text":
                content = msg.find("Content").text.strip()
                logger.info(f"[消息] 内容: {content[:60]}")
                gevent.spawn(handle_in_background, from_user, content)
                logger.info(f"[消息] ✅ 已启动后台处理，立即返回success")

        except Exception as e:
            logger.exception(f"[POST] 处理异常: {e}")

        return "success", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
