# Atlas Workspace Architecture Specification (Synthetic)

**System**: Atlas Core Service  
**Version**: 1.0-alpha  
**Status**: In Development (Synthetic Demo Dataset)  

---

## 1. System Overview
The Atlas Core Service is an enterprise context and activity management engine designed to orchestrate events, background jobs, and team records across distributed modules.

### High-Level Topology
```text
[ React + Vite Client ] <---> [ FastAPI Gateway ] <---> [ SQLite Engine (trace.db) ]
                                       |
                              [ Internal Cache: In-Memory LRU ]
```

---

## 2. Core Functional Modules
1. **auth**: User identity, password encryption via bcrypt (passlib), and JWT bearer token issuance. Authentication middleware validates authorization headers on protected endpoints.
2. **database**: SQLite embedded relational persistence via SQLAlchemy 2.x ORM models.
3. **payments**: External billing and checkout webhook integration (designated owner in meeting notes: Ankit Rao).
4. **notifications**: Multi-channel event dispatching, supporting SMTP email formatting and internal stream queues.
5. **api-docs**: OpenAPI contract documentation and interactive Swagger documentation.
6. **frontend-dashboard**: Modular React SPA featuring the Handover Center as the hero interface.

---

## 3. Caching & Performance
- **Active Strategy**: In-memory LRU cache dictionary configured in application memory.
- *Note*: Ensure worker process memory boundaries are monitored under elevated concurrency.

---

## 4. Security & Role Clearances
Clearance levels are strictly categorized into:
- `public`: Accessible to all authenticated and external audit entities.
- `team`: Restricted to internal organization members and developers.
- `restricted`: High-sensitivity organizational and leadership documentation.
