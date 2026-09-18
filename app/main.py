"""GridWise HTTP service. Two endpoints, exact names required by the specification."""
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gridwise")

app = FastAPI(title="GridWise", version="1.0.0", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    """Readiness probe. No external dependency - must stay cheap under repeated polling."""
    return {"status": "ok"}
