import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "akin-esp32-2026")

# Silme komutlarını yalnızca bu numaradan kabul eder.
AUTHORIZED_NUMBER = os.getenv(
    "AUTHORIZED_NUMBER",
    "905056352875",
)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
MAX_MESSAGES = 5

stored_messages = []
message_counter = 0
stored_date = datetime.now(ISTANBUL_TZ).date()

last_webhook_payload = {}


def now_istanbul():
    return datetime.now(ISTANBUL_TZ)


def reset_if_new_day():
    global stored_messages
    global stored_date
    global message_counter

    today = now_istanbul().date()

    if today != stored_date:
        stored_messages = []
        message_counter = 0
        stored_date = today

        print(
            f"Yeni gun basladi. Mesaj listesi sifirlandi: {today}",
            flush=True,
        )


def extract_message_text(incoming):
    message_type = incoming.get("type", "unknown")

    if message_type == "text":
        return incoming.get("text", {}).get("body", "").strip()

    if message_type == "button":
        return incoming.get("button", {}).get(
            "text",
            "[buton mesaji]",
        ).strip()

    if message_type == "interactive":
        interactive = incoming.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            return interactive.get("button_reply", {}).get(
                "title",
                "[buton cevabi]",
            ).strip()

        if interactive_type == "list_reply":
            return interactive.get("list_reply", {}).get(
                "title",
                "[liste cevabi]",
            ).strip()

        return "[etkilesimli mesaj]"

    if message_type == "image":
        caption = incoming.get("image", {}).get("caption", "").strip()
        return caption or "[resim mesaji]"

    if message_type == "document":
        filename = incoming.get("document", {}).get("filename", "")
        return f"[dokuman: {filename}]" if filename else "[dokuman mesaji]"

    if message_type == "audio":
        return "[ses mesaji]"

    if message_type == "video":
        caption = incoming.get("video", {}).get("caption", "").strip()
        return caption or "[video mesaji]"

    if message_type == "location":
        location = incoming.get("location", {})
        latitude = location.get("latitude", "")
        longitude = location.get("longitude", "")
        return f"[konum: {latitude}, {longitude}]"

    if message_type == "contacts":
        return "[kisi mesaji]"

    if message_type == "sticker":
        return "[cikartma mesaji]"

    return f"[{message_type} mesaji]"


def delete_message_by_position(position):
    global stored_messages

    if position < 1 or position > len(stored_messages):
        return False

    deleted_message = stored_messages.pop(position - 1)

    print(
        f"Mesaj silindi. Sira: {position}, Veri: {deleted_message}",
        flush=True,
    )

    return True


def process_remote_command(sender, message_text):
    global stored_messages
    global message_counter

    if sender != AUTHORIZED_NUMBER:
        return False

    command = message_text.strip().upper()

    if command == "SIL":
        stored_messages = []
        message_counter = 0

        print(
            f"Tum mesajlar uzaktan silindi. Gonderen: {sender}",
            flush=True,
        )

        return True

    if command.startswith("SIL "):
        number_text = command[4:].strip()

        try:
            position = int(number_text)
        except ValueError:
            print(
                f"Gecersiz SIL komutu: {message_text}",
                flush=True,
            )
            return True

        if not delete_message_by_position(position):
            print(
                f"Silinecek mesaj bulunamadi. Sira: {position}",
                flush=True,
            )

        return True

    if command == "LISTE":
        print(
            f"LISTE komutu alindi. Kayitli mesaj sayisi: "
            f"{len(stored_messages)}",
            flush=True,
        )
        return True

    return False


@app.get("/")
def home():
    reset_if_new_day()

    return jsonify(
        {
            "status": "ok",
            "message": "WhatsApp ESP32 sunucusu calisiyor.",
            "stored_message_count": len(stored_messages),
            "date": stored_date.isoformat(),
        }
    ), 200


@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    print(
        f"Webhook dogrulama istegi: mode={mode}, "
        f"token_eslesiyor={token == VERIFY_TOKEN}",
        flush=True,
    )

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook basariyla dogrulandi.", flush=True)
        return challenge or "", 200

    print("Webhook dogrulamasi reddedildi.", flush=True)
    return "Webhook dogrulanamadi.", 403


@app.post("/webhook")
def receive_webhook():
    global stored_messages
    global message_counter
    global last_webhook_payload

    reset_if_new_day()

    data = request.get_json(silent=True)

    if data is None:
        raw_body = request.get_data(as_text=True)

        print(
            f"Webhook JSON olarak okunamadi. Ham veri: {raw_body}",
            flush=True,
        )

        return "EVENT_RECEIVED", 200

    last_webhook_payload = data

    print("========================================", flush=True)
    print("META WEBHOOK POST GELDI", flush=True)
    print(
        json.dumps(data, ensure_ascii=False, indent=2),
        flush=True,
    )
    print("========================================", flush=True)

    try:
        entries = data.get("entry", [])

        if not entries:
            print(
                "Webhook icinde entry alani bulunamadi.",
                flush=True,
            )
            return "EVENT_RECEIVED", 200

        message_found = False

        for entry in entries:
            changes = entry.get("changes", [])

            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                if not messages:
                    statuses = value.get("statuses", [])

                    if statuses:
                        print(
                            "Mesaj durum guncellemesi geldi.",
                            flush=True,
                        )

                    continue

                for incoming in messages:
                    message_found = True

                    sender = incoming.get("from", "")
                    message_text = extract_message_text(incoming)

                    if not message_text:
                        print(
                            "Bos mesaj alindi, kaydedilmedi.",
                            flush=True,
                        )
                        continue

                    if process_remote_command(
                        sender,
                        message_text,
                    ):
                        print(
                            f"Uzaktan komut uygulandi: "
                            f"{message_text}",
                            flush=True,
                        )
                        continue

                    whatsapp_timestamp = incoming.get("timestamp")

                    if whatsapp_timestamp:
                        try:
                            received_at_utc = datetime.fromtimestamp(
                                int(whatsapp_timestamp),
                                tz=timezone.utc,
                            )
                            received_at = received_at_utc.astimezone(
                                ISTANBUL_TZ
                            ).isoformat()
                        except (
                            ValueError,
                            TypeError,
                            OverflowError,
                        ):
                            received_at = now_istanbul().isoformat()
                    else:
                        received_at = now_istanbul().isoformat()

                    message_counter += 1

                    new_message = {
                        "id": message_counter,
                        "sender": sender,
                        "message": message_text,
                        "received_at": received_at,
                    }

                    stored_messages.append(new_message)

                    # En fazla son 5 mesaj tutulur.
                    stored_messages = stored_messages[-MAX_MESSAGES:]

                    print(
                        "Yeni WhatsApp mesaji kaydedildi:",
                        new_message,
                        flush=True,
                    )

        if not message_found:
            print(
                "Webhook geldi fakat yeni mesaj bulunamadi.",
                flush=True,
            )

    except Exception as error:
        print(
            f"Webhook islenirken hata olustu: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

    return "EVENT_RECEIVED", 200


@app.get("/messages")
def get_messages():
    reset_if_new_day()

    response = jsonify(
        {
            "count": len(stored_messages),
            "date": stored_date.isoformat(),
            "messages": stored_messages,
        }
    )

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"

    return response, 200


@app.get("/message")
def get_last_message():
    reset_if_new_day()

    if stored_messages:
        latest_message = stored_messages[-1]
    else:
        latest_message = {
            "id": 0,
            "sender": "",
            "message": "",
            "received_at": "",
        }

    response = jsonify(latest_message)

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"

    return response, 200


@app.get("/debug/last-webhook")
def get_last_webhook():
    return jsonify(last_webhook_payload), 200


@app.get("/debug/messages")
def debug_messages():
    reset_if_new_day()

    return jsonify(
        {
            "authorized_number": AUTHORIZED_NUMBER,
            "count": len(stored_messages),
            "date": stored_date.isoformat(),
            "messages": stored_messages,
        }
    ), 200


@app.post("/debug/test-message")
def create_test_message():
    global stored_messages
    global message_counter

    reset_if_new_day()

    data = request.get_json(silent=True) or {}

    sender = str(data.get("sender", "test"))
    message_text = str(
        data.get("message", "ESP32 test mesaji")
    ).strip()

    message_counter += 1

    new_message = {
        "id": message_counter,
        "sender": sender,
        "message": message_text,
        "received_at": now_istanbul().isoformat(),
    }

    stored_messages.append(new_message)
    stored_messages = stored_messages[-MAX_MESSAGES:]

    print(
        "Manuel test mesaji olusturuldu:",
        new_message,
        flush=True,
    )

    return jsonify(new_message), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
    )
