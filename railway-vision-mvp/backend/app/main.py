import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, audit, auth, dashboard, devices, edge, models, pipelines, results, settings as settings_api, tasks, training, users
from app.core.brand import BRAND_TAGLINE
from app.core.config import get_settings
from app.db.database import SessionLocal
from app.services.bootstrap_service import bootstrap_defaults, initialize_database

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    description=BRAND_TAGLINE,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    os.makedirs(settings.model_repo_path, exist_ok=True)
    os.makedirs(settings.asset_repo_path, exist_ok=True)

    initialize_database()
    db = SessionLocal()
    try:
        bootstrap_defaults(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(settings_api.router)
app.include_router(models.router)
app.include_router(pipelines.router)
app.include_router(assets.router)
app.include_router(tasks.router)
app.include_router(training.router)
app.include_router(results.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(devices.router)
app.include_router(edge.router)
