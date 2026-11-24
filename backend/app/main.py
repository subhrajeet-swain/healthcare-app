from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import auth, db, errors, privacy
from app.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool(settings.database_url)
    yield
    db.close_pool()


app = FastAPI(title="healthcare-app", lifespan=lifespan)
errors.install(app)
app.include_router(auth.router)
app.include_router(privacy.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
