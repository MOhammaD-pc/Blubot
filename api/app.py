from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.connection import init_db
from api.routes_invoices import router as invoices_router
from api.routes_payment_page import router as payment_router
from api.routes_web import router as web_router
from api.routes_dashboard_api import router as dashboard_api_router

from pathlib import Path
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    yield

def create_app() -> FastAPI:
    app = FastAPI(
        title="BluBot Card-to-Card Payment Platform",
        description="Automated card-to-card payment gateway powered by BluBank active sessions",
        version="1.0.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files (logo, assets)
    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Mount Web Frontend and API Routers
    app.include_router(web_router)
    app.include_router(dashboard_api_router)
    app.include_router(invoices_router)
    app.include_router(payment_router)

    return app

app = create_app()
