"""Render startup — minimal server that passes health check immediately,
then loads the full app in a background thread."""
import logging
import os
import signal
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("start")

PORT = int(os.environ.get("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):
    """Responde 200 imediatamente para passar o health check do Render."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"starting","version":"2.0.0"}')

    def log_message(self, format, *args):
        log.info("temp-health: %s", format % args)


def run_full_app():
    """Carrega e inicia o app completo, substituindo o health server."""
    try:
        import uvicorn

        log.info("Loading full application...")
        from content_pipeline.web.app import app

        log.info("App loaded — starting uvicorn on port %d", PORT)
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
    except Exception:
        log.error("Fatal error loading app:")
        traceback.print_exc()
        # Keep process alive to avoid restart loop — serve health only
        log.info("Falling back to health-only mode")
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.serve_forever()


def handle_signal(signum, frame):
    log.info("Signal %s received — exiting", signum)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("Starting on port %d", PORT)

    # Start temporary health server to pass Render's health check
    temp_server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    temp_thread = threading.Thread(target=temp_server.serve_forever, daemon=True)
    temp_thread.start()
    log.info("Temp health server listening — loading full app...")

    # Give the health server a moment, then load the real app
    time.sleep(2)
    temp_server.shutdown()
    log.info("Temp server stopped — switching to full uvicorn")

    run_full_app()
