"""Dev server entry point. Production: use gunicorn or uvicorn with workers."""

import uvicorn

from .api import app  # noqa: F401  re-export for uvicorn


def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    uvicorn.run("praxis.web.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    serve(reload=True)
