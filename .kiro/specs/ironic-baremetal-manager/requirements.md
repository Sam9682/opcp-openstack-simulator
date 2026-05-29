# Requirements Document

## Introduction

This document specifies the requirements for adding an Ironic (Bare Metal) manager to the OpenStack Simulator. The Baremetal_Manager simulates OpenStack Ironic's node and port lifecycle management, following the same in-memory patterns established by the existing managers (ComputeManager, NetworkManager, VolumeManager, SecurityGroupManager). The feature includes data models, a manager class, REST API endpoints, and integration into the Simulator facade.

## Glossary

- **Baremetal_Manager**: The simulated Ironic manager class responsible for baremetal node and port lifecycle operations.
- **Baremetal_Node**: A dataclass representing a simulated physical machine with properties such as driver, power state, provision state, and hardware specifications.
- **Baremetal_Port**: A dataclass representing a network interface on a Baremetal_Node, identified by MAC address and associated with a specific node.
- **Resource_Store**: The central in-memory dictionary-based storage shared across all managers.
- **Resource_Limiter**: The quota enforcement component that raises ResourceLimitExceededError when active resource counts reach configured limits.
- **Provision_State**: The lifecycle state of a Baremetal_Node, following the sequence: enroll → manageable → available → active → deleted.
- **Power_State**: The simulated power status of a Baremetal_Node: power on, power off, or rebooting.
- **Simulator_Facade**: The top-level Simulator class that wires all managers together with shared store and limiter.
- **REST_API_Blueprint**: A Flask Blueprint providing HTTP endpoints for the Ironic Baremetal service at `/baremetal/v1/`.

## Requirements

### Requirement 1: Baremetal Node Data Model

**User Story:** As a developer, I want a Baremetal_Node dataclass that follows the existing model patterns, so that node state can be stored, serialized, and deserialized consistently.

#### Acceptance Criteria

1. THE Baremetal_Node SHALL contain fields: id (UUID string), name (string), driver (string), power_state (string), provision_state (string), memory_mb (int), cpus (int), local_gb (int), cpu_arch (string), driver_info (dict), properties (dict), status (string), created_at (ISO 8601 string), and updated_at (ISO 8601 string).
2. THE Baremetal_Node SHALL implement a to_dict method that returns a dictionary containing all fields.
3. THE Baremetal_Node SHALL implement a from_dict class method that constructs a Baremetal_Node from a dictionary.
4. FOR ALL valid Baremetal_Node instances, calling from_dict on the result of to_dict SHALL produce an equivalent Baremetal_Node (round-trip property).

### Requirement 2: Baremetal Port Data Model

**User Story:** As a developer, I want a Baremetal_Port dataclass that represents network interfaces on nodes, so that port-to-node associations can be tracked.

#### Acceptance Criteria

1. THE Baremetal_Port SHALL contain fields: id (UUID string), node_id (UUID string referencing the parent Baremetal_Node), address (MAC address string), status (string), and created_at (ISO 8601 string).
2. THE Baremetal_Port SHALL implement a to_dict method that returns a dictionary containing all fields.
3. THE Baremetal_Port SHALL implement a from_dict class method that constructs a Baremetal_Port from a dictionary.
4. FOR ALL valid Baremetal_Port instances, calling from_dict on the result of to_dict SHALL produce an equivalent Baremetal_Port (round-trip property).

### Requirement 3: Node Creation

**User Story:** As a simulator user, I want to create baremetal nodes with specified hardware properties, so that I can simulate enrolling physical machines.

#### Acceptance Criteria

1. WHEN a create_node request is received with a valid name, driver, and hardware properties, THE Baremetal_Manager SHALL create a Baremetal_Node with provision_state set to "enroll" and power_state set to "power off".
2. WHEN a create_node request is received, THE Baremetal_Manager SHALL assign a UUID v4 identifier and an ISO 8601 created_at timestamp to the new Baremetal_Node.
3. WHEN a create_node request specifies a name that already exists among non-deleted nodes, THE Baremetal_Manager SHALL raise a DuplicateResourceError.
4. WHEN the active baremetal_nodes count equals or exceeds the configured limit, THE Baremetal_Manager SHALL raise a ResourceLimitExceededError.
5. THE Baremetal_Manager SHALL store the created Baremetal_Node in the Resource_Store under the "baremetal_nodes" resource type.

### Requirement 4: Node Retrieval and Listing

**User Story:** As a simulator user, I want to retrieve individual nodes and list all active nodes, so that I can inspect the current baremetal inventory.

#### Acceptance Criteria

1. WHEN a get_node request is received with a valid node name, THE Baremetal_Manager SHALL return the corresponding Baremetal_Node.
2. WHEN a get_node request is received with a name that does not exist or is deleted, THE Baremetal_Manager SHALL return None.
3. WHEN a list_nodes request is received, THE Baremetal_Manager SHALL return all non-deleted Baremetal_Nodes from the Resource_Store.

### Requirement 5: Node Deletion

**User Story:** As a simulator user, I want to delete baremetal nodes using a soft-delete pattern, so that deleted nodes are excluded from active listings without losing state.

#### Acceptance Criteria

1. WHEN a delete_node request is received for an existing node, THE Baremetal_Manager SHALL set the node status to "DELETED" and provision_state to "deleted" via the Resource_Store mark_deleted mechanism.
2. WHEN a delete_node request is received for a node that does not exist, THE Baremetal_Manager SHALL raise a ResourceNotFoundError.
3. WHILE a Baremetal_Node has status "DELETED", THE Resource_Store SHALL exclude the node from get and list_active results.

### Requirement 6: Node Provision State Transitions

**User Story:** As a simulator user, I want to transition nodes through the Ironic provision lifecycle, so that I can simulate the full enrollment-to-deployment workflow.

#### Acceptance Criteria

1. WHEN a set_provision_state request with target "manage" is received for a node in provision_state "enroll", THE Baremetal_Manager SHALL transition the node to provision_state "manageable".
2. WHEN a set_provision_state request with target "provide" is received for a node in provision_state "manageable", THE Baremetal_Manager SHALL transition the node to provision_state "available".
3. WHEN a set_provision_state request with target "active" is received for a node in provision_state "available", THE Baremetal_Manager SHALL transition the node to provision_state "active" and set power_state to "power on".
4. WHEN a set_provision_state request with target "deleted" is received for a node in provision_state "active" or "available", THE Baremetal_Manager SHALL transition the node to provision_state "available" (undeploy) or invoke soft-delete respectively.
5. WHEN a set_provision_state request with target "clean" is received for a node in provision_state "manageable", THE Baremetal_Manager SHALL transition the node to provision_state "cleaning" and then to "manageable".
6. IF a set_provision_state request specifies an invalid transition for the current provision_state, THEN THE Baremetal_Manager SHALL raise an InvalidStateError.
7. WHEN a provision state transition completes, THE Baremetal_Manager SHALL update the updated_at field with the current ISO 8601 timestamp.

### Requirement 7: Node Power Management

**User Story:** As a simulator user, I want to control the power state of baremetal nodes, so that I can simulate power on, power off, and reboot operations.

#### Acceptance Criteria

1. WHEN a set_power_state request with target "power on" is received for a node with provision_state "active" or "available", THE Baremetal_Manager SHALL set the node power_state to "power on".
2. WHEN a set_power_state request with target "power off" is received for a node with provision_state "active" or "available", THE Baremetal_Manager SHALL set the node power_state to "power off".
3. WHEN a set_power_state request with target "rebooting" is received for a node with power_state "power on", THE Baremetal_Manager SHALL set the node power_state to "rebooting" and then to "power on".
4. IF a set_power_state request is received for a node in provision_state "enroll" or "manageable", THEN THE Baremetal_Manager SHALL raise an InvalidStateError.
5. WHEN a power state change completes, THE Baremetal_Manager SHALL update the updated_at field with the current ISO 8601 timestamp.

### Requirement 8: Port Management

**User Story:** As a simulator user, I want to create, list, and delete ports on baremetal nodes, so that I can simulate network interface configuration.

#### Acceptance Criteria

1. WHEN a create_port request is received with a valid node_id and MAC address, THE Baremetal_Manager SHALL create a Baremetal_Port with a UUID v4 identifier and ISO 8601 created_at timestamp.
2. WHEN a create_port request references a node_id that does not correspond to an existing non-deleted node, THE Baremetal_Manager SHALL raise a ResourceNotFoundError.
3. WHEN a create_port request specifies a MAC address that already exists among non-deleted ports, THE Baremetal_Manager SHALL raise a DuplicateResourceError.
4. WHEN a list_ports request is received with a node_id filter, THE Baremetal_Manager SHALL return all non-deleted Baremetal_Ports associated with that node.
5. WHEN a list_ports request is received without a filter, THE Baremetal_Manager SHALL return all non-deleted Baremetal_Ports.
6. WHEN a delete_port request is received for an existing port, THE Baremetal_Manager SHALL soft-delete the port by setting its status to "DELETED".
7. WHEN a delete_port request is received for a port that does not exist, THE Baremetal_Manager SHALL raise a ResourceNotFoundError.
8. WHEN the active baremetal_ports count equals or exceeds the configured limit, THE Baremetal_Manager SHALL raise a ResourceLimitExceededError.

### Requirement 9: Simulator Facade Integration

**User Story:** As a developer, I want the Baremetal_Manager to be accessible via the Simulator facade, so that it follows the same access pattern as existing managers.

#### Acceptance Criteria

1. THE Simulator_Facade SHALL expose the Baremetal_Manager as the attribute `baremetal_manager`.
2. THE Simulator_Facade SHALL pass the shared Resource_Store and Resource_Limiter to the Baremetal_Manager during initialization.
3. THE Simulator_Facade SHALL include "max_baremetal_nodes" and "max_baremetal_ports" in the default configuration with default values.
4. THE Resource_Limiter SHALL enforce limits for resource types "baremetal_nodes" and "baremetal_ports".

### Requirement 10: Resource Store Integration

**User Story:** As a developer, I want baremetal resources stored in the shared Resource_Store, so that they follow the same storage and soft-delete patterns as other resources.

#### Acceptance Criteria

1. THE Resource_Store SHALL contain a `baremetal_nodes` dictionary attribute for storing Baremetal_Node instances keyed by name.
2. THE Resource_Store SHALL contain a `baremetal_ports` dictionary attribute for storing Baremetal_Port instances keyed by MAC address.
3. THE Resource_Store SHALL support add, get, list_active, mark_deleted, and count_active operations for both "baremetal_nodes" and "baremetal_ports" resource types.

### Requirement 11: REST API Blueprint

**User Story:** As a simulator user, I want a REST API at `/baremetal/v1/` compatible with the OpenStack CLI, so that I can interact with baremetal resources via HTTP.

#### Acceptance Criteria

1. THE REST_API_Blueprint SHALL be registered at URL prefix `/baremetal/v1/`.
2. WHEN a GET request is received at `/baremetal/v1/nodes`, THE REST_API_Blueprint SHALL return a JSON list of all active Baremetal_Nodes.
3. WHEN a GET request is received at `/baremetal/v1/nodes/<node_ident>`, THE REST_API_Blueprint SHALL return the JSON representation of the specified node or a 404 response.
4. WHEN a POST request is received at `/baremetal/v1/nodes`, THE REST_API_Blueprint SHALL create a new Baremetal_Node and return a 201 response with the node JSON.
5. WHEN a DELETE request is received at `/baremetal/v1/nodes/<node_ident>`, THE REST_API_Blueprint SHALL soft-delete the node and return a 204 response.
6. WHEN a PUT request is received at `/baremetal/v1/nodes/<node_ident>/states/power`, THE REST_API_Blueprint SHALL invoke the power state change and return a 202 response.
7. WHEN a PUT request is received at `/baremetal/v1/nodes/<node_ident>/states/provision`, THE REST_API_Blueprint SHALL invoke the provision state transition and return a 202 response.
8. WHEN a GET request is received at `/baremetal/v1/ports`, THE REST_API_Blueprint SHALL return a JSON list of all active Baremetal_Ports, optionally filtered by node_id query parameter.
9. WHEN a POST request is received at `/baremetal/v1/ports`, THE REST_API_Blueprint SHALL create a new Baremetal_Port and return a 201 response.
10. WHEN a DELETE request is received at `/baremetal/v1/ports/<port_ident>`, THE REST_API_Blueprint SHALL soft-delete the port and return a 204 response.
11. THE REST_API_Blueprint SHALL require a valid authentication token for all endpoints, following the same pattern as existing API blueprints.
12. IF an API request triggers a ResourceNotFoundError, THEN THE REST_API_Blueprint SHALL return a 404 JSON error response.
13. IF an API request triggers a DuplicateResourceError, THEN THE REST_API_Blueprint SHALL return a 409 JSON error response.
14. IF an API request triggers a ResourceLimitExceededError, THEN THE REST_API_Blueprint SHALL return a 413 JSON error response.
15. IF an API request triggers an InvalidStateError, THEN THE REST_API_Blueprint SHALL return a 409 JSON error response with a descriptive message.

### Requirement 12: Node Update

**User Story:** As a simulator user, I want to update baremetal node properties after creation, so that I can modify hardware specifications or driver information.

#### Acceptance Criteria

1. WHEN an update_node request is received with valid property changes for an existing node, THE Baremetal_Manager SHALL apply the changes to the Baremetal_Node fields.
2. WHEN an update_node request is received for a node that does not exist, THE Baremetal_Manager SHALL raise a ResourceNotFoundError.
3. WHEN an update_node request modifies the name to a value already used by another non-deleted node, THE Baremetal_Manager SHALL raise a DuplicateResourceError.
4. WHEN a node update completes, THE Baremetal_Manager SHALL update the updated_at field with the current ISO 8601 timestamp.
5. WHEN a PATCH request is received at `/baremetal/v1/nodes/<node_ident>`, THE REST_API_Blueprint SHALL invoke the update operation and return a 200 response with the updated node JSON.
