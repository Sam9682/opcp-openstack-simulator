# Implementation Plan: OpenStack Simulator for Training Labs

## Overview

Build a pure-Python, in-memory OpenStack simulator that implements five manager interfaces (auth, compute, network, volume, security group) as a drop-in replacement for the `opcp-openstack-first-steps` training framework. Implementation proceeds bottom-up: infrastructure layer first, then managers, then the facade, with property-based tests woven in alongside each component.

## Tasks

- [x] 1. Set up project structure and dependencies
  - [x] 1.1 Create `pyproject.toml` with project metadata, Python 3.9+ requirement, and dependencies (`pytest`, `hypothesis`, `pytest-cov`)
    - Configure the package as `openstack_simulator`
    - Add a `[project.scripts]` or `[tool.pytest.ini_options]` section for test discovery
    - _Requirements: 1.1_
  - [x] 1.2 Create package skeleton with `__init__.py` files
    - Create `openstack_simulator/__init__.py` (exports `Simulator` class)
    - Create `openstack_simulator/managers/__init__.py`
    - Create empty `tests/conftest.py`
    - _Requirements: 1.4_

- [x] 2. Implement exception hierarchy
  - [x] 2.1 Create `openstack_simulator/exceptions.py` with all custom exceptions
    - Implement `SimulatorError` base class
    - Implement `AuthenticationError`, `TokenExpiredError`, `ResourceLimitExceededError`, `DuplicateResourceError`, `ResourceNotFoundError`, `InvalidStateError`
    - Each exception should accept a descriptive message
    - _Requirements: 2.2, 2.4, 3.2, 3.3, 4.2, 4.3, 6.2, 6.3, 6.7, 6.8, 7.2, 7.3, 7.7, 11.2, 11.3_

- [x] 3. Implement data models
  - [x] 3.1 Create `openstack_simulator/models.py` with all dataclass models
    - Implement `Token`, `Instance`, `Network`, `Subnet`, `Router`, `Port`, `Bond`, `Volume`, `SecurityGroup`, `Rule`, `Snapshot` as `@dataclass` classes
    - Each model must have `to_dict()` instance method and `from_dict(data)` class method
    - Use `uuid.uuid4()` for IDs and `datetime.utcnow().isoformat() + "Z"` for timestamps
    - Use `field(default_factory=list)` for list fields like `subnet_ids`, `port_ids`, `rules`
    - _Requirements: 8.1, 8.2, 8.4, 12.2, 12.3_
  - [ ]* 3.2 Write property test for serialization round-trip (Property 26)
    - **Property 26: Serialization round-trip**
    - For each model type, generate random valid instances and verify `from_dict(instance.to_dict())` produces an equivalent object
    - **Validates: Requirements 12.2, 12.3**

- [x] 4. Implement ResourceStore
  - [x] 4.1 Create `openstack_simulator/store.py` with the `ResourceStore` class
    - Implement `__init__` with empty dicts for each resource type: `instances`, `networks`, `subnets`, `routers`, `ports`, `bonds`, `volumes`, `security_groups`, `tokens` and a `snapshots` list
    - Implement `add(resource_type, name, resource)` to store a resource
    - Implement `get(resource_type, name)` to retrieve a non-deleted resource (return None if not found or status is "DELETED")
    - Implement `list_active(resource_type)` to return all non-deleted resources
    - Implement `mark_deleted(resource_type, name)` to set status to "DELETED"
    - Implement `count_active(resource_type)` to count non-deleted resources
    - _Requirements: 1.1, 11.1, 12.1_
  - [ ]* 4.2 Write unit tests for ResourceStore
    - Test add/get/list_active/mark_deleted/count_active operations
    - Test that deleted resources are excluded from get and list_active
    - _Requirements: 1.1, 11.1, 12.1_

- [x] 5. Implement ResourceLimiter
  - [x] 5.1 Create `openstack_simulator/limiter.py` with the `ResourceLimiter` class
    - Implement `__init__(limits: dict[str, int])` to store per-type limits
    - Implement `check(resource_type, store)` that raises `ResourceLimitExceededError` when `store.count_active(resource_type) >= limit`
    - Implement `get_limit(resource_type)` to return the configured limit
    - _Requirements: 1.3, 9.1, 9.2, 9.3, 9.4_
  - [ ]* 5.2 Write unit tests for ResourceLimiter
    - Test that check passes when under limit
    - Test that check raises ResourceLimitExceededError when at limit
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 6. Checkpoint - Verify infrastructure layer
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement AuthManager
  - [x] 7.1 Create `openstack_simulator/managers/auth.py` with the `AuthManager` class
    - Implement `__init__(store, session_timeout=120)`
    - Implement `authenticate(username, password)` — raise `AuthenticationError` if either is empty; otherwise create and store a `Token` with UUID, username, `issued_at`, and `expires_at` (issued_at + session_timeout minutes)
    - Implement `validate_token(token_id)` — look up token by UUID, raise `ResourceNotFoundError` if unknown, raise `TokenExpiredError` if expired, return True if valid
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [ ]* 7.2 Write property tests for AuthManager (Properties 1, 2)
    - **Property 1: Authentication round-trip** — for any non-empty username/password, authenticate then validate succeeds and token contains correct fields
    - **Property 2: Empty credentials rejection** — for any pair where at least one is empty, authenticate raises AuthenticationError
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5**

- [x] 8. Implement ComputeManager
  - [x] 8.1 Create `openstack_simulator/managers/compute.py` with the `ComputeManager` class
    - Implement `__init__(store, limiter)`
    - Implement `create(name, flavor, image)` — check limit, check duplicate, create Instance with UUID, status "ACTIVE", created_at timestamp
    - Implement `get(name)` — return instance or None
    - Implement `resize(name, flavor)` — raise ResourceNotFoundError if not found, update flavor, set status to "RESIZE" then "ACTIVE"
    - Implement `snapshot(name, snapshot_name)` — raise ResourceNotFoundError if not found, create Snapshot record
    - Implement `delete(name)` — raise ResourceNotFoundError if not found, mark deleted
    - Implement `list()` — return all non-deleted instances
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 11.1, 11.2, 12.1_
  - [ ]* 8.2 Write property tests for ComputeManager (Properties 3, 4, 5, 6, 11, 12)
    - **Property 3: Create-get round-trip** — create instance, get by name returns matching resource
    - **Property 4: Get nonexistent returns None**
    - **Property 5: Resource limit enforcement** — fill to limit, next create raises error
    - **Property 6: Duplicate name rejection** — create twice with same name raises error
    - **Property 11: Instance resize updates flavor** — resize changes flavor, status is ACTIVE
    - **Property 12: Instance snapshot creation** — snapshot has correct source_id and fields
    - **Validates: Requirements 3.1–3.8, 9.1**

- [x] 9. Implement NetworkManager
  - [x] 9.1 Create `openstack_simulator/managers/network.py` with the `NetworkManager` class
    - Implement `__init__(store, limiter)`
    - Implement `create(name)` — check limit, check duplicate, create Network with UUID, status "ACTIVE", empty subnet_ids
    - Implement `get(name)` — return network or None
    - Implement `create_subnet(network_name, name, cidr, gateway)` — raise ResourceNotFoundError if network not found, create Subnet, add subnet ID to network's subnet_ids
    - Implement `create_router(name)` — create Router with UUID, status "ACTIVE", empty subnet_ids
    - Implement `add_router_interface(router_name, subnet_id)` — raise ResourceNotFoundError if router or subnet not found, add subnet_id to router's subnet_ids
    - Implement `create_port(network_name, name)` — raise ResourceNotFoundError if network not found, create Port with UUID, generated MAC address, status "ACTIVE"
    - Implement `create_bond(name, port_names, bond_mode)` — raise ResourceNotFoundError if any port not found, create Bond with port IDs, bond_mode, status "ACTIVE"
    - Implement `delete(name)` — raise ResourceNotFoundError if not found, mark deleted
    - Implement `list()` — return all non-deleted networks
    - _Requirements: 4.1–4.10, 5.1–5.5, 11.1, 11.2, 12.1_
  - [ ]* 9.2 Write property tests for NetworkManager (Properties 3, 4, 5, 6, 13, 14, 15, 16, 17, 18)
    - **Property 3: Create-get round-trip** — for networks
    - **Property 4: Get nonexistent returns None** — for networks
    - **Property 5: Resource limit enforcement** — for networks
    - **Property 6: Duplicate name rejection** — for networks
    - **Property 13: Subnet creation associates with network** — subnet ID appears in network's subnet_ids
    - **Property 14: Subnet on nonexistent network raises error**
    - **Property 15: Port creation on existing network** — port has correct network_id, MAC, status
    - **Property 16: Port on nonexistent network raises error**
    - **Property 17: Bond creation from existing ports** — bond references all port IDs
    - **Property 18: Bond with nonexistent port raises error**
    - **Validates: Requirements 4.1–4.10, 5.1–5.5, 9.2**

- [x] 10. Checkpoint - Verify auth, compute, and network managers
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement VolumeManager
  - [x] 11.1 Create `openstack_simulator/managers/volume.py` with the `VolumeManager` class
    - Implement `__init__(store, limiter)`
    - Implement `create(name, size)` — check limit, check duplicate, create Volume with UUID, status "available", created_at, attached_to=None
    - Implement `get(name)` — return volume or None
    - Implement `attach(volume_name, instance_name)` — raise ResourceNotFoundError if volume or instance not found, raise InvalidStateError if volume is "in-use", set status to "in-use" and attached_to to instance_name
    - Implement `snapshot(name, snapshot_name)` — raise ResourceNotFoundError if not found, create Snapshot record with source_type "volume"
    - Implement `delete(name)` — raise ResourceNotFoundError if not found, raise InvalidStateError if "in-use", mark deleted
    - Implement `list()` — return all non-deleted volumes
    - _Requirements: 6.1–6.10, 11.1, 11.2, 11.3, 12.1_
  - [ ]* 11.2 Write property tests for VolumeManager (Properties 3, 4, 5, 6, 19, 20, 21, 22, 23)
    - **Property 3: Create-get round-trip** — for volumes
    - **Property 4: Get nonexistent returns None** — for volumes
    - **Property 5: Resource limit enforcement** — for volumes
    - **Property 6: Duplicate name rejection** — for volumes
    - **Property 19: Volume attach updates status** — status becomes "in-use", attached_to set
    - **Property 20: Volume attach with nonexistent references raises error**
    - **Property 21: Double-attach raises InvalidStateError**
    - **Property 22: Volume snapshot creation** — snapshot has correct source_id and fields
    - **Property 23: Delete in-use volume raises InvalidStateError**
    - **Validates: Requirements 6.1–6.10, 9.3, 11.3**

- [x] 12. Implement SecurityGroupManager
  - [x] 12.1 Create `openstack_simulator/managers/security_group.py` with the `SecurityGroupManager` class
    - Implement `__init__(store, limiter)`
    - Implement `create(name, description)` — check limit, check duplicate, create SecurityGroup with UUID, empty rules list, status "ACTIVE", created_at
    - Implement `get(name)` — return security group or None (including all associated rules)
    - Implement `add_rule(sg_name, protocol, port_range, direction, remote_ip_prefix)` — raise ResourceNotFoundError if SG not found, create Rule with UUID, add to SG's rules list
    - Implement `delete_rule(rule_id)` — find and remove rule by UUID across all security groups, raise ResourceNotFoundError if not found
    - Implement `delete(name)` — raise ResourceNotFoundError if not found, mark deleted
    - Implement `list()` — return all non-deleted security groups
    - _Requirements: 7.1–7.9, 11.1, 11.2, 12.1_
  - [ ]* 12.2 Write property tests for SecurityGroupManager (Properties 3, 4, 5, 6, 24, 25)
    - **Property 3: Create-get round-trip** — for security groups
    - **Property 4: Get nonexistent returns None** — for security groups
    - **Property 5: Resource limit enforcement** — for security groups
    - **Property 6: Duplicate name rejection** — for security groups
    - **Property 24: Rule add and delete round-trip** — add rule increases count, delete removes it
    - **Property 25: Add rule to nonexistent SG raises error**
    - **Validates: Requirements 7.1–7.9, 9.4**

- [x] 13. Checkpoint - Verify all managers
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement Simulator facade
  - [x] 14.1 Create `openstack_simulator/simulator.py` with the `Simulator` class
    - Implement `__init__(config=None)` with default configuration: `default_flavor="m1.small"`, `default_image="ubuntu-22.04"`, `session_timeout=120`, `max_instances=3`, `max_networks=2`, `max_volumes=3`, `max_security_groups=5`
    - Initialize `ResourceStore` and `ResourceLimiter` with configured limits
    - Initialize all five managers with shared store and limiter references
    - Expose `auth_manager`, `compute_manager`, `network_manager`, `volume_manager`, `security_group_manager` attributes
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 14.2 Update `openstack_simulator/__init__.py` to export `Simulator` and all exception types
    - Export `Simulator` as the primary public API
    - Export all exceptions for consumer use
    - Export all model classes for type checking
    - _Requirements: 1.4, 10.1_
  - [ ]* 14.3 Write unit tests for Simulator initialization and assessment engine compatibility
    - Test that default config values are applied correctly
    - Test that all five manager attributes are accessible and correctly typed
    - Test assessment engine resource type mapping: "instance" → compute_manager, "network" → network_manager, "subnet" → network_manager, "router" → network_manager, "volume" → volume_manager, "security_group" → security_group_manager
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 10.1_

- [ ] 15. Implement cross-cutting property tests
  - [ ]* 15.1 Write property tests for UUID validity and uniqueness (Property 9)
    - **Property 9: UUID validity and uniqueness**
    - Create multiple resources across all types, verify every UUID matches v4 format and no duplicates exist
    - **Validates: Requirements 8.1, 8.3, 8.4**
  - [ ]* 15.2 Write property test for ISO 8601 timestamps (Property 10)
    - **Property 10: ISO 8601 timestamps**
    - For any created resource with a `created_at` field, verify the timestamp parses as valid ISO 8601
    - **Validates: Requirements 8.2**
  - [ ]* 15.3 Write property tests for delete-and-free-quota cycle (Property 7)
    - **Property 7: Delete excludes from get and frees quota**
    - Create a resource, delete it, verify get returns None, list excludes it, and a new resource can be created at the limit
    - **Validates: Requirements 9.5, 11.1, 11.4, 12.1**
  - [ ]* 15.4 Write property test for delete nonexistent (Property 8)
    - **Property 8: Delete nonexistent raises error**
    - For any name not corresponding to an existing resource, delete raises ResourceNotFoundError
    - **Validates: Requirements 11.2**
  - [ ]* 15.5 Write property test for list returns only non-deleted (Property 27)
    - **Property 27: List returns only non-deleted resources**
    - Perform a sequence of creates and deletes, verify list returns exactly the non-deleted set
    - **Validates: Requirements 12.1**

- [x] 16. Create shared test fixtures
  - [x] 16.1 Implement `tests/conftest.py` with shared pytest fixtures
    - Create a `simulator` fixture that returns a fresh `Simulator()` instance
    - Create individual manager fixtures: `auth_manager`, `compute_manager`, `network_manager`, `volume_manager`, `security_group_manager`
    - Create a `store` fixture and `limiter` fixture for infrastructure-level tests
    - Define reusable Hypothesis strategies for resource names, flavors, images, sizes, CIDRs, protocols, port ranges, directions, IP prefixes
    - _Requirements: 1.1, 1.4_

- [x] 17. Final checkpoint - Full test suite
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 27 universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and configuration
- The implementation language is Python 3.9+ as specified in the design
- All state is in-memory — no database or persistence layer needed
