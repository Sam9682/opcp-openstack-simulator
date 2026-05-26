# Requirements Document

## Introduction

The OpenStack Simulator is a lightweight, in-memory simulation layer that replaces real OpenStack API calls, enabling users to run the `opcp-openstack-first-steps` training project without access to a live OpenStack platform. The simulator implements the same manager interfaces (auth, compute, network, volume, security group) that the training exercises call, tracks resource state in memory, enforces resource limits, and produces realistic responses (UUIDs, timestamps, status transitions). It serves as a drop-in replacement so that all ~17 exercises across 7 lab modules work unchanged.

## Glossary

- **Simulator**: The OpenStack Simulator system that provides in-memory implementations of OpenStack manager interfaces
- **Auth_Manager**: The simulated Keystone authentication manager responsible for authenticating users and managing tokens
- **Compute_Manager**: The simulated Nova compute manager responsible for instance lifecycle operations
- **Network_Manager**: The simulated Neutron networking manager responsible for network, subnet, router, port, and bond operations
- **Volume_Manager**: The simulated Cinder storage manager responsible for volume lifecycle and snapshot operations
- **Security_Group_Manager**: The simulated Neutron security group manager responsible for security group and rule operations
- **Resource_Store**: The in-memory data store that holds all simulated OpenStack resources and their current state
- **Assessment_Engine**: The training framework component that queries resource state to verify exercise completion
- **Token**: A simulated authentication token with an expiration time, issued upon successful authentication
- **Instance**: A simulated compute instance with attributes including name, flavor, image, status, and UUID
- **Network**: A simulated network resource with attributes including name, subnets, and UUID
- **Subnet**: A simulated subnet resource associated with a network, containing CIDR and gateway information
- **Router**: A simulated router resource that connects subnets and networks
- **Port**: A simulated network port attached to a network
- **Bond**: A simulated LACP bond aggregating multiple ports with a specified bond mode
- **Volume**: A simulated block storage volume with name, size, status, and optional instance attachment
- **Security_Group**: A simulated security group containing a set of rules that control traffic
- **Rule**: A single ingress or egress rule within a Security_Group specifying protocol, port range, and direction
- **Resource_Limiter**: The component that enforces maximum resource counts per resource type
- **UUID**: A universally unique identifier in standard format (e.g., 550e8400-e29b-41d4-a716-446655440000) assigned to every simulated resource
- **Status_Transition**: A change in a resource's status field following a defined lifecycle (e.g., BUILDING → ACTIVE → DELETED)

## Requirements

### Requirement 1: Simulator Initialization and Configuration

**User Story:** As a training lab user, I want the simulator to initialize with default configuration values, so that I can start exercises without manual setup.

#### Acceptance Criteria

1. WHEN the Simulator is initialized, THE Simulator SHALL create an empty Resource_Store for each resource type (instances, networks, subnets, routers, ports, bonds, volumes, security groups, tokens)
2. WHEN the Simulator is initialized, THE Simulator SHALL load default configuration values including default flavor "m1.small", default image "ubuntu-22.04", and session timeout of 120 minutes
3. WHEN the Simulator is initialized, THE Simulator SHALL register resource limits of max_instances: 3, max_networks: 2, max_volumes: 3, and max_security_groups: 5 with the Resource_Limiter
4. WHEN the Simulator is initialized, THE Simulator SHALL expose auth_manager, compute_manager, network_manager, volume_manager, and security_group_manager attributes that implement the same method signatures as the training framework expects

### Requirement 2: Authentication and Token Management

**User Story:** As a training lab user, I want to authenticate with the simulator and receive tokens, so that I can complete authentication exercises.

#### Acceptance Criteria

1. WHEN the Auth_Manager receives an authenticate call with a valid username and password, THE Auth_Manager SHALL return a Token containing a UUID, the username, an issued_at timestamp, and an expires_at timestamp set to 120 minutes after issuance
2. WHEN the Auth_Manager receives an authenticate call with an empty username or an empty password, THE Auth_Manager SHALL raise an authentication error
3. WHILE a Token has not passed its expires_at timestamp, THE Auth_Manager SHALL treat the Token as valid
4. WHEN the Auth_Manager is asked to validate a Token that has passed its expires_at timestamp, THE Auth_Manager SHALL raise a token-expired error
5. FOR ALL valid username and password pairs, authenticating and then validating the returned Token SHALL succeed (round-trip property)

### Requirement 3: Compute Instance Management

**User Story:** As a training lab user, I want to create, retrieve, resize, and snapshot instances, so that I can complete compute exercises.

#### Acceptance Criteria

1. WHEN the Compute_Manager receives a create call with a name, flavor, and image, THE Compute_Manager SHALL return an Instance with a generated UUID, the provided name, flavor, image, status "ACTIVE", and a created_at timestamp
2. WHEN the Compute_Manager receives a create call and the number of existing non-deleted instances equals the max_instances limit, THE Compute_Manager SHALL raise a resource-limit-exceeded error
3. WHEN the Compute_Manager receives a create call with a name that matches an existing non-deleted Instance, THE Compute_Manager SHALL raise a duplicate-resource error
4. WHEN the Compute_Manager receives a get call with a name that matches an existing Instance, THE Compute_Manager SHALL return that Instance with its current state
5. WHEN the Compute_Manager receives a get call with a name that does not match any existing Instance, THE Compute_Manager SHALL return None
6. WHEN the Compute_Manager receives a resize call for an existing Instance with a new flavor, THE Compute_Manager SHALL update the Instance flavor and set the status to "RESIZE" then to "ACTIVE"
7. WHEN the Compute_Manager receives a snapshot request for an existing Instance, THE Compute_Manager SHALL create a snapshot record containing the Instance UUID, a snapshot UUID, a name, and a created_at timestamp
8. FOR ALL Instances created with unique names within the resource limit, creating an Instance and then getting the Instance by name SHALL return an equivalent Instance (round-trip property)

### Requirement 4: Network Management

**User Story:** As a training lab user, I want to create and manage networks, subnets, and routers, so that I can complete networking exercises.

#### Acceptance Criteria

1. WHEN the Network_Manager receives a create call with a name, THE Network_Manager SHALL return a Network with a generated UUID, the provided name, status "ACTIVE", and a created_at timestamp
2. WHEN the Network_Manager receives a create call and the number of existing non-deleted networks equals the max_networks limit, THE Network_Manager SHALL raise a resource-limit-exceeded error
3. WHEN the Network_Manager receives a create call with a name that matches an existing non-deleted Network, THE Network_Manager SHALL raise a duplicate-resource error
4. WHEN the Network_Manager receives a get call with a name that matches an existing Network, THE Network_Manager SHALL return that Network with its current state
5. WHEN the Network_Manager receives a get call with a name that does not match any existing Network, THE Network_Manager SHALL return None
6. WHEN the Network_Manager receives a create_subnet call with a network name, subnet name, CIDR, and gateway, THE Network_Manager SHALL create a Subnet with a generated UUID and associate the Subnet with the specified Network
7. IF the Network_Manager receives a create_subnet call referencing a network name that does not exist, THEN THE Network_Manager SHALL raise a resource-not-found error
8. WHEN the Network_Manager receives a create_router call with a name, THE Network_Manager SHALL return a Router with a generated UUID, the provided name, and status "ACTIVE"
9. WHEN the Network_Manager receives an add_router_interface call with a router name and a subnet identifier, THE Network_Manager SHALL associate the Subnet with the Router
10. FOR ALL Networks created with unique names within the resource limit, creating a Network and then getting the Network by name SHALL return an equivalent Network (round-trip property)

### Requirement 5: Port and Bond Management (LACP)

**User Story:** As a training lab user, I want to create ports and LACP bonds, so that I can complete LACP exercises.

#### Acceptance Criteria

1. WHEN the Network_Manager receives a create_port call with a network name and a port name, THE Network_Manager SHALL return a Port with a generated UUID, the provided name, the associated network UUID, a generated MAC address, and status "ACTIVE"
2. IF the Network_Manager receives a create_port call referencing a network name that does not exist, THEN THE Network_Manager SHALL raise a resource-not-found error
3. WHEN the Network_Manager receives a create_bond call with a bond name, a list of port names, and a bond mode, THE Network_Manager SHALL return a Bond with a generated UUID, the provided name, references to the specified Ports, the bond mode, and status "ACTIVE"
4. IF the Network_Manager receives a create_bond call referencing a port name that does not exist, THEN THE Network_Manager SHALL raise a resource-not-found error
5. FOR ALL Ports created on existing Networks, creating a Port and then retrieving the Port by name SHALL return an equivalent Port (round-trip property)

### Requirement 6: Volume Management

**User Story:** As a training lab user, I want to create, retrieve, attach, and snapshot volumes, so that I can complete storage exercises.

#### Acceptance Criteria

1. WHEN the Volume_Manager receives a create call with a name and size in GB, THE Volume_Manager SHALL return a Volume with a generated UUID, the provided name, the specified size, status "available", and a created_at timestamp
2. WHEN the Volume_Manager receives a create call and the number of existing non-deleted volumes equals the max_volumes limit, THE Volume_Manager SHALL raise a resource-limit-exceeded error
3. WHEN the Volume_Manager receives a create call with a name that matches an existing non-deleted Volume, THE Volume_Manager SHALL raise a duplicate-resource error
4. WHEN the Volume_Manager receives a get call with a name that matches an existing Volume, THE Volume_Manager SHALL return that Volume with its current state
5. WHEN the Volume_Manager receives a get call with a name that does not match any existing Volume, THE Volume_Manager SHALL return None
6. WHEN the Volume_Manager receives an attach call with a volume name and an instance name, THE Volume_Manager SHALL set the Volume status to "in-use" and record the attachment to the specified Instance
7. IF the Volume_Manager receives an attach call referencing a volume name or instance name that does not exist, THEN THE Volume_Manager SHALL raise a resource-not-found error
8. IF the Volume_Manager receives an attach call for a Volume that already has status "in-use", THEN THE Volume_Manager SHALL raise an invalid-state error
9. WHEN the Volume_Manager receives a snapshot request for an existing Volume, THE Volume_Manager SHALL create a snapshot record containing the Volume UUID, a snapshot UUID, a name, and a created_at timestamp
10. FOR ALL Volumes created with unique names within the resource limit, creating a Volume and then getting the Volume by name SHALL return an equivalent Volume (round-trip property)

### Requirement 7: Security Group Management

**User Story:** As a training lab user, I want to create security groups and manage rules, so that I can complete security group exercises.

#### Acceptance Criteria

1. WHEN the Security_Group_Manager receives a create call with a name and description, THE Security_Group_Manager SHALL return a Security_Group with a generated UUID, the provided name, the provided description, an empty rules list, and a created_at timestamp
2. WHEN the Security_Group_Manager receives a create call and the number of existing non-deleted security groups equals the max_security_groups limit, THE Security_Group_Manager SHALL raise a resource-limit-exceeded error
3. WHEN the Security_Group_Manager receives a create call with a name that matches an existing non-deleted Security_Group, THE Security_Group_Manager SHALL raise a duplicate-resource error
4. WHEN the Security_Group_Manager receives a get call with a name that matches an existing Security_Group, THE Security_Group_Manager SHALL return that Security_Group with its current state including all associated Rules
5. WHEN the Security_Group_Manager receives a get call with a name that does not match any existing Security_Group, THE Security_Group_Manager SHALL return None
6. WHEN the Security_Group_Manager receives an add_rule call with a security group name, protocol, port range, direction, and remote IP prefix, THE Security_Group_Manager SHALL add a Rule with a generated UUID to the specified Security_Group
7. IF the Security_Group_Manager receives an add_rule call referencing a security group name that does not exist, THEN THE Security_Group_Manager SHALL raise a resource-not-found error
8. WHEN the Security_Group_Manager receives a delete_rule call with a rule UUID, THE Security_Group_Manager SHALL remove the specified Rule from its Security_Group
9. FOR ALL Security_Groups created with unique names within the resource limit, creating a Security_Group and then getting the Security_Group by name SHALL return an equivalent Security_Group (round-trip property)

### Requirement 8: Resource Identification and Timestamps

**User Story:** As a training lab user, I want simulated resources to have realistic identifiers and timestamps, so that the simulation feels authentic and the assessment engine can process resources correctly.

#### Acceptance Criteria

1. THE Simulator SHALL assign a unique UUID in standard format (8-4-4-4-12 hexadecimal) to every created resource
2. THE Simulator SHALL assign a created_at timestamp in ISO 8601 format to every created resource
3. THE Simulator SHALL guarantee that no two resources share the same UUID across all resource types
4. FOR ALL resources created by the Simulator, each resource UUID SHALL be a valid version-4 UUID

### Requirement 9: Resource Limit Enforcement

**User Story:** As a training lab user, I want the simulator to enforce resource limits, so that the training experience matches real OpenStack quota behavior.

#### Acceptance Criteria

1. WHILE the number of non-deleted Instances in the Resource_Store equals max_instances (3), THE Compute_Manager SHALL reject new Instance creation requests with a resource-limit-exceeded error
2. WHILE the number of non-deleted Networks in the Resource_Store equals max_networks (2), THE Network_Manager SHALL reject new Network creation requests with a resource-limit-exceeded error
3. WHILE the number of non-deleted Volumes in the Resource_Store equals max_volumes (3), THE Volume_Manager SHALL reject new Volume creation requests with a resource-limit-exceeded error
4. WHILE the number of non-deleted Security_Groups in the Resource_Store equals max_security_groups (5), THE Security_Group_Manager SHALL reject new Security_Group creation requests with a resource-limit-exceeded error
5. WHEN a resource is deleted, THE Resource_Limiter SHALL decrement the count for that resource type, allowing new resources to be created

### Requirement 10: Assessment Engine Compatibility

**User Story:** As a training lab user, I want the assessment engine to query simulated resources the same way it queries real OpenStack resources, so that exercise validation works correctly.

#### Acceptance Criteria

1. THE Simulator SHALL support the Assessment_Engine resource type mapping: "instance" maps to Compute_Manager, "network" maps to Network_Manager, "subnet" maps to Network_Manager, "router" maps to Network_Manager, "volume" maps to Volume_Manager, and "security_group" maps to Security_Group_Manager
2. WHEN the Assessment_Engine queries a resource by name through the appropriate manager, THE manager SHALL return the resource object with all attributes needed for assessment comparison
3. WHEN the Assessment_Engine queries a resource by name that does not exist, THE manager SHALL return None without raising an error
4. FOR ALL resources created through any manager, querying the resource by name through the same manager SHALL return a resource with matching name, type, and status (round-trip property)

### Requirement 11: Resource Deletion

**User Story:** As a training lab user, I want to delete simulated resources, so that I can free up quota and repeat exercises.

#### Acceptance Criteria

1. WHEN a manager receives a delete call for an existing resource by name, THE manager SHALL mark the resource status as "DELETED" and exclude the resource from subsequent get-by-name queries
2. WHEN a manager receives a delete call for a resource name that does not exist, THE manager SHALL raise a resource-not-found error
3. IF the Volume_Manager receives a delete call for a Volume with status "in-use", THEN THE Volume_Manager SHALL raise an invalid-state error
4. WHEN a resource is marked as "DELETED", THE Resource_Limiter SHALL no longer count that resource toward the resource limit for its type

### Requirement 12: Serialization and State Inspection

**User Story:** As a training lab user, I want to inspect the current state of all simulated resources, so that I can debug exercises and understand the simulated environment.

#### Acceptance Criteria

1. THE Simulator SHALL provide a list operation on each manager that returns all non-deleted resources of that type
2. THE Simulator SHALL serialize each resource to a dictionary representation containing all resource attributes
3. FOR ALL resources created by the Simulator, serializing a resource to a dictionary and reconstructing the resource from that dictionary SHALL produce an equivalent resource (round-trip property)
