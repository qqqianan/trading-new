"""FastAPI application entry point."""

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ashare_lab.api.router import create_api_router
from ashare_lab.data.demo import DemoMarketDataProvider
from ashare_lab.services.research import ResearchService

_WEB_DIRECTORY = Path(__file__).parent / "web"


def create_app() -> FastAPI:
    """Assemble the application with a replaceable market data adapter."""
    provider = DemoMarketDataProvider()
    service = ResearchService(provider)
    application = FastAPI(
        title="A 股量化研究台",
        version="0.1.0",
    )
    application.include_router(create_api_router(service))
    application.mount("/", StaticFiles(directory=_WEB_DIRECTORY, html=True), name="web")
    return application


app = create_app()


def run() -> None:
    """Run the local research server."""
    uvicorn.run("ashare_lab.main:app", host="127.0.0.1", port=8000, reload=False)
