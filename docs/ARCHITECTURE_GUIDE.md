# Architecture Guide

## Overview

The OpenStack Simulator follows a layered architecture with clear separation of concerns. All state lives in memory — there is no database, no persistence, and no network calls to external services.

## Layered Design

```
┌─────────────────────────────────────────────────────────┐
│                    REST API Layer                       │
│  (Flask Blueprints: identity, compute, network, volume) │
├─────────────────────────────────────────────────────────┤
│                    Manager Layer                        │
│  (AuthManager, ComputeManager, NetworkManager,          │
│   VolumeManager, SecurityGroupManager)                  │
├─────────────────────────────────────────────────────────┤
│                 Infrastructure Layer                    │
│  (ResourceStore, ResourceLimiter, Exceptions, Models)   │
├─────────────────────────────────────────────────────────┤
│                   Simulator Facade                      │
│  (Wires everything together, holds configuration)       │
└─────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | Responsibility |
|-------|---------------|
| REST API | HTTP request/response handling, JSON serialization, token validation, error translation |
| Manager | Business logic, state validation, limit checks, duplicate detection |
| Infrastructure | Data storage, quota counting, exception definitions, data models |
| Facade | Initialization, configuration, dependency wiring |

## Package Structure

```
openstack_simulator/
├── __init__.py              # Public API exports (Simulator, exceptions, models)
├── simulator.py             # Simulator facade class
├── models.py                # @dataclass models with to_dict()/from_dict()
├── store.py                 # ResourceStore — in-memory dict-based storage
├── limiter.py               # ResourceLimiter — quota enforcement
├── exceptions.py            # Custom exception hierarchy
├── managers/
│   ├── __init__.py
│   ├── auth.py              # AuthManager (Keystone)
│   ├── compute.py           # ComputeManager (Nova)
│   ├── network.py           # NetworkManager (Neutron)
│   ├── volume.py            # VolumeManager (Cinder)
│   └── security_group.py    # SecurityGroupManager (Neutron)
└── api/
    ├── __init__.py
    ├── app.py               # Flask application factory
    ├── wsgi.py              # WSGI entry point for gunicorn
    ├── helpers.py           # Shared utilities (token decorator, service catalog)
    ├── identity.py          # Keystone v3 endpoints
    ├── compute.py           # Nova v2.1 endpoints
    ├── network.py           # Neutron v2.0 endpoints
    └── volume.py            # Cinder v3 endpoints
```

## Key Components

### Simulator Facade (`simulator.py`)

The `Simulator` class is the single entry point. It:
- Merges user config with defaults
- Creates a shared `ResourceStore`
- Creates a `ResourceLimiter` with configured quotas
- Instantiates all managers with shared store and limiter references
- Exposes managers as attributes (`auth_manager`, `compute_manager`, etc.)

```python
sim = Simulator(config={"max_instances": 5})
sim.compute_manager.create("my-vm", "m1.small", "ubuntu-22.04")
```

### ResourceStore (`store.py`)

Central in-memory storage using Python dictionaries, one per resource type. Resources are keyed by name (or MAC address for ports).

**Operations:**
- `add(resource_type, name, resource)` — store a resource
- `get(resource_type, name)` — retrieve (returns None if deleted or missing)
- `list_active(resource_type)` — all non-deleted resources
- `mark_deleted(resource_type, name)` — soft-delete (sets status to "DELETED")
- `count_active(resource_type)` — count for quota checks

### ResourceLimiter (`limiter.py`)

Enforces maximum resource counts per type. Called by managers before creating resources.

```python
limiter.check("instances", store)  # raises ResourceLimitExceededError if at limit
```

### Exception Hierarchy (`exceptions.py`)

```
SimulatorError (base)
├── AuthenticationError        — empty credentials
├── TokenExpiredError          — expired token validation
├── ResourceLimitExceededError — quota exceeded
├── DuplicateResourceError     — name conflict
├── ResourceNotFoundError      — missing resource
└── InvalidStateError          — illegal state transition
```

### Data Models (`models.py`)

All resources are Python `@dataclass` classes with:
- UUID v4 identifiers
- ISO 8601 timestamps
- `to_dict()` for serialization
- `from_dict(data)` classmethod for deserialization
- `field(default_factory=list)` for collection fields

Models: `Token`, `Instance`, `Network`, `Subnet`, `Router`, `Port`, `Bond`, `Volume`, `SecurityGroup`, `Rule`, `Snapshot`

### Managers (`managers/`)

Each manager follows the same pattern:
1. Accept `store` and `limiter` in `__init__`
2. Check limits before creation (`limiter.check(...)`)
3. Check for duplicates before creation (`store.get(...)`)
4. Create model instances with `_generate_id()` and `_now_timestamp()`
5. Store via `store.add(...)`
6. Raise specific exceptions for error cases

### REST API (`api/`)

Flask blueprints that wrap manager operations with HTTP semantics:
- Token validation via `@require_token` decorator
- JSON request/response handling
- Exception-to-HTTP-status translation
- Service catalog generation for token responses

## Data Flow

### Create Resource (e.g., server)

```
Client → POST /compute/v2.1/servers
       → @require_token validates X-Auth-Token
       → compute_bp.create_server() extracts JSON body
       → sim.compute_manager.create(name, flavor, image)
           → limiter.check("instances", store)
           → store.get("instances", name) — duplicate check
           → Instance(...) — create model
           → store.add("instances", name, instance)
       → return JSON response with 202 status
```

### Authentication Flow

```
Client → POST /identity/v3/auth/tokens
       → identity_bp.create_token() extracts credentials
       → sim.auth_manager.authenticate(username, password)
           → Token(...) — create token with UUID and expiry
           → store.tokens[token.id] = token
       → return JSON with service catalog
       → X-Subject-Token header contains the token ID
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| State storage | In-memory dicts | Simple, fast, sufficient for training |
| Resource identity | uuid.uuid4() | Matches real OpenStack |
| Timestamps | ISO 8601 + "Z" | Consistent with OpenStack API |
| Deletion | Soft-delete (status="DELETED") | Matches OpenStack behavior |
| Token expiry | Real time comparison | Simple and testable |
| Workers | Single gunicorn worker | Required for shared in-memory state |
| API framework | Flask | Lightweight, well-known, easy to extend |

## Extending the Simulator

To add a new OpenStack service (e.g., Ironic):

1. **Add models** to `models.py` (dataclass with to_dict/from_dict)
2. **Add store attributes** in `store.py` (new dict for the resource type)
3. **Create a manager** in `managers/` (following the existing pattern)
4. **Update the facade** in `simulator.py` (add config defaults, instantiate manager)
5. **Create an API blueprint** in `api/` (Flask routes wrapping manager calls)
6. **Register the blueprint** in `api/app.py`
7. **Update the service catalog** in `api/helpers.py`
