# Implementation Plan: Ironic Baremetal Manager

## Overview

Add an Ironic (Bare Metal) manager to the OpenStack Simulator, implementing node and port lifecycle management with provision/power state machines. Implementation proceeds bottom-up: data models → store updates → limiter updates → manager → facade integration → REST API blueprint → tests. Each step builds on the previous, with property-based tests woven in alongside each component.

## Tasks

- [x] 1. Add Baremetal data models to models.py
  - [x] 1.1 Implement `BaremetalNode` dataclass in `openstack_simulator/models.py`
    - Add `@dataclass` class with fields: id, name, driver, power_state, provision_state, memory_mb, cpus, local_gb, cpu_arch, driver_info (dict), properties (dict), status, created_at, updated_at
    - Implement `to_dict()` method returning all fields as a dictionary (deep-copy dicts)
    - Implement `from_dict(data)` class method constructing a BaremetalNode from a dictionary
    - Use `field(default_factory=dict)` for driver_info and properties
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 Implement `BaremetalPort` dataclass in `openstack_simulator/models.py`
    - Add `@dataclass` class with fields: id, node_id, address (MAC), status, created_at
    - Implement `to_dict()` method returning all fields as a dictionary
    - Implement `from_dict(data)` class method constructing a BaremetalPort from a dictionary
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x]* 1.3 Write property test for BaremetalNode serialization round-trip
    - **Property 1: BaremetalNode serialization round-trip**
    - Generate random valid BaremetalNode instances and verify `BaremetalNode.from_dict(node.to_dict())` produces an equivalent object
    - **Validates: Requirements 1.2, 1.3, 1.4**
  - [x]* 1.4 Write property test for BaremetalPort serialization round-trip
    - **Property 2: BaremetalPort serialization round-trip**
    - Generate random valid BaremetalPort instances and verify `BaremetalPort.from_dict(port.to_dict())` produces an equivalent object
    - **Validates: Requirements 2.2, 2.3, 2.4**

- [x] 2. Update ResourceStore with baremetal resource types
  - [x] 2.1 Add `baremetal_nodes` and `baremetal_ports` dictionaries to `ResourceStore.__init__` in `openstack_simulator/store.py`
    - Add `self.baremetal_nodes: dict[str, BaremetalNode] = {}` attribute
    - Add `self.baremetal_ports: dict[str, BaremetalPort] = {}` attribute
    - Import `BaremetalNode` and `BaremetalPort` from models
    - Verify existing `add`, `get`, `list_active`, `mark_deleted`, `count_active` methods work with the new resource types
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 3. Update ResourceLimiter and Simulator facade
  - [x] 3.1 Add baremetal limits to `DEFAULT_CONFIG` and `Simulator.__init__` in `openstack_simulator/simulator.py`
    - Add `"max_baremetal_nodes": 10` and `"max_baremetal_ports": 20` to `DEFAULT_CONFIG`
    - Add `"baremetal_nodes": int(self.config["max_baremetal_nodes"])` and `"baremetal_ports": int(self.config["max_baremetal_ports"])` to the limiter limits dict
    - Import `BaremetalManager` from `openstack_simulator.managers.baremetal`
    - Instantiate `self.baremetal_manager = BaremetalManager(store=self.store, limiter=self.limiter)`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 4. Implement BaremetalManager
  - [x] 4.1 Create `openstack_simulator/managers/baremetal.py` with node CRUD operations
    - Implement `__init__(self, store: ResourceStore, limiter: ResourceLimiter)`
    - Implement `create_node(name, driver, memory_mb=0, cpus=0, local_gb=0, cpu_arch="x86_64", driver_info=None, properties=None)` — check limit via `self.limiter.check("baremetal_nodes", self.store)`, check duplicate name, create BaremetalNode with UUID, provision_state="enroll", power_state="power off", status="ACTIVE", timestamps
    - Implement `get_node(name)` — return node from store or None
    - Implement `list_nodes()` — return all non-deleted nodes via `self.store.list_active("baremetal_nodes")`
    - Implement `update_node(name, **updates)` — raise ResourceNotFoundError if not found, check duplicate name if name changes, apply updates, set updated_at
    - Implement `delete_node(name)` — raise ResourceNotFoundError if not found, set provision_state to "deleted", mark deleted in store
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 12.1, 12.2, 12.3, 12.4_
  - [x] 4.2 Implement provision state machine in `BaremetalManager`
    - Implement `set_provision_state(name, target)` with valid transitions:
      - enroll + "manage" → manageable
      - manageable + "provide" → available
      - manageable + "clean" → manageable (passes through cleaning)
      - available + "active" → active (set power_state to "power on")
      - active + "deleted" → available (undeploy, set power_state to "power off")
      - available + "deleted" → soft-delete via store
    - Raise `InvalidStateError` for any invalid transition
    - Update `updated_at` timestamp on successful transition
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  - [x] 4.3 Implement power state machine in `BaremetalManager`
    - Implement `set_power_state(name, target)` with valid transitions:
      - "power on" target when provision_state in {available, active} → set power_state to "power on"
      - "power off" target when provision_state in {available, active} → set power_state to "power off"
      - "rebooting" target when power_state is "power on" → set power_state to "power on" (passes through rebooting)
    - Raise `InvalidStateError` if provision_state in {enroll, manageable}
    - Update `updated_at` timestamp on successful change
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [x] 4.4 Implement port operations in `BaremetalManager`
    - Implement `create_port(node_id, address)` — check limit via `self.limiter.check("baremetal_ports", self.store)`, verify node_id references existing non-deleted node (search by id field), check duplicate MAC address, create BaremetalPort with UUID, status="ACTIVE", created_at
    - Implement `list_ports(node_id=None)` — return all non-deleted ports, optionally filtered by node_id
    - Implement `delete_port(address)` — raise ResourceNotFoundError if not found, mark deleted in store
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_
  - [x]* 4.5 Write property test for node creation initial state
    - **Property 3: Node creation initial state invariant**
    - For any valid name/driver/hardware params, verify newly created node has provision_state=="enroll" and power_state=="power off"
    - **Validates: Requirements 3.1**
  - [x]* 4.6 Write property test for duplicate node name rejection
    - **Property 4: Duplicate node name rejection**
    - Create a node, then attempt to create another with the same name — verify DuplicateResourceError is raised
    - **Validates: Requirements 3.3**
  - [x]* 4.7 Write property test for node quota enforcement
    - **Property 5: Node quota enforcement**
    - Configure limit N, create N nodes, verify next create raises ResourceLimitExceededError
    - **Validates: Requirements 3.4**
  - [x]* 4.8 Write property test for node store consistency
    - **Property 6: Node store consistency**
    - Perform sequences of create/delete, verify list_nodes returns exactly non-deleted nodes, get_node returns None for deleted/non-existent
    - **Validates: Requirements 3.5, 4.1, 4.2, 4.3, 5.1, 5.3**

- [x] 5. Checkpoint - Verify models, store, and manager
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement provision and power state property tests
  - [x]* 6.1 Write property test for valid provision state transitions
    - **Property 7: Valid provision state transitions**
    - For each valid (source_state, target) pair, verify the node transitions to the expected destination state with correct side effects
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
  - [x]* 6.2 Write property test for invalid provision state transitions
    - **Property 8: Invalid provision state transitions**
    - For any node and any target not valid for the current provision_state, verify InvalidStateError is raised
    - **Validates: Requirements 6.6**
  - [x]* 6.3 Write property test for valid power state transitions
    - **Property 9: Valid power state transitions**
    - For nodes with provision_state in {available, active}, verify power on/off/rebooting transitions work correctly
    - **Validates: Requirements 7.1, 7.2, 7.3**
  - [x]* 6.4 Write property test for invalid power state transitions
    - **Property 10: Invalid power state transitions**
    - For nodes with provision_state in {enroll, manageable}, verify any set_power_state raises InvalidStateError
    - **Validates: Requirements 7.4**
  - [x]* 6.5 Write property test for mutation updates timestamp
    - **Property 11: Mutation updates timestamp**
    - For any successful state transition or update, verify updated_at is updated to a timestamp >= previous value
    - **Validates: Requirements 6.7, 7.5, 12.4**

- [x] 7. Implement port property tests
  - [x]* 7.1 Write property test for port creation with valid node
    - **Property 12: Port creation with valid node**
    - For any valid MAC and existing non-deleted node, verify create_port produces a port with valid UUID, correct node_id, and ISO 8601 created_at
    - **Validates: Requirements 8.1**
  - [x]* 7.2 Write property test for port creation with invalid node
    - **Property 13: Port creation with invalid node**
    - For any node_id not corresponding to an existing non-deleted node, verify create_port raises ResourceNotFoundError
    - **Validates: Requirements 8.2**
  - [x]* 7.3 Write property test for duplicate port MAC rejection
    - **Property 14: Duplicate port MAC rejection**
    - Create a port, then attempt to create another with the same MAC — verify DuplicateResourceError is raised
    - **Validates: Requirements 8.3**
  - [x]* 7.4 Write property test for port listing with node filter
    - **Property 15: Port listing with node filter**
    - Create ports on multiple nodes, verify list_ports(node_id=X) returns exactly the ports for that node
    - **Validates: Requirements 8.4, 8.5**

- [x] 8. Implement REST API Blueprint
  - [x] 8.1 Create `openstack_simulator/api/baremetal.py` with Flask Blueprint
    - Create `baremetal_bp = Blueprint("baremetal", __name__, url_prefix="/baremetal/v1")`
    - Implement `GET /nodes` — list all active nodes, return JSON `{"nodes": [...]}`
    - Implement `POST /nodes` — create node from request JSON, return 201 with node JSON
    - Implement `GET /nodes/<node_ident>` — get node by name or UUID, return node JSON or 404
    - Implement `PATCH /nodes/<node_ident>` — update node properties, return 200 with updated node JSON
    - Implement `DELETE /nodes/<node_ident>` — soft-delete node, return 204
    - Implement `PUT /nodes/<node_ident>/states/power` — change power state, return 202
    - Implement `PUT /nodes/<node_ident>/states/provision` — change provision state, return 202
    - Implement `GET /ports` — list ports with optional `?node_id=` filter, return JSON `{"ports": [...]}`
    - Implement `POST /ports` — create port from request JSON, return 201 with port JSON
    - Implement `DELETE /ports/<port_ident>` — soft-delete port, return 204
    - Apply `@require_token` decorator to all endpoints
    - Handle exceptions: ResourceNotFoundError→404, DuplicateResourceError→409, ResourceLimitExceededError→413, InvalidStateError→409
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 11.11, 11.12, 11.13, 11.14, 11.15, 12.5_
  - [x] 8.2 Register blueprint and update service catalog
    - Import and register `baremetal_bp` in `openstack_simulator/api/app.py`
    - Add baremetal service entry to `build_service_catalog` in `openstack_simulator/api/helpers.py` with type "baremetal", name "ironic", endpoint URL `{base_url}/baremetal/v1`
    - _Requirements: 11.1, 9.1, 9.2_

- [x] 9. Checkpoint - Verify full integration
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Write integration tests for REST API
  - [x]* 10.1 Write integration tests for node endpoints in `tests/test_baremetal_api.py`
    - Test POST /nodes creates node and returns 201
    - Test GET /nodes returns list of active nodes
    - Test GET /nodes/<ident> returns node or 404
    - Test PATCH /nodes/<ident> updates node or returns 404/409
    - Test DELETE /nodes/<ident> returns 204 or 404
    - Test PUT /nodes/<ident>/states/provision returns 202 or 409
    - Test PUT /nodes/<ident>/states/power returns 202 or 409
    - Test authentication requirement (401 without token)
    - Test error responses: 409 for duplicates, 413 for quota, 409 for invalid state
    - _Requirements: 11.1–11.15_
  - [x]* 10.2 Write integration tests for port endpoints in `tests/test_baremetal_api.py`
    - Test POST /ports creates port and returns 201
    - Test GET /ports returns list of active ports
    - Test GET /ports?node_id=X filters by node
    - Test DELETE /ports/<ident> returns 204 or 404
    - Test error responses: 404 for invalid node_id, 409 for duplicate MAC, 413 for quota
    - _Requirements: 11.8, 11.9, 11.10, 8.1–8.8_

- [x] 11. Final checkpoint - Full test suite
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 15 universal correctness properties from the design document
- Unit/integration tests validate specific examples, edge cases, and HTTP layer behavior
- The implementation language is Python 3.9+ as established by the existing codebase
- All state is in-memory — the new manager follows the same patterns as ComputeManager, VolumeManager, etc.
- The store uses `name` as key for nodes and `address` (MAC) as key for ports

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5", "4.6", "4.7", "4.8"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["10.1", "10.2"] }
  ]
}
```
