import argparse
import requests
import json
import logging
import schedule
import time
import hashlib
from datetime import datetime, timedelta
from config import (
    TICKETMASTER_API_KEY,
    EVENT_ID,
    NTFY_URL,
    NTFY_PRIORITY,
    NTFY_TAGS,
    HEARTBEAT_ENABLED,
    HEARTBEAT_INTERVAL_MINUTES,
    HEARTBEAT_PRIORITY,
    HEARTBEAT_TAGS,
    CHECK_INTERVAL_MINUTES,
    HOT_CHECK_INTERVAL_MINUTES,
    HOT_WINDOW_DAYS_BEFORE_EVENT,
    GITHUB_ACTIONS_MODE,
    LOG_FILE,
    STATE_FILE
)

# Setup logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def timestamp_now():
    """Return formatted current timestamp."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def search_events(keyword="BTS", country_code="CO", city="Bogotá"):
    """Search for events using Ticketmaster API. Returns list of events."""
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        "apikey": TICKETMASTER_API_KEY,
        "keyword": keyword,
        "countryCode": country_code,
        "city": city,
        "size": 20
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        events = data.get("_embedded", {}).get("events", [])
        return events, None
    except Exception as e:
        logging.error(f"Error searching events: {e}")
        return [], str(e)

def normalize_event_data(event):
    """Normalize event data into a stable snapshot for comparison."""
    dates = event.get("dates", {})
    sales = event.get("sales", {})

    normalized = {
        "id": event.get("id"),
        "name": event.get("name"),
        "url": event.get("url"),
        "status": event.get("status"),
        "event_date": dates.get("start", {}).get("localDate") if dates else None,
        "public_sale_start": sales.get("public", {}).get("startDateTime") if sales else None,
        "public_sale_end": sales.get("public", {}).get("endDateTime") if sales else None,
        "presale_start": sales.get("presales", [{}])[0].get("startDateTime") if sales.get("presales") else None,
        "presale_end": sales.get("presales", [{}])[0].get("endDateTime") if sales.get("presales") else None,
        "on_sale": event.get("onSaleStartDate"),
        "test": event.get("test"),
    }
    return normalized

def calculate_hash(events_list):
    """Calculate hash of normalized events list."""
    normalized = [normalize_event_data(e) for e in events_list]
    json_str = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()

def load_state():
    """Load state from state.json file with default fallbacks."""
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}

    defaults = {
        "hash": None,
        "event_count": 0,
        "last_check": None,
        "last_heartbeat_sent": None,
        "last_check_summary": {
            "checked_at": None,
            "events_found": 0,
            "changed": False,
            "change_type": "none",
            "alert_sent": False,
            "api_error": None,
            "message": None
        }
    }

    for key, default_value in defaults.items():
        if key not in state:
            state[key] = default_value

    return state

def save_state(current_hash, event_count, last_check_summary, last_heartbeat_sent=None):
    """Save state to state.json file."""
    state = load_state()
    state["hash"] = current_hash
    state["event_count"] = event_count
    state["last_check"] = timestamp_now()
    state["last_check_summary"] = last_check_summary

    if last_heartbeat_sent is not None:
        state["last_heartbeat_sent"] = last_heartbeat_sent

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def should_send_heartbeat(state):
    """Check if heartbeat interval has passed since last heartbeat."""
    if not HEARTBEAT_ENABLED:
        return False

    # En GitHub Actions siempre se envía heartbeat (si no se envió alerta principal)
    if GITHUB_ACTIONS_MODE:
        return True

    last_heartbeat_sent = state.get("last_heartbeat_sent")

    if last_heartbeat_sent is None:
        return True

    try:
        last_time = datetime.strptime(last_heartbeat_sent, "%Y-%m-%d %H:%M:%S")
        time_since = datetime.now() - last_time
        minutes_since = time_since.total_seconds() / 60
        return minutes_since >= HEARTBEAT_INTERVAL_MINUTES
    except ValueError:
        return True

def build_heartbeat_message(summary):
    """Build heartbeat summary message in Spanish."""
    change_type = summary.get("change_type", "none")
    change_type_map = {
        "none": "Ninguno",
        "new_event": "Eventos nuevos encontrados",
        "event_disappeared": "Evento desapareció",
        "event_updated": "Evento actualizado",
    }
    change_label = change_type_map.get(change_type, change_type)

    # Indicar si es ejecución automática de GitHub Actions
    origin = "☁️ GitHub Actions" if GITHUB_ACTIONS_MODE else "💻 Local"

    message = f"""✅ BTS Ticketmaster Monitor activo

✏️ Última consulta: {summary.get('checked_at', 'Sin datos')}
📃 Eventos encontrados: {summary.get('events_found', 0)}
🔄 Cambio detectado: {'Sí' if summary.get('changed') else 'No'}
📧 Tipo de cambio: {change_label}
📢 Alerta principal: {'Enviada' if summary.get('alert_sent') else 'No'}
⚠️ Error API: {summary.get('api_error') or 'Ninguno'}
🖥️ Origen: {origin}

⏳ Próxima acción: Seguir monitoreando..."""

    return message

def send_ntfy_alert(message, priority=None, tags=None):
    """Send push notification using ntfy with optional custom priority/tags."""
    use_priority = priority if priority is not None else NTFY_PRIORITY
    use_tags = tags if tags is not None else NTFY_TAGS

    try:
        response = requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": "BTS Ticketmaster Monitor",
                "Priority": use_priority,
                "Tags": use_tags,
                "Content-Type": "text/plain; charset=utf-8"
            },
            timeout=20
        )
        response.raise_for_status()
        logging.info("ntfy alert sent successfully")
        print("✅ ntfy alert sent")
        return True
    except Exception as e:
        logging.error(f"Error sending ntfy alert: {e}")
        print(f"❌ Error sending ntfy: {e}")
        return False

def check_for_changes():
    """Check Ticketmaster for BTS events and detect changes. Returns structured result."""
    print(f"\n[{timestamp_now()}] Checking Ticketmaster...")

    events, api_error = search_events(keyword="BTS", country_code="CO", city="Bogotá")
    current_hash = calculate_hash(events)
    previous_state = load_state()
    previous_hash = previous_state.get("hash")
    previous_count = previous_state.get("event_count", 0)

    print(f"Events found: {len(events)}")

    result = {
        "changed": False,
        "message": None,
        "events_found": len(events),
        "change_type": "none",
        "api_error": api_error,
        "checked_at": timestamp_now()
    }

    if api_error:
        print(f"❌ API error: {api_error}")
        result["message"] = f"❌ Error consultando Ticketmaster: {api_error}"
        return result

    if len(events) == 0 and previous_count > 0:
        result["changed"] = True
        result["change_type"] = "event_disappeared"
        result["message"] = "⚠️ Los eventos BTS ya no están disponibles en Ticketmaster!"
        print("⚠️ Change detected: Events disappeared")

    elif len(events) > 0 and previous_count == 0:
        result["changed"] = True
        result["change_type"] = "new_event"
        event = events[0]
        event_name = event.get("name", "Unknown")
        event_date = event.get("dates", {}).get("start", {}).get("localDate", "TBA")
        result["message"] = f"🎫 NUEVO EVENTO: {event_name}\n📅 Fecha: {event_date}"
        print("✅ Change detected: New events found")

    elif current_hash != previous_hash and len(events) > 0:
        result["changed"] = True
        result["change_type"] = "event_updated"
        event = events[0]
        event_name = event.get("name", "Unknown")
        sales = event.get("sales", {})
        public_sales = sales.get("public", {}) if sales else {}
        start_date_sales = public_sales.get("startDateTime", "N/A") if public_sales else "N/A"

        if start_date_sales != "N/A":
            result["message"] = f"🔔 ACTUALIZACIÓN: {event_name}\n💫 Venta iniciada: {start_date_sales}"
        else:
            result["message"] = f"🔔 EVENTO ACTUALIZADO: {event_name}"
        print("🔄 Change detected: Event data changed")

    else:
        print("✓ No changes")

    return result

def validate_config():
    """Validate required configuration."""
    issues = []

    if TICKETMASTER_API_KEY == "YOUR_API_KEY_HERE":
        issues.append("ERROR: Set TICKETMASTER_API_KEY in config.py")

    if not NTFY_URL or not NTFY_URL.startswith("https://ntfy.sh/"):
        issues.append("ERROR: NTFY_URL must be set to a valid https://ntfy.sh/ URL in config.py")

    if issues:
        for issue in issues:
            print(issue)
            logging.error(issue)
        return False
    return True

def run_check_once():
    """Run one check and exit (main mode for GitHub Actions and Task Scheduler)."""
    print(f"\n{'='*60}")
    print(f"BTS Ticketmaster Monitor - Single Check")
    print(f"Started: {timestamp_now()}")
    print(f"Mode: {'☁️ GitHub Actions' if GITHUB_ACTIONS_MODE else '💻 Local'}")
    print(f"{'='*60}")

    if not validate_config():
        return

    state = load_state()
    result = check_for_changes()

    alert_sent = False
    last_heartbeat_to_save = None

    # Prioridad 1: alerta de cambio real
    if result["changed"] and result["message"]:
        print(f"\n📢 Sending main alert to ntfy...")
        send_ntfy_alert(result["message"])
        result["alert_sent"] = True
        alert_sent = True
        last_heartbeat_to_save = timestamp_now()
        print("\nHeartbeat timestamp updated (main alert sent)")
    else:
        result["alert_sent"] = False

    # Prioridad 2: heartbeat
    # En GitHub Actions: siempre (cada run confirma que el pipeline está vivo)
    # En local: solo si pasó el intervalo configurado
    if not alert_sent and should_send_heartbeat(state):
        print(f"\n🔔 Sending heartbeat notification...")
        heartbeat_msg = build_heartbeat_message(result)
        send_ntfy_alert(heartbeat_msg, priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
        last_heartbeat_to_save = timestamp_now()
        print("Heartbeat sent")

    # Guardar estado
    events, _ = search_events()
    save_state(calculate_hash(events), result["events_found"], result,
               last_heartbeat_sent=last_heartbeat_to_save)

    print(f"\nCheck completed at {timestamp_now()}")
    print(f"{'='*60}\n")

def run_daemon():
    """Run as daemon with periodic checks (local use)."""
    print(f"\n{'='*60}")
    print(f"BTS Ticketmaster Monitor - Daemon Mode")
    print(f"Started: {timestamp_now()}")
    print(f"Normal interval: {CHECK_INTERVAL_MINUTES} min")
    print(f"Hot interval: {HOT_CHECK_INTERVAL_MINUTES} min (within {HOT_WINDOW_DAYS_BEFORE_EVENT} days of event)")
    print(f"Heartbeat: Every {HEARTBEAT_INTERVAL_MINUTES} min (if no main alert)")
    print(f"{'='*60}")

    if not validate_config():
        return

    def scheduled_check():
        state = load_state()
        result = check_for_changes()

        alert_sent = False
        last_heartbeat_to_save = None

        if result["changed"] and result["message"]:
            print(f"\n📢 Sending main alert...")
            send_ntfy_alert(result["message"])
            result["alert_sent"] = True
            alert_sent = True
            last_heartbeat_to_save = timestamp_now()
        else:
            result["alert_sent"] = False

        if not alert_sent and should_send_heartbeat(state):
            print(f"\n🔔 Sending heartbeat notification...")
            heartbeat_msg = build_heartbeat_message(result)
            send_ntfy_alert(heartbeat_msg, priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
            last_heartbeat_to_save = timestamp_now()

        events, _ = search_events()
        save_state(calculate_hash(events), result["events_found"], result,
                   last_heartbeat_sent=last_heartbeat_to_save)

    scheduled_check()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(scheduled_check)

    print("\nMonitor running. Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print(f"\n\nMonitor stopped at {timestamp_now()}")
        logging.info("Monitor stopped by user")

def main():
    parser = argparse.ArgumentParser(
        description="Ticketmaster BTS Bogotá Change Monitor with Heartbeat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --test-alert         # Send test change alert
  python main.py --test-heartbeat     # Send test heartbeat
  python main.py --check-once         # Run one check (for GitHub Actions / Task Scheduler)
  python main.py --daemon             # Run continuously (local only)
        """
    )
    parser.add_argument("--test-alert", action="store_true",
                        help="Send a test change alert and exit")
    parser.add_argument("--test-heartbeat", action="store_true",
                        help="Send a test heartbeat notification and exit")
    parser.add_argument("--check-once", action="store_true",
                        help="Run one check, update state, and exit")
    parser.add_argument("--daemon", action="store_true",
                        help="Run as daemon with periodic checks (local only)")

    args = parser.parse_args()

    if args.test_alert:
        send_ntfy_alert("✅ Prueba BTS Monitor: ntfy funcionando correctamente")
        return

    if args.test_heartbeat:
        test_summary = {
            "checked_at": timestamp_now(),
            "events_found": 0,
            "changed": False,
            "change_type": "none",
            "alert_sent": False,
            "api_error": None,
            "message": None
        }
        msg = build_heartbeat_message(test_summary)
        send_ntfy_alert(msg, priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
        return

    if args.check_once:
        run_check_once()
        return

    if args.daemon:
        run_daemon()
        return

    run_daemon()

if __name__ == "__main__":
    main()
