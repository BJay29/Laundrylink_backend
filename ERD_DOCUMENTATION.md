# Laundrylink Backend - Entity Relationship Diagram (ERD)

## Database Overview
Ang system ay gumagamit ng **6 main tables** na naka-organize para sa laundry business management.

---

## 📋 TABLE SPECIFICATIONS

### 1. **SHOPS** (Main/Parent Entity)
**Purpose**: Nagse-serve as container para sa lahat ng shop-specific data

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique shop identifier |
| `shop_name` | String | UNIQUE, NOT NULL | Pangalan ng laundry shop |
| `address` | String | NULLABLE | Lokasyon ng shop |
| `created_at` | DateTime | DEFAULT: Current UTC Time | Kapag nag-register ang shop |

**Relationships:**
- ONE-TO-MANY with `users` (1 shop → many users/staff)
- ONE-TO-MANY with `machines` (1 shop → many washers/dryers)
- ONE-TO-MANY with `bookings` (1 shop → many transactions)
- ONE-TO-MANY with `inventory` (1 shop → many items)
- ONE-TO-ONE with `settings` (1 shop → 1 settings config)

---

### 2. **USERS** (Authentication & Access Control)
**Purpose**: Identity management para sa shop owners at staff

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique user identifier |
| `email` | String | UNIQUE, NOT NULL, INDEXED | Login email |
| `password_hash` | String | NOT NULL | Encrypted password |
| `role` | String | NOT NULL | "owner" or "staff" (RBAC) |
| `shop_id` | Integer | FOREIGN KEY → shops.id | Link sa shop |
| `is_active` | Boolean | DEFAULT: True | User status (active/inactive) |
| `created_at` | DateTime | DEFAULT: Current UTC Time | Account creation date |

**Relationships:**
- MANY-TO-ONE with `shops` (multiple users per shop)

---

### 3. **MACHINES** (Hardware Units)
**Purpose**: Track laundry equipment (washers/dryers) at operational performance

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique machine identifier |
| `machine_type` | String | NOT NULL | "Washer" or "Dryer" |
| `machine_number` | Integer | NOT NULL | Machine unit number (e.g., W-1, D-2) |
| `status` | String | DEFAULT: "Available" | "Available", "Busy", "Maintenance" |
| `current_service_type` | String | DEFAULT: "None" | Active service type |
| `current_price` | Float | DEFAULT: 0.0 | Billing amount para sa current cycle |
| `remaining_time` | Integer | DEFAULT: 0 | Countdown timer sa seconds |
| `total_cycles` | Integer | DEFAULT: 0 | Lifetime usage counter |
| `net_profit_accumulated` | Float | DEFAULT: 0.0 | Total profit generated |
| `profitability_rate` | Float | DEFAULT: 0.0 | Profitability percentage |
| `accumulated_electricity` | Float | DEFAULT: 0.0 | Total electricity cost |
| `accumulated_water` | Float | DEFAULT: 0.0 | Total water cost |
| `accumulated_detergent` | Float | DEFAULT: 0.0 | Total detergent cost |
| `shop_id` | Integer | FOREIGN KEY → shops.id | Link sa shop (owner) |

**Relationships:**
- MANY-TO-ONE with `shops` (multiple machines per shop)
- ONE-TO-MANY with `bookings` (via washer_id: 1 machine → many bookings)
- ONE-TO-MANY with `bookings` (via dryer_id: 1 machine → many bookings)

---

### 4. **BOOKINGS** (Laundry Transactions)
**Purpose**: Record ng bawat customer service request at transaction details

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique booking identifier |
| `customer_name` | String | NOT NULL | Pangalan ng customer |
| `service_type` | String | NOT NULL | "Full Service", "Titan Wash", "Regular Wash", "Comforter" |
| `category` | String | NOT NULL | Service category |
| `weight` | Float | NOT NULL | Pag-timbang ng laundry (kg) |
| `loads` | Integer | DEFAULT: 1 | Number ng loads |
| `total_price` | Float | NOT NULL | Final billing amount |
| `booking_mode` | String | NOT NULL | "Self-Service" or "Full Service" |
| `service_duration` | Integer | DEFAULT: 45 | Duration sa minutes |
| `add_detergent` | Boolean | DEFAULT: False | Add-on service |
| `add_delivery` | Boolean | DEFAULT: False | Add-on service |
| `is_rush` | Boolean | DEFAULT: False | Rush order indicator |
| `status` | String | DEFAULT: "Pending" | "Pending", "Completed", "Cancelled" |
| `washer_id` | Integer | FOREIGN KEY → machines.id (NULLABLE) | Assigned washer |
| `dryer_id` | Integer | FOREIGN KEY → machines.id (NULLABLE) | Assigned dryer |
| `shop_id` | Integer | FOREIGN KEY → shops.id | Link sa shop |
| `booking_timestamp` | DateTime | DEFAULT: Current UTC Time | Service start time |
| `created_at` | DateTime | DEFAULT: Current UTC Time | Record creation time |

**Relationships:**
- MANY-TO-ONE with `shops` (multiple bookings per shop)
- MANY-TO-ONE with `machines` (washer_id: many bookings → 1 machine)
- MANY-TO-ONE with `machines` (dryer_id: many bookings → 1 machine)

---

### 5. **INVENTORY** (Stock Management)
**Purpose**: Track ng laundry supplies at reorder levels para sa predictive ordering

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique inventory item ID |
| `item_name` | String | NOT NULL, INDEXED | Pangalan ng supply (e.g., Detergent, Fabric Softener) |
| `current_stock` | Float | DEFAULT: 0.0 | Available quantity |
| `reorder_point` | Float | DEFAULT: 5.0 | Threshold para sa reordering |
| `unit` | String | DEFAULT: "kg" | Measurement unit ("kg", "liters", "pieces") |
| `shop_id` | Integer | FOREIGN KEY → shops.id | Link sa shop |

**Relationships:**
- MANY-TO-ONE with `shops` (multiple items per shop)

---

### 6. **SETTINGS** (Business Configuration)
**Purpose**: Central configuration para sa pricing at operational costs

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | Integer | PRIMARY KEY, AUTO INCREMENT | Unique settings ID |
| `full_service_price` | Float | DEFAULT: 210.0 | Price para sa full service (PHP) |
| `regular_wash_price` | Float | DEFAULT: 65.0 | Price para sa regular wash (PHP) |
| `titan_wash_price` | Float | DEFAULT: 100.0 | Price para sa titan wash (PHP) |
| `comforter_price` | Float | DEFAULT: 150.0 | Price para sa comforter service (PHP) |
| `electricity_rate` | Float | DEFAULT: 12.0 | Cost per kWh (PHP) |
| `water_rate` | Float | DEFAULT: 50.0 | Cost per cubic meter (PHP) |
| `detergent_cost_per_load` | Float | DEFAULT: 10.0 | Estimated cost per cycle (PHP) |
| `off_peak_hours` | String | DEFAULT: "8:00 AM - 11:00 AM" | Optimization window |
| `shop_id` | Integer | FOREIGN KEY → shops.id (UNIQUE) | Link sa shop (one-to-one) |

**Relationships:**
- ONE-TO-ONE with `shops` (1 shop → 1 settings config)

---

## 🔗 RELATIONSHIPS SUMMARY

```
SHOPS (Parent Entity)
├── 1:N → USERS (Many staff/owners per shop)
├── 1:N → MACHINES (Many washers/dryers per shop)
├── 1:N → BOOKINGS (Many transactions per shop)
├── 1:N → INVENTORY (Many supply items per shop)
└── 1:1 → SETTINGS (One configuration per shop)

MACHINES
└── 1:N → BOOKINGS (via washer_id and dryer_id)
```

---

## 📊 DATA TYPES USED

- **Integer**: For IDs, counters, and numeric identifiers
- **String**: For names, descriptions, and categorical data
- **Float**: For prices, weights, costs, and financial metrics
- **Boolean**: For flags (add_detergent, add_delivery, is_rush, is_active)
- **DateTime**: For timestamps and audit trails

---

## 🔐 CONSTRAINTS & INTEGRITY

| Constraint Type | Details |
|-----------------|---------|
| PRIMARY KEY | Unique identifier para sa bawat table |
| FOREIGN KEY | Maintains referential integrity between tables |
| UNIQUE | shop_name at email (prevent duplicates) |
| NOT NULL | Required fields para sa data consistency |
| DEFAULT | Automatic values kung walang user input |
| CASCADE DELETE | Kung may-delete ng shop, lahat ng related data ay automatic na ded-delete |
| ON DELETE SET NULL | Kung may-delete ng machine, booking references ay nagiging NULL |
| INDEXED | Fast queries para sa frequently searched columns |

---

## 📈 SAMPLE DATA RELATIONSHIPS

### Example: Single Shop with All Related Data

```
SHOP: "LundroMat Express"
├── USERS: [Owner Maria, Staff Juan]
├── MACHINES: [W-1, W-2, D-1, D-2]
├── BOOKINGS: [
│   {customer: "Alice", washer: W-1, dryer: D-1, service: "Full Service"},
│   {customer: "Bob", washer: W-2, dryer: D-2, service: "Regular Wash"}
│   ]
├── INVENTORY: [Detergent (10 kg), Softener (5 liters), etc.]
└── SETTINGS: {full_service_price: 210, electricity_rate: 12, ...}
```

---

## 💾 KEY FEATURES

1. **Multi-Tenancy**: Each shop has isolated data
2. **Real-time Telemetry**: Machine status updated in real-time
3. **Financial Analytics**: Profit tracking per machine
4. **Predictive Inventory**: Reorder points para sa automatic reminders
5. **Audit Trail**: All timestamps para sa history tracking
6. **RBAC**: Role-based access control para sa users
7. **Cascading Operations**: Delete operations manage related data automatically
