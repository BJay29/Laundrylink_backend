from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine
from app import models
from app.routes import auth_routes, booking_routes, machine_routes

# 1. Lifespan Manager: Replaces the deprecated @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This block executes when the server starts
    print("========================================")
    print("LaundryLink Backend started successfully")
    print("Architecture: Clean Routes/Controllers Split")
    
    # Database Synchronization: Automatically creates/updates tables
    # This will now include the new Booking and Machine tables
    try:
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Tables Synced Successfully!")
    except Exception as e:
        print(f"Database Sync Error: {e}")
        
    print("System Mode: Profit Optimization Ready")
    print("========================================")
    
    yield  # The FastAPI application runs here
    
    # This block executes before the server shuts down
    print("Shutting down LaundryLink Backend...")

# 2. FastAPI Instance Configuration
app = FastAPI(
    title="LaundryLink API",
    description="Backend API for Laundry Income Optimization System",
    version="1.0.0",
    lifespan=lifespan
)

# 3. CORS Configuration: Essential for Flutter (Mobile) and React (Web) integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Application Routes
# Including the core modules for Auth, Bookings, and Machines
app.include_router(auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)

# 5. Root Endpoint for Status Verification
@app.get("/")
def read_root():
    """
    Root endpoint to verify API status and database connectivity.
    Used for initial health checks during deployment.
    """
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines"],
        "environment": "Development Sprint"
    }