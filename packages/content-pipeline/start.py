"""Render startup script."""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    import uvicorn
    from content_pipeline.web.app import app
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
