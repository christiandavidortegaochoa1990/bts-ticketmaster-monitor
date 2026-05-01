import argparse
import requests
import json
import logging
import schedule
import time
import hashlib
from datetime import datetime
from config import (
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

import re

def extract_stable_content(html: str) -> str:
    """Elimina partes dinámicas del HTML y retorna solo el texto visible estable."""
    # Eliminar scripts, estilos y comentarios
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<style[\s\S]*?</style>',   '', html, flags=re.IGNORECASE)
    html = re.sub(r'<!--[\s\S]*?-->',           '', html)
    # Eliminar todos los tags HTML (quedan solo los textos)
    html = re.sub(r'<[^>]+>', ' ', html)
    # Normalizar espacios
    html = re.sub(r'\s+', ' ', html).strip()
    return html

# ─── URLs a monitorear ────────────────────────────────────────────────────────
MONITORED_EVENTS = [
    {
        "id": "army_vie_2oct",
        "label": "Army Membership - Vie 2 Oct",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-army-membership-viernes-2-octubre"
    },
    {
        "id": "general_vie_2oct",
        "label": "Venta General - Vie 2 Oct",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-viernes-2-octubre"
    },
    {
        "id": "army_sab_3oct",
        "label": "Army Membership - Sab 3 Oct",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-army-membership-sabado-3-octubre"
    },
    {
        "id": "general_sab_3oct",
        "label": "Venta General - Sab 3 Oct",
        "url": "https://www.ticketmaster.co/event/bts-world-tour-venta-general-sabado-3-octubre"
    },
]

SOLD_OUT_KEYWORDS = ["agotado"]

BUY_CTA_KEYWORDS = [
    "seleccionar asiento",
    "agregar al carrito",
    "comprar entradas",
    "comprar boletos",
    "buy tickets",
    "find tickets",
    "select seats",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def timestamp_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_ticketmaster_status(html):
    """
    Detecta el estado del evento desde el HTML inicial de Ticketmaster.

    Aunque el DOM renderizado muestra:
    <div class="event-status status-soldout">
        <span>Agotado</span>
    </div>

    el HTML recibido por requests contiene una señal más estable:
    "salesStatus":"SOLD_OUT"

    No intenta comprar, reservar, entrar a fila ni interactuar con la página.
    Solo analiza HTML público.
    """
    sales_status_match = re.search(
        r'"salesStatus"\s*:\s*"([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )

    if sales_status_match:
        sales_status = sales_status_match.group(1).upper().strip()

        if sales_status == "SOLD_OUT":
            status_text = "AGOTADO"
            sold_out = True
            available = False
        elif sales_status in {"ON_SALE", "ONSALE", "AVAILABLE"}:
            status_text = f"POSIBLE DISPONIBLE - salesStatus={sales_status}"
            sold_out = False
            available = True
        else:
            status_text = f"REVISAR MANUALMENTE - salesStatus={sales_status}"
            sold_out = False
            available = False

        return {
            "status_code": sales_status,
            "status_text": status_text,
            "sold_out": sold_out,
            "available": available,
            "status_found": True,
            "selector": '"salesStatus" from initial HTML',
        }

    return {
        "status_code": "UNKNOWN",
        "status_text": "salesStatus NO DETECTADO - REVISAR MANUALMENTE",
        "sold_out": False,
        "available": False,
        "status_found": False,
        "selector": '"salesStatus" from initial HTML',
    }


def detect_status_keywords(html):
    return extract_ticketmaster_status(html)

def fetch_event_page(url):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        r.raise_for_status()
        return r.text, None
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return None, str(e)

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in {STATE_FILE}: {e}")
        print(f"Invalid JSON in {STATE_FILE}: {e}")
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")

def should_send_heartbeat(state):
    if not HEARTBEAT_ENABLED:
        return False

    last = state.get("last_heartbeat_sent")
    if not last:
        return True

    try:
        elapsed = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        return elapsed >= HEARTBEAT_INTERVAL_MINUTES
    except ValueError:
        return True

def build_heartbeat_message(results):
    origin = "GitHub Actions" if GITHUB_ACTIONS_MODE else "Local"
    lines = [
        "BTS Ticketmaster Monitor activo",
        "",
        f"Origen: {origin}",
        f"Consulta: {timestamp_now()}",
        "",
        "Estado por evento:",
    ]
    for r in results:
        icon = r.get("status_text") or (
            "AGOTADO" if r.get("sold_out") else "AGOTADO NO DETECTADO - REVISAR"
        )
        change = " ** CAMBIO **" if r.get("changed") else ""
        error  = f" | Error: {r['error']}" if r.get("error") else ""
        lines.append(f"  [{icon}] {r['label']}{change}{error}")
    lines += ["", "Seguir monitoreando..."]
    return "\n".join(lines)

def send_ntfy_alert(message, priority=None, tags=None):
    try:
        r = requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": "BTS Ticketmaster Monitor",
                "Priority": priority or NTFY_PRIORITY,
                "Tags": tags or NTFY_TAGS,
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=20,
        )
        r.raise_for_status()
        logging.info("ntfy alert sent")
        print("ntfy alert sent OK")
        return True
    except Exception as e:
        logging.error(f"Error sending ntfy: {e}")
        print(f"Error sending ntfy: {e}")
        return False

def check_all_events():
    state = load_state()
    any_changed = False
    results = []

    for event in MONITORED_EVENTS:
        eid   = event["id"]
        label = event["label"]
        url   = event["url"]

        print(f"  Checking: {label} ...")
        html, error = fetch_event_page(url)

        result = {
            "id":        eid,
            "label":     label,
            "url":       url,
            "changed":   False,
            "sold_out":  False,
            "available": False,
            "error":     error,
        }

        if error:
            results.append(result)
            continue

        kw = detect_status_keywords(html)

        result["sold_out"] = kw["sold_out"]
        result["available"] = kw["available"]
        result["status_code"] = kw.get("status_code")
        result["status_text"] = kw.get("status_text")
        result["status_found"] = kw.get("status_found")
        result["selector"] = kw.get("selector")

        status_snapshot = {
            "status_code": result["status_code"],
            "status_text": result["status_text"],
            "status_found": result["status_found"],
            "selector": result["selector"],
        }

        current_hash = sha256(
            json.dumps(status_snapshot, sort_keys=True, ensure_ascii=False)
        )

        previous_hash = state.get(f"{eid}_status_hash")

        detected_status = result["status_text"] or "SIN ESTADO"

        if previous_hash and current_hash != previous_hash:
            result["changed"] = True
            any_changed = True
            logging.info(f"Change detected: {label} | Status: {detected_status}")
            print(
                f"    CAMBIO DETECTADO | Estado: {detected_status} | "
                f"Hash estado: {current_hash[:8]}..."
            )
        else:
            print(
                f"    Sin cambios | Estado: {detected_status} | "
                f"Hash estado: {current_hash[:8]}..."
            )

        state[f"{eid}_status_hash"] = current_hash
        state[f"{eid}_status_snapshot"] = status_snapshot
        results.append(result)

    state["last_check"] = timestamp_now()
    save_state(state)
    return results, any_changed

def build_change_message(results):
    changed = [r for r in results if r.get("changed")]
    lines = ["CAMBIO DETECTADO - BTS Bogota", ""]
    for r in changed:
        status = r.get("status_text") or (
            "AGOTADO" if r.get("sold_out") else "AGOTADO NO DETECTADO - revisar manualmente"
        )
        lines.append(f"{r['label']}: {status}")
        lines.append(f"URL: {r['url']}")
        lines.append("")
    lines.append(f"Hora: {timestamp_now()}")
    return "\n".join(lines)

def run_check_once():
    print(f"\n{'='*60}")
    print(f"BTS Ticketmaster Monitor - Single Check")
    print(f"Started : {timestamp_now()}")
    print(f"Mode    : {'GitHub Actions' if GITHUB_ACTIONS_MODE else 'Local'}")
    print(f"{'='*60}\n")

    state = load_state()
    print("Checking events...\n")
    results, any_changed = check_all_events()

    alert_sent = False

    if any_changed:
        msg = build_change_message(results)
        print(f"\nSending change alert...")
        send_ntfy_alert(msg)
        alert_sent = True
        state = load_state()
        state["last_heartbeat_sent"] = timestamp_now()
        save_state(state)

    if not alert_sent and should_send_heartbeat(state):
        msg = build_heartbeat_message(results)
        print(f"\nSending heartbeat...")
        send_ntfy_alert(msg, priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
        state = load_state()
        state["last_heartbeat_sent"] = timestamp_now()
        save_state(state)

    print(f"\nDone at {timestamp_now()}")
    print(f"{'='*60}\n")

def run_daemon():
    print(f"\n{'='*60}")
    print(f"BTS Ticketmaster Monitor - Daemon Mode")
    print(f"Started : {timestamp_now()}")
    print(f"Interval: {CHECK_INTERVAL_MINUTES} min")
    print(f"{'='*60}\n")

    def scheduled_check():
        state = load_state()
        print(f"\n[{timestamp_now()}] Checking...")
        results, any_changed = check_all_events()

        alert_sent = False

        if any_changed:
            msg = build_change_message(results)
            send_ntfy_alert(msg)
            alert_sent = True
            state = load_state()
            state["last_heartbeat_sent"] = timestamp_now()
            save_state(state)

        if not alert_sent and should_send_heartbeat(state):
            msg = build_heartbeat_message(results)
            send_ntfy_alert(msg, priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
            state = load_state()
            state["last_heartbeat_sent"] = timestamp_now()
            save_state(state)

    scheduled_check()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(scheduled_check)

    print("Monitor running. Press Ctrl+C to stop.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print(f"\nMonitor stopped at {timestamp_now()}")

def main():
    parser = argparse.ArgumentParser(description="BTS Bogota Ticketmaster Monitor")
    parser.add_argument("--test-alert",     action="store_true")
    parser.add_argument("--test-heartbeat", action="store_true")
    parser.add_argument("--check-once",     action="store_true")
    parser.add_argument("--daemon",         action="store_true")
    args = parser.parse_args()

    if args.test_alert:
        send_ntfy_alert(
            "Prueba BTS Monitor: alerta de cambio funcionando\nURL: https://www.ticketmaster.co"
        )
        return

    if args.test_heartbeat:
        dummy = [{"label": e["label"], "changed": False, "sold_out": False,
                  "available": False, "error": None} for e in MONITORED_EVENTS]
        send_ntfy_alert(build_heartbeat_message(dummy),
                        priority=HEARTBEAT_PRIORITY, tags=HEARTBEAT_TAGS)
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
