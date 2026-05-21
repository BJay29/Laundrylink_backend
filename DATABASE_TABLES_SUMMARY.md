# LAUNDRYLINK - DATABASE TABLES SUMMARY

## 6 MAIN TABLES PARA SA DATABASE

### 1. **SHOPS TABLE** 
Core table na nag-store ng laundry business information

**Table Name:** `shops`  
**Primary Purpose:** Store shop details at serve as parent for all other data

**Columns:**
- `id` (INT) - Primary Key
- `shop_name` (VARCHAR) - Shop name (Unique)
- `address` (VARCHAR) - Shop location
- `created_at` (DATETIME) - Registration date

---

### 2. **USERS TABLE**
Para sa authentication at user management

**Table Name:** `users`  
**Primary Purpose:** Manage shop owners at staff members

**Columns:**
- `id` (INT) - Primary Key
- `email` (VARCHAR) - User email (Unique)
- `password_hash` (VARCHAR) - Encrypted password
- `role` (VARCHAR) - "owner" or "staff"
- `shop_id` (INT) - Foreign Key to shops
- `is_active` (BOOLEAN) - Active status
- `created_at` (DATETIME) - Account creation date

**Data Examples:**
```
| id | email              | role  | shop_id | is_active |
|----|-------------------|-------|---------|-----------|
| 1  | maria@laundromat.com | owner | 1     | True      |
| 2  | juan@laundromat.com  | staff | 1     | True      |
```

---

### 3. **MACHINES TABLE**
Hardware inventory tracking (Washers at Dryers)

**Table Name:** `machines`  
**Primary Purpose:** Track laundry equipment performance at status

**Columns:**
- `id` (INT) - Primary Key
- `machine_type` (VARCHAR) - "Washer" or "Dryer"
- `machine_number` (INT) - Unit number
- `status` (VARCHAR) - "Available", "Busy", "Maintenance"
- `current_service_type` (VARCHAR) - Active service
- `current_price` (FLOAT) - Current billing
- `remaining_time` (INT) - Countdown timer (seconds)
- `total_cycles` (INT) - Lifetime usage count
- `net_profit_accumulated` (FLOAT) - Total profit
- `profitability_rate` (FLOAT) - Profit percentage
- `accumulated_electricity` (FLOAT) - Electricity cost
- `accumulated_water` (FLOAT) - Water cost
- `accumulated_detergent` (FLOAT) - Detergent cost
- `shop_id` (INT) - Foreign Key to shops

**Data Examples:**
```
| id | machine_type | machine_number | status    | total_cycles | net_profit |
|----|--------------|----------------|-----------|--------------|------------|
| 1  | Washer       | 1              | Available | 1250         | 15750.50   |
| 2  | Dryer        | 1              | Busy      | 980          | 9800.00    |
```

---

### 4. **BOOKINGS TABLE**
Laundry transaction records

**Table Name:** `bookings`  
**Primary Purpose:** Record ng customer service requests at transactions

**Columns:**
- `id` (INT) - Primary Key
- `customer_name` (VARCHAR) - Customer name
- `service_type` (VARCHAR) - "Full Service", "Titan Wash", "Regular Wash", "Comforter"
- `category` (VARCHAR) - Service category
- `weight` (FLOAT) - Weight in kg
- `loads` (INT) - Number of loads
- `total_price` (FLOAT) - Total amount charged
- `booking_mode` (VARCHAR) - "Self-Service" or "Full Service"
- `service_duration` (INT) - Duration in minutes
- `add_detergent` (BOOLEAN) - Detergent add-on
- `add_delivery` (BOOLEAN) - Delivery add-on
- `is_rush` (BOOLEAN) - Rush order flag
- `status` (VARCHAR) - "Pending", "Completed", "Cancelled"
- `washer_id` (INT) - Foreign Key to machines
- `dryer_id` (INT) - Foreign Key to machines
- `shop_id` (INT) - Foreign Key to shops
- `booking_timestamp` (DATETIME) - Service start time
- `created_at` (DATETIME) - Record creation time

**Data Examples:**
```
| id | customer_name | service_type | weight | loads | total_price | washer_id | dryer_id | status    |
|----|---------------|--------------|--------|-------|-------------|-----------|----------|-----------|
| 1  | Alice         | Full Service | 5.5    | 3     | 210.00      | 1         | 2        | Completed |
| 2  | Bob           | Regular Wash | 3.0    | 2     | 65.00       | 2         | NULL     | Pending   |
| 3  | Carol         | Comforter    | 8.0    | 1     | 150.00      | 1         | 1        | Completed |
```

---

### 5. **INVENTORY TABLE**
Laundry supplies management

**Table Name:** `inventory`  
**Primary Purpose:** Track stock levels at reorder points

**Columns:**
- `id` (INT) - Primary Key
- `item_name` (VARCHAR) - Supply name
- `current_stock` (FLOAT) - Available quantity
- `reorder_point` (FLOAT) - Threshold for reordering
- `unit` (VARCHAR) - Measurement unit ("kg", "liters", "pieces")
- `shop_id` (INT) - Foreign Key to shops

**Data Examples:**
```
| id | item_name          | current_stock | reorder_point | unit   | shop_id |
|----|-------------------|----------------|---------------|--------|---------|
| 1  | Detergent Powder   | 25.0           | 5.0           | kg     | 1       |
| 2  | Fabric Softener    | 8.5            | 2.0           | liters | 1       |
| 3  | Bleach             | 12.0           | 3.0           | liters | 1       |
```

---

### 6. **SETTINGS TABLE**
Business configuration at pricing

**Table Name:** `settings`  
**Primary Purpose:** Store pricing rules at operational costs

**Columns:**
- `id` (INT) - Primary Key
- `full_service_price` (FLOAT) - Full service price (PHP)
- `regular_wash_price` (FLOAT) - Regular wash price (PHP)
- `titan_wash_price` (FLOAT) - Titan wash price (PHP)
- `comforter_price` (FLOAT) - Comforter service price (PHP)
- `electricity_rate` (FLOAT) - Cost per kWh (PHP)
- `water_rate` (FLOAT) - Cost per cubic meter (PHP)
- `detergent_cost_per_load` (FLOAT) - Cost per cycle (PHP)
- `off_peak_hours` (VARCHAR) - Time range for optimization
- `shop_id` (INT) - Foreign Key to shops (Unique - one per shop)

**Data Example:**
```
| id | full_service_price | regular_wash_price | titan_wash_price | comforter_price | electricity_rate | water_rate | detergent_cost | shop_id |
|----|-------------------|-------------------|------------------|-----------------|-----------------|-----------|----------------|---------|
| 1  | 210.00            | 65.00             | 100.00           | 150.00          | 12.00           | 50.00     | 10.00          | 1       |
```

---

## 🔗 TABLE RELATIONSHIPS (KEYS)

**Foreign Key Relationships:**
```
shops.id ──→ users.shop_id (One-to-Many)
shops.id ──→ machines.shop_id (One-to-Many)
shops.id ──→ bookings.shop_id (One-to-Many)
shops.id ──→ inventory.shop_id (One-to-Many)
shops.id ──→ settings.shop_id (One-to-One)

machines.id ──→ bookings.washer_id (One-to-Many)
machines.id ──→ bookings.dryer_id (One-to-Many)
```

---

## 📊 RELATIONSHIP CARDINALITY

| Relationship | Type | Explanation |
|---|---|---|
| SHOPS → USERS | 1:N | One shop has many users (owners/staff) |
| SHOPS → MACHINES | 1:N | One shop has many machines (washers/dryers) |
| SHOPS → BOOKINGS | 1:N | One shop processes many bookings |
| SHOPS → INVENTORY | 1:N | One shop stocks many inventory items |
| SHOPS → SETTINGS | 1:1 | One shop has one settings configuration |
| MACHINES → BOOKINGS (washer) | 1:N | One machine can be assigned to many bookings |
| MACHINES → BOOKINGS (dryer) | 1:N | One machine can be assigned to many bookings |

---

## 🎯 DATA TYPES REFERENCE

| Type | Description | Example |
|------|-------------|---------|
| INT | Integer numbers | 1, 100, 1250 |
| VARCHAR | Text/String | "Washer", "Alice", "Full Service" |
| FLOAT | Decimal numbers | 65.50, 210.00, 12.5 |
| BOOLEAN | True/False | True, False |
| DATETIME | Date and Time | 2024-05-21 14:30:00 |

---

## ✅ CONSTRAINTS

- **PRIMARY KEY (PK)**: Unique identifier for each row
- **FOREIGN KEY (FK)**: Link to parent table
- **UNIQUE**: No duplicate values allowed
- **NOT NULL**: Field must have a value
- **DEFAULT**: Automatic value if not provided
- **CASCADE**: Delete parent deletes children
- **SET NULL**: Delete parent sets foreign key to NULL

---

## 📝 SAMPLE SQL CREATE STATEMENTS

```sql
-- SHOPS
CREATE TABLE shops (
    id INT PRIMARY KEY AUTO_INCREMENT,
    shop_name VARCHAR(255) UNIQUE NOT NULL,
    address VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- USERS
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    shop_id INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
);

-- MACHINES
CREATE TABLE machines (
    id INT PRIMARY KEY AUTO_INCREMENT,
    machine_type VARCHAR(50) NOT NULL,
    machine_number INT NOT NULL,
    status VARCHAR(50) DEFAULT 'Available',
    current_service_type VARCHAR(100),
    current_price FLOAT DEFAULT 0.0,
    remaining_time INT DEFAULT 0,
    total_cycles INT DEFAULT 0,
    net_profit_accumulated FLOAT DEFAULT 0.0,
    profitability_rate FLOAT DEFAULT 0.0,
    accumulated_electricity FLOAT DEFAULT 0.0,
    accumulated_water FLOAT DEFAULT 0.0,
    accumulated_detergent FLOAT DEFAULT 0.0,
    shop_id INT NOT NULL,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
);

-- BOOKINGS
CREATE TABLE bookings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    customer_name VARCHAR(255) NOT NULL,
    service_type VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL,
    weight FLOAT NOT NULL,
    loads INT DEFAULT 1,
    total_price FLOAT NOT NULL,
    booking_mode VARCHAR(50) NOT NULL,
    service_duration INT DEFAULT 45,
    add_detergent BOOLEAN DEFAULT FALSE,
    add_delivery BOOLEAN DEFAULT FALSE,
    is_rush BOOLEAN DEFAULT FALSE,
    status VARCHAR(50) DEFAULT 'Pending',
    washer_id INT,
    dryer_id INT,
    shop_id INT NOT NULL,
    booking_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
    FOREIGN KEY (washer_id) REFERENCES machines(id) ON DELETE SET NULL,
    FOREIGN KEY (dryer_id) REFERENCES machines(id) ON DELETE SET NULL
);

-- INVENTORY
CREATE TABLE inventory (
    id INT PRIMARY KEY AUTO_INCREMENT,
    item_name VARCHAR(255) NOT NULL,
    current_stock FLOAT DEFAULT 0.0,
    reorder_point FLOAT DEFAULT 5.0,
    unit VARCHAR(50) DEFAULT 'kg',
    shop_id INT NOT NULL,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
);

-- SETTINGS
CREATE TABLE settings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    full_service_price FLOAT DEFAULT 210.0,
    regular_wash_price FLOAT DEFAULT 65.0,
    titan_wash_price FLOAT DEFAULT 100.0,
    comforter_price FLOAT DEFAULT 150.0,
    electricity_rate FLOAT DEFAULT 12.0,
    water_rate FLOAT DEFAULT 50.0,
    detergent_cost_per_load FLOAT DEFAULT 10.0,
    off_peak_hours VARCHAR(100) DEFAULT '8:00 AM - 11:00 AM',
    shop_id INT NOT NULL UNIQUE,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
);
```

---

## 📌 KEY INSIGHTS FOR YOUR PAPERS

1. **Multi-Tenant Architecture**: Database supports multiple laundry shops with isolated data
2. **Real-time Telemetry**: Machine status updated in real-time for monitoring
3. **Financial Analytics**: Profit tracking per machine para sa business intelligence
4. **Predictive Inventory**: Reorder points para sa automatic supply management
5. **Audit Trail**: All timestamps maintained para sa historical analysis
6. **RBAC Implementation**: Role-based access control para sa security
7. **Data Integrity**: Foreign keys at cascading deletes ensure consistency
