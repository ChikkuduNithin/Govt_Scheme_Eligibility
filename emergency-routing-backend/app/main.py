from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import database as db_module
from app.core.database import (
    connect_to_mongo,
    close_mongo_connection,
    create_indexes,
    get_db,
)
from app.routers import alerts as alerts_router
from app.routers import ambulances as ambulances_router
from app.routers import emergencies as emergencies_router
from app.routers import hospitals as hospitals_router
from app.routers import ws as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    await create_indexes(get_db())
    yield
    await close_mongo_connection()


app = FastAPI(title="Emergency Routing Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hospitals_router.router, prefix="/api/v1")
app.include_router(ambulances_router.router, prefix="/api/v1")
app.include_router(emergencies_router.router, prefix="/api/v1")
app.include_router(alerts_router.router, prefix="/api/v1")
app.include_router(ws_router.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health():
    db_status = "ok" if db_module.client is not None else "down"
    return {"status": "ok", "database": db_status}
