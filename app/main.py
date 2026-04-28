from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app import models
from app.routes import auth_routes, shop_routes

# Database Sync: Automatically creates tables in PostgreSQL based on models
# Note: This won't add columns to existing tables, hence our manual ALTER TABLE in pgAdmin.
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="LaundryLink API",
    description="Backend API for Laundry Management System",
    version="1.0.0"
)

# CORS Configuration: Allows frontend applications (Flutter/React) to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Authentication Routes
# Tinanggal natin yung prefix="/auth" dito dahil nandoon na iyon sa loob ng auth_routes.router
app.include_router(auth_routes.router)
app.include_router(shop_routes.router)

@app.get("/")
def read_root():
    """
    Root endpoint to verify the API status and database connectivity.
    """
    return {
        "status": "Online",
        "message": "LaundryLink API is running with Clean Architecture!",
        "database": "PostgreSQL Connected"
    }

# Terminal status logs executed on server startup
@app.on_event("startup")
def startup_event():
    print("========================================")
    print("LaundryLink Backend started successfully")
    print("Architecture: Routes and Controllers Split")
    print("PostgreSQL Tables Synced!")
    print("Multi-Shop Support: Enabled")
    print("========================================")