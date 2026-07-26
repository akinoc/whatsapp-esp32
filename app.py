import json
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

last_webhook_payload = {}


@app.get("/")
def home():
    return jsonify(
        {
            "status": "ok",
            "message": "WhatsApp ESP32 sunucusu calisiyor.",
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


def extract_message_text(incoming):
    message_type = incoming.get("type", "unknown")

    if message_type == "text":
        return incoming.get("text", {}).get("body", "")

    if message_type == "button":
        return incoming.get("button", {}).get("text", "[buton mesaji]")

    if message_type == "interactive":
        interactive = incoming.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            return interactive.get("button_reply", {}).get(
                "title",
                "[buton cevabi]",
            )

        if interactive_type == "list_reply":
            return interactive.get("list_reply", {}).get(
                "title",
                "[liste cevabi]",
            )

        return "[etkilesimli mesaj]"

    if message_type == "image":
        caption = incoming.get("image", {}).get("caption", "")
        return caption or "[resim mesaji]"

    if message_type == "document":
        filename = incoming.get("document", {}).get("filename", "")
        return f"[dokuman: {filename}]" if filename else "[dokuman mesaji]"

    if message_type == "audio":
        return "[ses mesaji]"

    if message_type == "video":
        caption = incoming.get("video", {}).get("caption", "")
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


@app.post("/webhook")
def receive_webhook():
    global latest_message
    global last_webhook_payload

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
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
    print("========================================", flush=True)

    try:
        entries = data.get("entry", [])

        if not entries:
            print("Webhook icinde entry alani bulunamadi.", flush=True)
            return "EVENT_RECEIVED", 200

        message_found = False

        for entry in entries:
            changes = entry.get("changes", [])

            for change in changes:
                field = change.get("field", "")
                value = change.get("value", {})

                print(f"Webhook field: {field}", flush=True)

                messages = value.get("messages", [])

                if not messages:
                    statuses = value.get("statuses", [])

                    if statuses:
                        print(
                            "Bu webhook gelen mesaj degil, "
                            "mesaj durum guncellemesidir.",
                            flush=True,
                        )

                    continue

                for incoming in messages:
                    message_found = True

                    sender = incoming.get("from", "")
                    message_text = extract_message_text(incoming)

                    whatsapp_timestamp = incoming.get("timestamp")

                    if whatsapp_timestamp:
                        try:
                            received_at = datetime.fromtimestamp(
                                int(whatsapp_timestamp),
                                tz=timezone.utc,
                            ).isoformat()
                        except (ValueError, TypeError, OverflowError):
                            received_at = datetime.now(
                                timezone.utc
                            ).isoformat()
                    else:
                        received_at = datetime.now(
                            timezone.utc
                        ).isoformat()

                    latest_message = {
                        "id": latest_message["id"] + 1,
                        "sender": sender,
                        "message": message_text,
                        "received_at": received_at,
                    }

                    print(
                        "Yeni WhatsApp mesaji kaydedildi:",
                        latest_message,
                        flush=True,
                    )

        if not message_found:
            print(
                "Webhook geldi fakat icinde yeni bir WhatsApp "
                "mesaji bulunamadi.",
                flush=True,
            )

    except Exception as error:
        print(
            f"Webhook islenirken beklenmeyen hata olustu: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

    # Meta'ya hızlı biçimde 200 dönülmelidir.
    return "EVENT_RECEIVED", 200


@app.get("/message")
def get_message():
    response = jsonify(latest_message)

    # ESP32'nin eski sonucu önbellekten almaması için.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"

    return response, 200


@app.get("/debug/last-webhook")
def get_last_webhook():
    return jsonify(last_webhook_payload), 200


@app.post("/debug/test-message")
def create_test_message():
    global latest_message

    data = request.get_json(silent=True) or {}

    latest_message = {
        "id": latest_message["id"] + 1,
        "sender": data.get("sender", "test"),
        "message": data.get("message", "ESP32 test mesaji"),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    print("Manuel test mesaji olusturuldu:", latest_message, flush=True)

    return jsonify(latest_message), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
