import os

# Configuration for Ticketmaster Monitor
# Secrets are read from environment variables (for GitHub Actions and .env files)
# with fallback to placeholder values

# Ticketmaster API Key - Get from https://developer.ticketmaster.com/
TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY", "YOUR_API_KEY_HERE")

# Event ID - Find using search_event function or manually
EVENT_ID = os.getenv("EVENT_ID", "PLACEHOLDER")  # Replace with actual event ID

# ntfy push notification settings - No API keys required!
# Subscribe to this URL on your phone to receive alerts
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh/bts-prueba")
NTFY_PRIORITY = os.getenv("NTFY_PRIORITY", "urgent")
NTFY_TAGS = os.getenv("NTFY_TAGS", "rotating_light,ticket")

# Heartbeat notification settings
HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "True").lower() in ["true", "1", "yes"]
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "60"))
HEARTBEAT_PRIORITY = os.getenv("HEARTBEAT_PRIORITY", "default")
HEARTBEAT_TAGS = os.getenv("HEARTBEAT_TAGS", "information_source,robot")

# Check intervals in minutes
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
HOT_CHECK_INTERVAL_MINUTES = int(os.getenv("HOT_CHECK_INTERVAL_MINUTES", "2"))
HOT_WINDOW_DAYS_BEFORE_EVENT = int(os.getenv("HOT_WINDOW_DAYS_BEFORE_EVENT", "14"))

# Execution context
GITHUB_ACTIONS_MODE = os.getenv("GITHUB_ACTIONS_MODE", "false").lower() in ["true", "1", "yes"]

# Log file
LOG_FILE = "monitor.log"
STATE_FILE = "state.json"