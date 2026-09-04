import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from the project root .env.local before any
# other imports that may depend on them.
load_dotenv(dotenv_path=".env.local")

from api.routes.health import router as health_router  # noqa: E402
from api.routes.simulation import router as simulation_router  # noqa: E402

app = FastAPI(
    title="Countercurrent IMB API",
    docs_url="/api/py/docs",
    openapi_url="/api/py/openapi.json",
)

API_PREFIX = "/api/py"

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routers.
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(simulation_router, prefix=API_PREFIX)
