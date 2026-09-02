from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import urllib.request
import urllib.error

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "akin123")
MESSAGE_RETENTION_HOURS = 24
DEFAULT_DEVICE_LIMIT = 5

# WhatsApp Cloud API ayarlari.
# Render > Environment bolumune ekle:
# WHATSAPP_ACCESS_TOKEN      = Meta access token
# WHATSAPP_PHONE_NUMBER_ID   = WhatsApp Phone Number ID
# GRAPH_API_VERSION   = v23.0   (istersen degistirebilirsin)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")

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
    """WhatsApp Unix zamanini UTC datetime'a donusturur."""
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
    if len(sender) <= 4:
        return sender
    return "*" * (len(sender) - 4) + sender[-4:]


def normalize_command(text):
    """Komut kontrolu icin metni Turkce karakterleri de dikkate alarak normalize eder."""
    text = str(text or "").strip().upper()

    replacements = str.maketrans({
        "İ": "I",
        "I": "I",
        "Ş": "S",
        "Ğ": "G",
        "Ü": "U",
        "Ö": "O",
        "Ç": "C",
    })
    return text.translate(replacements)


def send_whatsapp_text(to_number, text):
    """
    WhatsApp Cloud API ile metin cevabi gonderir.
    Token veya Phone Number ID yoksa uygulama cokmez; sadece log basar.
    """
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(
            "WhatsApp cevabi gonderilemedi: "
            "WHATSAPP_ACCESS_TOKEN veya WHATSAPP_PHONE_NUMBER_ID tanimli degil."
        )
        return False

    url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    )

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": str(to_number),
        "type": "text",
        "text": {
            "preview_url": False,
            "body": str(text),
        },
    }

    request_data = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request_data, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(
                f"WhatsApp cevabi gonderildi -> {mask_sender(to_number)} "
                f"HTTP {response.status}: {response_body}"
            )
            return 200 <= response.status < 300

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        print(
            f"WhatsApp API HTTP hatasi {error.code}: {error_body}"
        )
    except Exception as error:
        print(f"WhatsApp API gonderim hatasi: {error}")

    return False



def prune_old_messages():
    """24 saatten eski mesajlari bellekten siler."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MESSAGE_RETENTION_HOURS)

    kept_messages = []
    for item in messages_history:
        try:
            item_time = datetime.fromisoformat(
                str(item.get("timestamp", "")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue

        if item_time >= cutoff:
            kept_messages.append(item)

    messages_history[:] = kept_messages


def build_help_text():
    return (
        "Kullanilabilir komutlar:\n"
        "\n"
        "YARDIM - Bu yardim ekranini gosterir.\n"
        "LISTE - Kayitli mesajlari listeler.\n"
        "SIL <ID> - Belirtilen ID'li mesaji siler.\n"
        "SIL - Son kayitli mesaji siler.\n"
        "TEMIZLE - Tum kayitli mesajlari siler.\n"
        "\n"
        "Ornek: SIL 12"
    )


def build_list_text():
    prune_old_messages()

    if not messages_history:
        return "Kayitli mesaj bulunmuyor."

    lines = [f"Son {MESSAGE_RETENTION_HOURS} saatteki mesajlar ({len(messages_history)}):"]

    for item in messages_history:
        message = str(item.get("message", "")).replace("\n", " ").strip()
        if len(message) > 80:
            message = message[:77] + "..."

        lines.append(
            f"{item.get('id', '?')} - "
            f"{item.get('display_time', '')} - "
            f"{item.get('masked_sender', '')} - "
            f"{message}"
        )

    return "\n".join(lines)


def delete_message_by_id(message_id):
    for index, item in enumerate(messages_history):
        if item.get("id") == message_id:
            return messages_history.pop(index)
    return None


def handle_command(sender, message_text):
    """
    Komutsa islemi yapar ve True doner.
    Boylece YARDIM/LISTE/SIL/TEMIZLE komutlari ekranda normal mesaj olarak gorunmez.
    """
    prune_old_messages()
    command = normalize_command(message_text)

    if command == "YARDIM":
        print(f"YARDIM komutu alindi -> {mask_sender(sender)}")
        send_whatsapp_text(sender, build_help_text())
        return True

    if command == "LISTE":
        print(
            f"LISTE komutu alindi. Kayitli mesaj sayisi: "
            f"{len(messages_history)}"
        )
        send_whatsapp_text(sender, build_list_text())
        return True

    if command == "SIL":
        if not messages_history:
            reply = "Silinecek kayitli mesaj bulunmuyor."
        else:
            deleted = messages_history.pop()
            reply = (
                f"Son mesaj silindi.\n"
                f"ID: {deleted.get('id')}\n"
                f"Mesaj: {deleted.get('message', '')}"
            )

        print(f"SIL komutu alindi -> {reply}")
        send_whatsapp_text(sender, reply)
        return True

    if command.startswith("SIL "):
        parts = command.split(maxsplit=1)

        try:
            message_id = int(parts[1])
        except (IndexError, ValueError):
            send_whatsapp_text(
                sender,
                "Gecersiz SIL komutu. Ornek kullanim: SIL 12"
            )
            return True

        deleted = delete_message_by_id(message_id)

        if deleted:
            reply = (
                f"Mesaj silindi.\n"
                f"ID: {deleted.get('id')}\n"
                f"Mesaj: {deleted.get('message', '')}"
            )
        else:
            reply = f"ID {message_id} ile kayitli mesaj bulunamadi."

        print(f"SIL {message_id} komutu alindi -> {reply}")
        send_whatsapp_text(sender, reply)
        return True

    if command in ("TEMIZLE", "TEMİZLE"):
        count = len(messages_history)
        messages_history.clear()

        reply = f"{count} kayit silindi. Mesaj listesi temizlendi."
        print(f"TEMIZLE komutu alindi -> {count} mesaj silindi.")
        send_whatsapp_text(sender, reply)
        return True

    return False


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

            # Komutlar normal mesaj listesine eklenmez.
            if message_type == "text" and handle_command(sender, message_text):
                continue

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
            prune_old_messages()

            print(f"Yeni mesaj: {new_message}")

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook verisi okunamadi:", error)

    return "EVENT_RECEIVED", 200


@app.route("/message", methods=["GET"])
def get_last_message():
    prune_old_messages()

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
    prune_old_messages()

    all_requested = str(request.args.get("all", "")).strip().lower() in (
        "1", "true", "yes", "evet"
    )

    try:
        requested_limit = int(
            request.args.get("limit", DEFAULT_DEVICE_LIMIT)
        )
    except (TypeError, ValueError):
        requested_limit = DEFAULT_DEVICE_LIMIT

    # /messages?all=1 veya /messages?limit=0 -> son 24 saatin TAMAMI
    if all_requested or requested_limit == 0:
        selected_messages = list(messages_history)
    else:
        limit = max(1, requested_limit)
        selected_messages = messages_history[-limit:]

    return jsonify({
        "count": len(selected_messages),
        "total_count": len(messages_history),
        "retention_hours": MESSAGE_RETENTION_HOURS,
        "messages": selected_messages,
    })


@app.route("/", methods=["GET"])
def home():
    return "WhatsApp ESP32 sunucusu calisiyor."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
