import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "akin-esp32-2026")

latest_message = {
    "id": 0,
    "sender": "",
    "message": "",
    "received_at": "",
}


@app.get("/")
def home():
    return "WhatsApp ESP32 sunucusu calisiyor.", 200


@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200

    return "Webhook dogrulanamadi.", 403


@app.post("/webhook")
def receive_webhook():
    global latest_message

    data = request.get_json(silent=True) or {}

    try:
        value = data["entry"][0]["changes"][0]["value"]
        messages = value.get("messages", [])

        if messages:
            incoming = messages[0]

            if incoming.get("type") == "text":
                text = incoming.get("text", {}).get("body", "")
            else:
                text = f"[{incoming.get('type', 'bilinmeyen')} mesaj]"

            latest_message = {
                "id": latest_message["id"] + 1,
                "sender": incoming.get("from", ""),
                "message": text,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }

            print("Yeni WhatsApp mesaji:", latest_message, flush=True)

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook verisi okunamadi:", error, flush=True)

    # Meta webhook'a her zaman hızlıca 200 yanıtı verilmelidir.
    return "EVENT_RECEIVED", 200


@app.get("/message")
def get_message():
    return jsonify(latest_message)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
