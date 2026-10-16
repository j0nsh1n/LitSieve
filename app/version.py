"""The one place the app version lives (audit 23.5).

FastAPI, /health, the admin summary, support packets and every template
footer read it from here; a release bumps this line only.
"""

APP_VERSION = "6.0.0"
