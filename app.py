import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)


# ----------------------------------------------------
# Ortam değişkenleri
# ----------------------------------------------------
VERIFY_TOKEN = os.getenv(
    "VERIFY_TOKEN",
    "akin-esp32-2026",
)

# Birden fazla yetkili numara virgülle ayrılır.
AUTHORIZED_NUMBERS = {
    number.strip()
    for number in os.getenv(
        "AUTHORIZED_NUMBERS",
        "905056352875,905056941962",
    ).split(",")
    if number.strip()
}

WHATSAPP_ACCESS_TOKEN = os.getenv(
    "WHATSAPP_ACCESS_TOKEN",
    "",
)

WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID",
    "",
)

GRAPH_API_VERSION = os.getenv(
    "GRAPH_API_VERSION",
    "",
)


# ----------------------------------------------------
# Genel ayarlar
# ----------------------------------------------------
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
MAX_MESSAGES = 5

stored_messages = []
message_counter = 0
stored_date = datetime.now(ISTANBUL_TZ).date()

last_webhook_payload = {}


# ----------------------------------------------------
# Tarih ve günlük sıfırlama
# ----------------------------------------------------
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
            f"Yeni gun basladi. Mesajlar sifirlandi: {today}",
            flush=True,
        )


# ----------------------------------------------------
# WhatsApp üzerinden cevap gönderme
# ----------------------------------------------------
def send_whatsapp_text(recipient, text):
    if not WHATSAPP_ACCESS_TOKEN:
        print(
            "WHATSAPP_ACCESS_TOKEN tanimlanmamis.",
            flush=True,
        )
        return False

    if not WHATSAPP_PHONE_NUMBER_ID:
        print(
            "WHATSAPP_PHONE_NUMBER_ID tanimlanmamis.",
            flush=True,
        )
        return False

    if not GRAPH_API_VERSION:
        print(
            "GRAPH_API_VERSION tanimlanmamis.",
            flush=True,
        )
        return False

    url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text,
        },
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=15,
        )

        print(
            f"WhatsApp cevap HTTP kodu: {response.status_code}",
            flush=True,
        )

        if not response.ok:
            print(
                f"WhatsApp cevap hatasi: {response.text}",
                flush=True,
            )
            return False

        print(
            f"WhatsApp cevabi gonderildi: {recipient}",
            flush=True,
        )
        return True

    except requests.RequestException as error:
        print(
            f"WhatsApp cevap baglanti hatasi: {error}",
            flush=True,
        )
        return False


# ----------------------------------------------------
# Mesaj listesini WhatsApp metnine çevirme
# ----------------------------------------------------
def build_list_text():
    reset_if_new_day()

    if not stored_messages:
        return (
            "📦 Bugün kayıtlı teslimat kodu bulunmuyor.\n\n"
            "Yeni bir kod eklemek için normal mesaj gönder."
        )

    lines = [
        "📦 Bugünkü Teslimat Kodları",
        "",
    ]

    for position, item in enumerate(stored_messages, start=1):
        message = item.get("message", "")
        lines.append(f"{position}. {message}")

    lines.append("")
    lines.append(f"Toplam: {len(stored_messages)} kayıt")

    return "\n".join(lines)


def build_help_text():
    return (
        "❓ Kullanılabilir Komutlar\n\n"
        "📋 LISTE\n"
        "Kayıtlı mesajları gösterir.\n\n"
        "📊 DURUM\n"
        "Bugünkü kayıt sayısını gösterir.\n\n"
        "🗑️ SIL\n"
        "Tüm kayıtları siler.\n\n"
        "🗑️ SIL 3\n"
        "Listedeki 3. kaydı siler.\n\n"
        "📩 Normal mesaj\n"
        "Mesajı teslimat kodu olarak listeye ekler."
    )


# ----------------------------------------------------
# Gelen WhatsApp mesajının içeriğini çıkarma
# ----------------------------------------------------
def extract_message_text(incoming):
    message_type = incoming.get("type", "unknown")

    if message_type == "text":
        return (
            incoming
            .get("text", {})
            .get("body", "")
            .strip()
        )

    if message_type == "button":
        return (
            incoming
            .get("button", {})
            .get("text", "[buton mesaji]")
            .strip()
        )

    if message_type == "interactive":
        interactive = incoming.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            return (
                interactive
                .get("button_reply", {})
                .get("title", "[buton cevabi]")
                .strip()
            )

        if interactive_type == "list_reply":
            return (
                interactive
                .get("list_reply", {})
                .get("title", "[liste cevabi]")
                .strip()
            )

        return "[etkilesimli mesaj]"

    if message_type == "image":
        caption = (
            incoming
            .get("image", {})
            .get("caption", "")
            .strip()
        )
        return caption or "[resim mesaji]"

    if message_type == "document":
        filename = (
            incoming
            .get("document", {})
            .get("filename", "")
        )

        if filename:
            return f"[dokuman: {filename}]"

        return "[dokuman mesaji]"

    if message_type == "audio":
        return "[ses mesaji]"

    if message_type == "video":
        caption = (
            incoming
            .get("video", {})
            .get("caption", "")
            .strip()
        )
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


# ----------------------------------------------------
# Listedeki tek mesajı silme
# ----------------------------------------------------
def delete_message_by_position(position):
    global stored_messages

    if position < 1 or position > len(stored_messages):
        return None

    deleted_message = stored_messages.pop(position - 1)

    print(
        f"Mesaj silindi. Sira: {position}, "
        f"Mesaj: {deleted_message}",
        flush=True,
    )

    return deleted_message


# ----------------------------------------------------
# WhatsApp uzaktan yönetim komutları
# ----------------------------------------------------
def process_remote_command(sender, message_text):
    global stored_messages
    global message_counter

    command = message_text.strip().upper()

    command_names = {
        "LISTE",
        "DURUM",
        "YARDIM",
        "SIL",
    }

    is_command = (
        command in command_names
        or command.startswith("SIL ")
    )

    # Normal mesajsa komut olarak işleme.
    if not is_command:
        return False

    # Komutları yalnızca yetkili numaralar kullanabilir.
    if sender not in AUTHORIZED_NUMBERS:
        print(
            f"Yetkisiz komut girisimi. Gonderen: {sender}",
            flush=True,
        )

        send_whatsapp_text(
            sender,
            "⛔ Bu numaranın yönetim komutlarını "
            "kullanma yetkisi yok.",
        )

        return True

    reset_if_new_day()

    if command == "LISTE":
        send_whatsapp_text(
            sender,
            build_list_text(),
        )
        return True

    if command == "DURUM":
        count = len(stored_messages)

        send_whatsapp_text(
            sender,
            (
                f"📊 Bugün {count} kayıt var.\n"
                f"📅 Tarih: {stored_date.strftime('%d.%m.%Y')}"
            ),
        )
        return True

    if command == "YARDIM":
        send_whatsapp_text(
            sender,
            build_help_text(),
        )
        return True

    if command == "SIL":
        deleted_count = len(stored_messages)

        stored_messages = []
        message_counter = 0

        send_whatsapp_text(
            sender,
            (
                "🗑️ Bugünkü tüm kayıtlar silindi.\n\n"
                f"Silinen kayıt sayısı: {deleted_count}"
            ),
        )

        print(
            f"Tum mesajlar uzaktan silindi. "
            f"Gonderen: {sender}",
            flush=True,
        )

        return True

    if command.startswith("SIL "):
        position_text = command[4:].strip()

        try:
            position = int(position_text)

        except ValueError:
            send_whatsapp_text(
                sender,
                (
                    "⚠️ Geçersiz silme komutu.\n\n"
                    "Örnek kullanım:\n"
                    "SIL 3"
                ),
            )
            return True

        deleted_message = delete_message_by_position(
            position
        )

        if deleted_message is None:
            send_whatsapp_text(
                sender,
                (
                    f"⚠️ {position} numaralı kayıt bulunamadı.\n\n"
                    f"Mevcut kayıt sayısı: "
                    f"{len(stored_messages)}"
                ),
            )
            return True

        deleted_text = deleted_message.get(
            "message",
            "",
        )

        response_text = (
            f"✅ {position} numaralı kayıt silindi.\n\n"
            f"Silinen kayıt:\n{deleted_text}\n\n"
            f"{build_list_text()}"
        )

        send_whatsapp_text(
            sender,
            response_text,
        )

        return True

    return False


# ----------------------------------------------------
# Ana sayfa
# ----------------------------------------------------
@app.get("/")
def home():
    reset_if_new_day()

    return jsonify(
        {
            "status": "ok",
            "message": "WhatsApp ESP32 sunucusu calisiyor.",
            "stored_message_count": len(stored_messages),
            "date": stored_date.isoformat(),
            "maximum_messages": MAX_MESSAGES,
        }
    ), 200


# ----------------------------------------------------
# Meta webhook doğrulama
# ----------------------------------------------------
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
        print(
            "Webhook basariyla dogrulandi.",
            flush=True,
        )
        return challenge or "", 200

    print(
        "Webhook dogrulamasi reddedildi.",
        flush=True,
    )

    return "Webhook dogrulanamadi.", 403


# ----------------------------------------------------
# Meta webhook mesajlarını alma
# ----------------------------------------------------
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
            f"Webhook JSON okunamadi. Ham veri: {raw_body}",
            flush=True,
        )

        return "EVENT_RECEIVED", 200

    last_webhook_payload = data

    print("=" * 40, flush=True)
    print("META WEBHOOK POST GELDI", flush=True)

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    print("=" * 40, flush=True)

    try:
        entries = data.get("entry", [])

        if not entries:
            print(
                "Webhook icinde entry bulunamadi.",
                flush=True,
            )

            return "EVENT_RECEIVED", 200

        for entry in entries:
            changes = entry.get("changes", [])

            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                if not messages:
                    statuses = value.get(
                        "statuses",
                        [],
                    )

                    if statuses:
                        print(
                            "Mesaj durum guncellemesi geldi.",
                            flush=True,
                        )

                    continue

                for incoming in messages:
                    sender = str(
                        incoming.get("from", "")
                    )

                    message_text = extract_message_text(
                        incoming
                    )

                    if not message_text:
                        print(
                            "Bos mesaj kaydedilmedi.",
                            flush=True,
                        )
                        continue

                    # Gelen içerik komutsa listeye ekleme.
                    if process_remote_command(
                        sender,
                        message_text,
                    ):
                        print(
                            f"Komut uygulandi: {message_text}",
                            flush=True,
                        )
                        continue

                    whatsapp_timestamp = incoming.get(
                        "timestamp"
                    )

                    if whatsapp_timestamp:
                        try:
                            received_at_utc = (
                                datetime.fromtimestamp(
                                    int(whatsapp_timestamp),
                                    tz=timezone.utc,
                                )
                            )

                            received_at = (
                                received_at_utc
                                .astimezone(ISTANBUL_TZ)
                                .isoformat()
                            )

                        except (
                            ValueError,
                            TypeError,
                            OverflowError,
                        ):
                            received_at = (
                                now_istanbul().isoformat()
                            )
                    else:
                        received_at = (
                            now_istanbul().isoformat()
                        )

                    message_counter += 1

                    new_message = {
                        "id": message_counter,
                        "sender": sender,
                        "message": message_text,
                        "received_at": received_at,
                    }

                    stored_messages.append(new_message)

                    # En fazla son 5 mesaj tutulur.
                    stored_messages = stored_messages[
                        -MAX_MESSAGES:
                    ]

                    print(
                        "Yeni WhatsApp mesaji kaydedildi:",
                        new_message,
                        flush=True,
                    )

    except Exception as error:
        print(
            f"Webhook isleme hatasi: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

    return "EVENT_RECEIVED", 200


# ----------------------------------------------------
# ESP32 için en fazla 5 mesajlık liste
# ----------------------------------------------------
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


# ----------------------------------------------------
# Eski ESP32 kodları için son mesaj endpoint'i
# ----------------------------------------------------
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


# ----------------------------------------------------
# Hata ayıklama adresleri
# ----------------------------------------------------
@app.get("/debug/last-webhook")
def get_last_webhook():
    return jsonify(last_webhook_payload), 200


@app.get("/debug/messages")
def debug_messages():
    reset_if_new_day()

    return jsonify(
        {
            "authorized_numbers": sorted(AUTHORIZED_NUMBERS),
            "count": len(stored_messages),
            "date": stored_date.isoformat(),
            "messages": stored_messages,
        }
    ), 200


# ----------------------------------------------------
# Uygulamayı çalıştır
# ----------------------------------------------------
if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
