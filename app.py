from flask import Flask, request, jsonify
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

app = Flask(__name__)

VERIFY_TOKEN = "akin123"
MAX_MESSAGES = 20
DEFAULT_DEVICE_LIMIT = 5

messages_history = []
message_counter = 0
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

TURKISH_MONTHS = [
    "Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
    "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"
]

TURKISH_DAYS = [
    "Pazartesi", "Sali", "Carsamba", "Persembe",
    "Cuma", "Cumartesi", "Pazar"
]


def parse_whatsapp_timestamp(raw_timestamp):
    """WhatsApp Unix zamanını UTC datetime'a dönüştürür."""
    try:
        return datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def format_turkish_datetime(utc_datetime):
    local_datetime = utc_datetime.astimezone(ISTANBUL_TZ)
    return (
        f"{local_datetime.day} "
        f"{TURKISH_MONTHS[local_datetime.month - 1]} "
        f"{TURKISH_DAYS[local_datetime.weekday()]} "
        f"{local_datetime:%H:%M}"
    )


def mask_sender(sender):
    sender = str(sender or "").strip()
    if not sender:
        return "Bilinmiyor"
    if len(sender) <= 2:
        return sender
    return "*" * (len(sender) - 2) + sender[-2:]


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

        for incoming in incoming_messages:
            sender = incoming.get("from", "")
            message_type = incoming.get("type", "")

            if message_type == "text":
                message_text = incoming.get("text", {}).get("body", "")
            else:
                message_text = f"[{message_type or 'bilinmeyen'} mesaj]"

            utc_datetime = parse_whatsapp_timestamp(incoming.get("timestamp"))
            message_counter += 1

            new_message = {
                "id": message_counter,
                "sender": sender,
                "masked_sender": mask_sender(sender),
                "message": message_text,
                "timestamp": utc_datetime.isoformat().replace("+00:00", "Z"),
                "display_time": format_turkish_datetime(utc_datetime),
            }

            messages_history.append(new_message)

            if len(messages_history) > MAX_MESSAGES:
                del messages_history[:-MAX_MESSAGES]

            print(f"Yeni mesaj: {new_message}")

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook verisi okunamadi:", error)

    return "EVENT_RECEIVED", 200


@app.route("/message", methods=["GET"])
def get_last_message():
    if not messages_history:
        return jsonify({
            "id": 0,
            "sender": "",
            "masked_sender": "",
            "message": "",
            "timestamp": "",
            "display_time": "",
        })

    return jsonify(messages_history[-1])


@app.route("/messages", methods=["GET"])
def get_all_messages():
    try:
        requested_limit = int(request.args.get("limit", DEFAULT_DEVICE_LIMIT))
    except (TypeError, ValueError):
        requested_limit = DEFAULT_DEVICE_LIMIT

    limit = max(1, min(requested_limit, MAX_MESSAGES))
    selected_messages = messages_history[-limit:]

    return jsonify({
        "count": len(selected_messages),
        "total_count": len(messages_history),
        "messages": selected_messages,
    })


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp ESP32 sunucusu calisiyor."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
