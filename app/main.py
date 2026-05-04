from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine
from app import models
from app.routes import auth_routes, booking_routes, machine_routes

# 1. Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("========================================")
    print("LaundryLink Backend started successfully")
    print("Architecture: Clean Routes/Controllers Split")
    
    try:
        models.Base.metadata.create_all(bind=engine)
        print("PostgreSQL Tables Synced Successfully!")
    except Exception as e:
        print(f"Database Sync Error: {e}")
        
    print("System Mode: Profit Optimization Ready")
    print("========================================")
    
    yield  
    
    print("Shutting down LaundryLink Backend...")

# 2. FastAPI Instance
app = FastAPI(
    title="LaundryLink API",
    description="Backend API for Laundry Income Optimization System",
    version="1.0.0",
    lifespan=lifespan
)

# 3. CORS Fix:
# HINDI pwedeng sabay ang allow_origins=["*"] at allow_credentials=True
# Kaya specific origins na lang ang ilalagay
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        # Dagdag mo dito yung production URL mo pag nag-deploy ka ng frontend
        # "https://your-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routes
app.include_router(auth_routes.router)
app.include_router(booking_routes.router)
app.include_router(machine_routes.router)

# 5. Health Check
@app.get("/")
def read_root():
    return {
        "status": "Online",
        "system": "LaundryLink Optimization Engine",
        "database": "PostgreSQL Connected",
        "modules_active": ["Auth", "Bookings", "Machines"],
        "environment": "Development Sprint"
    }
