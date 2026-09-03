from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import sqlite3
import urllib.request
import urllib.error

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "akin123")
DEFAULT_DEVICE_LIMIT = 5
DB_PATH = os.getenv("DB_PATH", "/var/data/messages.db")

# WhatsApp Cloud API ayarlari.
# Render > Environment bolumune ekle:
# WHATSAPP_ACCESS_TOKEN      = Meta access token
# WHATSAPP_PHONE_NUMBER_ID   = WhatsApp Phone Number ID
# GRAPH_API_VERSION   = v23.0   (istersen degistirebilirsin)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

TURKISH_MONTHS = [
    "Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
    "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"
]

TURKISH_DAYS = [
    "Pazartesi", "Sali", "Carsamba", "Persembe",
    "Cuma", "Cumartesi", "Pazar"
]



def get_db():
    """SQLite baglantisi acar. Render Persistent Disk kullaniliyorsa veri restartta da korunur."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                masked_sender TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                display_time TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_timestamp "
            "ON messages(timestamp)"
        )


def today_start_utc():
    """Istanbul saatine gore bugunun 00:00 anini UTC olarak dondurur."""
    now_local = datetime.now(ISTANBUL_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def tomorrow_start_utc():
    """Istanbul saatine gore yarinin 00:00 anini UTC olarak dondurur."""
    return today_start_utc() + timedelta(days=1)


def cleanup_previous_days():
    """Istanbul saatine gore bugun 00:00'dan eski tum mesajlari siler."""
    cutoff = today_start_utc().isoformat().replace("+00:00", "Z")
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))


def row_to_dict(row):
    return {
        "id": row["id"],
        "sender": row["sender"],
        "masked_sender": row["masked_sender"],
        "message": row["message"],
        "timestamp": row["timestamp"],
        "display_time": row["display_time"],
    }


def get_today_messages(limit=None):
    cleanup_previous_days()
    start = today_start_utc().isoformat().replace("+00:00", "Z")
    end = tomorrow_start_utc().isoformat().replace("+00:00", "Z")

    sql = """
        SELECT id, sender, masked_sender, message, timestamp, display_time
        FROM messages
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY id ASC
    """
    params = [start, end]

    if limit is not None and limit > 0:
        sql = """
            SELECT id, sender, masked_sender, message, timestamp, display_time
            FROM (
                SELECT id, sender, masked_sender, message, timestamp, display_time
                FROM messages
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
        """
        params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [row_to_dict(row) for row in rows]


def insert_message(sender, masked_sender, message, timestamp, display_time):
    cleanup_previous_days()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages
                (sender, masked_sender, message, timestamp, display_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sender, masked_sender, message, timestamp, display_time),
        )
        message_id = cursor.lastrowid

    return message_id


def delete_message_by_id_db(message_id):
    cleanup_previous_days()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, sender, masked_sender, message, timestamp, display_time
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()

        if row is None:
            return None

        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        return row_to_dict(row)


def delete_last_message_db():
    cleanup_previous_days()
    messages = get_today_messages()
    if not messages:
        return None
    return delete_message_by_id_db(messages[-1]["id"])


def clear_today_messages():
    cleanup_previous_days()
    start = today_start_utc().isoformat().replace("+00:00", "Z")
    end = tomorrow_start_utc().isoformat().replace("+00:00", "Z")

    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE timestamp >= ? AND timestamp < ?",
            (start, end),
        ).fetchone()[0]

        conn.execute(
            "DELETE FROM messages WHERE timestamp >= ? AND timestamp < ?",
            (start, end),
        )

    return count


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
    messages = get_today_messages()

    if not messages:
        return "Bugune ait kayitli mesaj bulunmuyor."

    lines = [f"Bugunun kayitli mesajlari ({len(messages)}):"]

    for item in messages:
        message = str(item.get("message", "")).replace("
", " ").strip()
        if len(message) > 80:
            message = message[:77] + "..."

        lines.append(
            f"{item.get('id', '?')} - "
            f"{item.get('display_time', '')} - "
            f"{item.get('masked_sender', '')} - "
            f"{message}"
        )

    return "
".join(lines)




def handle_command(sender, message_text):
    """
    Komutsa islemi yapar ve True doner.
    YARDIM/LISTE/SIL/TEMIZLE komutlari ekranda normal mesaj olarak gorunmez.
    """
    cleanup_previous_days()
    command = normalize_command(message_text)

    if command == "YARDIM":
        print(f"YARDIM komutu alindi -> {mask_sender(sender)}")
        send_whatsapp_text(sender, build_help_text())
        return True

    if command == "LISTE":
        messages = get_today_messages()
        print(f"LISTE komutu alindi. Bugunku mesaj sayisi: {len(messages)}")
        send_whatsapp_text(sender, build_list_text())
        return True

    if command == "SIL":
        deleted = delete_last_message_db()

        if deleted is None:
            reply = "Silinecek kayitli mesaj bulunmuyor."
        else:
            reply = (
                f"Son mesaj silindi.
"
                f"ID: {deleted.get('id')}
"
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

        deleted = delete_message_by_id_db(message_id)

        if deleted:
            reply = (
                f"Mesaj silindi.
"
                f"ID: {deleted.get('id')}
"
                f"Mesaj: {deleted.get('message', '')}"
            )
        else:
            reply = f"ID {message_id} ile bugune ait kayitli mesaj bulunamadi."

        print(f"SIL {message_id} komutu alindi -> {reply}")
        send_whatsapp_text(sender, reply)
        return True

    if command in ("TEMIZLE", "TEMİZLE"):
        count = clear_today_messages()
        reply = f"{count} kayit silindi. Bugunun mesaj listesi temizlendi."
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

            timestamp = utc_datetime.isoformat().replace("+00:00", "Z")
            display_time = format_turkish_datetime(utc_datetime)
            masked_sender = mask_sender(sender)

            message_id = insert_message(
                sender=sender,
                masked_sender=masked_sender,
                message=message_text,
                timestamp=timestamp,
                display_time=display_time,
            )

            new_message = {
                "id": message_id,
                "sender": sender,
                "masked_sender": masked_sender,
                "message": message_text,
                "timestamp": timestamp,
                "display_time": display_time,
            }

            print(f"Yeni mesaj: {new_message}")

    except (KeyError, IndexError, TypeError) as error:
        print("Webhook verisi okunamadi:", error)

    return "EVENT_RECEIVED", 200


@app.route("/message", methods=["GET"])
def get_last_message():
    messages = get_today_messages(limit=1)

    if not messages:
        return jsonify({
            "id": 0,
            "sender": "",
            "masked_sender": "",
            "message": "",
            "timestamp": "",
            "display_time": "",
        })

    return jsonify(messages[-1])



@app.route("/messages", methods=["GET"])
def get_all_messages():
    cleanup_previous_days()

    all_requested = str(request.args.get("all", "")).strip().lower() in (
        "1", "true", "yes", "evet"
    )

    try:
        requested_limit = int(
            request.args.get("limit", DEFAULT_DEVICE_LIMIT)
        )
    except (TypeError, ValueError):
        requested_limit = DEFAULT_DEVICE_LIMIT

    if all_requested or requested_limit == 0:
        selected_messages = get_today_messages()
    else:
        selected_messages = get_today_messages(limit=max(1, requested_limit))

    total_count = len(get_today_messages())

    return jsonify({
        "count": len(selected_messages),
        "total_count": total_count,
        "day_reset": "Europe/Istanbul 00:00",
        "messages": selected_messages,
    })



init_db()
cleanup_previous_days()

@app.route("/", methods=["GET"])
def home():
    return "WhatsApp ESP32 sunucusu calisiyor."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
