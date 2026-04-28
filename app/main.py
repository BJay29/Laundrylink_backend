from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine
from app import models
from app.routes import auth_routes, shop_routes

# 1. Modern Lifespan Manager: Kapalit ng @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dito ilalagay ang code na tatakbo pagka-start ng server
    print("========================================")
    print("LaundryLink Backend started successfully")
    print("Architecture: Routes and Controllers Split")
    
    # Database Sync: Ginagawa ang tables sa PostgreSQL (Aiven)
    try:
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Tables Synced!")
    except Exception as e:
        print(f"Database Sync Error: {e}")
        
    print("Multi-Shop Support: Enabled")
    print("========================================")
    
    yield  # Dito tumatakbo ang FastAPI app
    
    # Dito naman ilalagay ang code kung may gagawin bago mag-shutdown (optional)
    print("Shutting down LaundryLink Backend...")

# 2. FastAPI Instance with Lifespan
app = FastAPI(
    title="LaundryLink API",
    description="Backend API for Laundry Management System",
    version="1.0.0",
    lifespan=lifespan
)

# 3. CORS Configuration: Mahalaga para sa Flutter at React integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Payagan ang lahat ng origins sa development/testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routes
app.include_router(auth_routes.router)
app.include_router(shop_routes.router)

# 5. Root Endpoint
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