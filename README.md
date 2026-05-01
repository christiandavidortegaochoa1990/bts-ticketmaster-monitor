# Ticketmaster BTS Bogotá Monitor with Hourly Heartbeat

This Python project monitors **BTS Bogotá event availability** on Ticketmaster and sends instant push notifications via **ntfy** when **changes are detected**. Includes an optional hourly heartbeat to confirm the monitor is working.

## Key Features

✅ **Change Detection**: Only sends alerts when status actually changes  
✅ **No Spam**: Uses hash-based state tracking to avoid duplicate alerts  
✅ **Heartbeat**: Optional hourly summary confirming monitor is active  
✅ **Smart Priority**: Change alerts = urgent, heartbeats = normal  
✅ **Task Scheduler Ready**: Designed for Windows Task Scheduler automation  
✅ **Clear Logging**: Timestamps and detailed console output  

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Get Ticketmaster API Key
- Sign up at [developer.ticketmaster.com](https://developer.ticketmaster.com/) (free)
- Copy your API key to `config.py`: `TICKETMASTER_API_KEY = "your-key-here"`

### 3. Set Up ntfy Notifications
- Download the **ntfy app**:
  - [iOS App Store](https://apps.apple.com/us/app/ntfy/id1625396347)
  - [Google Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- Open the app and subscribe to this topic:
  ```
  https://ntfy.sh/bts-prueba
  ```
- Done! You'll receive all alerts automatically (no account needed)

## Usage

### Test ntfy Connection
```bash
python main.py --test-alert
```
Sends a test **change alert** to verify ntfy integration.

### Test Heartbeat
```bash
python main.py --test-heartbeat
```
Sends a test **heartbeat notification** to verify heartbeat format. Shows timestamp, events found, and error status.

### Run a Single Check
```bash
python main.py --check-once
```
This will:
1. Search Ticketmaster for BTS events
2. Compare with previous state
3. Send **change alert** immediately if changes detected
4. If no change, send **heartbeat** only if **60+ minutes** have passed since last heartbeat
5. Update `state.json` with new state and heartbeat timestamp
6. Exit

**Perfect for Windows Task Scheduler automation.**

### Run as Daemon (Continuous)
```bash
python main.py --daemon
```
Or simply:
```bash
python main.py
```

Runs continuous checks with the same logic as `--check-once`.

## Setup Windows Task Scheduler

### Automate checks every 10 minutes:

1. Open **Windows Task Scheduler**
2. Click **Create Basic Task...**
3. **Name**: "BTS Monitor"
4. **Trigger**: Daily → Repeat task every **10 minutes** → Indefinitely
5. **Action**:
   - Program: `C:\Users\<YourUser>\Documents\10_projects\ticket_master\.venv\Scripts\python.exe`
   - Arguments: `main.py --check-once`
   - Start in: `C:\Users\<YourUser>\Documents\10_projects\ticket_master`
6. **Conditions**: Uncheck "Stop if computer on battery"
7. Click **OK**

**Result**: Your computer will check for changes automatically every 10 minutes and send alerts to your phone.

## Alert Types

### Change Alert (🔴 URGENT)
Sent **immediately** when a change is detected:
- ✅ New event appears
- ⚠️ Event disappears (was visible, now gone)
- 🎫 Ticket sales open
- 🔄 Event details updated
- ❌ API error

**Priority**: URGENT | Tags: rotating_light, ticket

### Heartbeat (ℹ️ INFO)
Sent **every 60 minutes** (if no main alert in that run):
- Confirms monitor is active
- Shows last check timestamp
- Shows number of events found
- Shows if any changes were detected
- Shows any API errors

**Priority**: DEFAULT | Tags: information_source, robot

## Configuration

Edit `config.py` to customize:

```python
# Check frequency (for --daemon mode)
CHECK_INTERVAL_MINUTES = 10

# Heartbeat settings
HEARTBEAT_ENABLED = True  # Enable/disable heartbeats
HEARTBEAT_INTERVAL_MINUTES = 60  # How often (in minutes)
HEARTBEAT_PRIORITY = "default"  # Lower = less intrusive
HEARTBEAT_TAGS = "information_source,robot"

# ntfy topic (must match your subscription)
NTFY_URL = "https://ntfy.sh/bts-prueba"
```

## Important Notes

🔒 **Safe**: Only reads data. Does not automate login, queue, CAPTCHA, cart, checkout, or purchase  
📱 **Mobile Only**: ntfy app required on your phone  
⚡ **Instant**: Notifications arrive in real-time  
🆓 **Free**: No API keys or subscriptions for ntfy  
💾 **Smart**: Uses hashing to avoid repeated alerts for same status  

## Files

- `main.py` - Main monitor script with change + heartbeat logic
- `config.py` - Configuration (API keys, intervals, priorities)
- `state.json` - Persistent state (hash, event count, timestamps, summary)
- `requirements.txt` - Python dependencies
- `monitor.log` - Detailed activity log
- `README.md` - This file

## Troubleshooting

### "ERROR: Set TICKETMASTER_API_KEY"
- Get free API key at [developer.ticketmaster.com](https://developer.ticketmaster.com/)
- Update `config.py`

### Not receiving alerts?
- Test: `python main.py --test-alert`
- Make sure you subscribed to `https://ntfy.sh/bts-prueba` in ntfy app
- Check phone notification settings
- Alerts are **real-time only** (no history after restart)

### Getting too many heartbeats?
- Increase `HEARTBEAT_INTERVAL_MINUTES` (default 60)
- Or set `HEARTBEAT_ENABLED = False` to disable

### Monitor using too much data?
- Increase check interval in Task Scheduler or `CHECK_INTERVAL_MINUTES`
- Example: Check every 30 minutes instead of 10

## How It Works

1. **Fetches** BTS events from Ticketmaster API
2. **Normalizes** key fields (dates, sales, status, URL)
3. **Generates** SHA256 hash of normalized data
4. **Compares** hash against `state.json` 
5. **If changed**: Sends change alert immediately and updates heartbeat timer
6. **If not changed**: Checks if 60+ minutes passed since last heartbeat
7. **If heartbeat due**: Sends summary notification
8. **Always saves** updated state for next check

## License

Free to use and modify.