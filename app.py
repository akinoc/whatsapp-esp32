from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

VERIFY_TOKEN = "akin123"

# Son 20 mesajı bellekte tutar
MAX_MESSAGES = 20
messages_history = []
message_counter = 0


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_whatsapp_message():
    global message_counter

    data = request.get_json(silent=True) or {}

    try:
        value = data["entry"][0]["changes"][0]["value"]
        incoming_messages = value.get("messages", [])

        if incoming_messages:
            incoming = incoming_messages[0]

            sender = incoming.get("from", "")
            message_type = incoming.get("type", "")

            if message_type == "text":
                message_text = incoming.get("text", {}).get("body", "")
            else:
                message_text = f"[{message_type or 'bilinmeyen'} mesaj]"

            message_counter += 1

            new_message = {
                "id": message_counter,
                "sender": sender,
                "message": message_text,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            messages_history.append(new_message)

            # Sadece son 20 mesajı tut
            if len(messages_history) > MAX_MESSAGES:
                messages_history.pop(0)

            print(f"Yeni mesaj: {new_message}")

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook verisi okunamadi:", error)

    return "EVENT_RECEIVED", 200


# Sadece en son mesaj
@app.route("/message", methods=["GET"])
def get_last_message():
    if not messages_history:
        return jsonify({
            "id": 0,
            "sender": "",
            "message": ""
        })

    return jsonify(messages_history[-1])


# Tüm kayıtlı mesajlar
@app.route("/messages", methods=["GET"])
def get_all_messages():
    return jsonify({
        "count": len(messages_history),
        "messages": messages_history
    })


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp ESP32 sunucusu calisiyor."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
