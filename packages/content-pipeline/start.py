"""Render startup script with error capture."""
import os
import sys
import traceback

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    print(f"[start.py] Starting uvicorn on port {port}", flush=True)
    try:
        import uvicorn
        print("[start.py] uvicorn imported OK", flush=True)
        from content_pipeline.web.app import app
        print("[start.py] app imported OK", flush=True)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
