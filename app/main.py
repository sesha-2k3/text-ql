"""
text-ql: Natural Language to SQL converter.

FastAPI application entrypoint.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from config.settings import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting text-ql API...")
    settings = get_settings()
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Default dialect: {settings.default_dialect}")
    logger.info(f"Max row limit: {settings.max_row_limit}")

    # Validate API key is present
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not set - API calls will fail!")

    yield

    # Shutdown
    logger.info("Shutting down text-ql API...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="text-ql",
        description="Natural Language to SQL converter using multi-agent architecture",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router, prefix="/api")

    # Also mount at root for convenience
    app.include_router(router)

    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
