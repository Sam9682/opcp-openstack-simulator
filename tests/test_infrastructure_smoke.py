"""Smoke test: Verify infrastructure layer components work together."""

import uuid
from datetime import datetime

from openstack_simulator.store import ResourceStore
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.models import Instance
from openstack_simulator.exceptions import ResourceLimitExceededError


def test_store_add_and_get():
    """Test that we can add a resource and retrieve it."""
    store = ResourceStore()
    instance = Instance(
        id=str(uuid.uuid4()),
        name="test-server",
        flavor="m1.small",
        image="ubuntu-22.04",
        status="ACTIVE",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    store.add("instances", "test-server", instance)

    retrieved = store.get("instances", "test-server")
    assert retrieved is not None
    assert retrieved.name == "test-server"
    assert retrieved.flavor == "m1.small"


def test_store_list_active():
    """Test that list_active returns non-deleted resources."""
    store = ResourceStore()
    for i in range(3):
        inst = Instance(
            id=str(uuid.uuid4()),
            name=f"server-{i}",
            flavor="m1.small",
            image="ubuntu-22.04",
            status="ACTIVE",
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        store.add("instances", f"server-{i}", inst)

    active = store.list_active("instances")
    assert len(active) == 3


def test_store_count_active():
    """Test that count_active returns correct count."""
    store = ResourceStore()
    assert store.count_active("instances") == 0

    inst = Instance(
        id=str(uuid.uuid4()),
        name="server-1",
        flavor="m1.small",
        image="ubuntu-22.04",
        status="ACTIVE",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    store.add("instances", "server-1", inst)
    assert store.count_active("instances") == 1


def test_store_mark_deleted():
    """Test that mark_deleted excludes resource from get and list_active."""
    store = ResourceStore()
    inst = Instance(
        id=str(uuid.uuid4()),
        name="to-delete",
        flavor="m1.small",
        image="ubuntu-22.04",
        status="ACTIVE",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    store.add("instances", "to-delete", inst)
    assert store.get("instances", "to-delete") is not None

    store.mark_deleted("instances", "to-delete")
    assert store.get("instances", "to-delete") is None
    assert store.count_active("instances") == 0
    assert len(store.list_active("instances")) == 0


def test_limiter_passes_under_limit():
    """Test that limiter check passes when under limit."""
    store = ResourceStore()
    limiter = ResourceLimiter(limits={"instances": 3})

    inst = Instance(
        id=str(uuid.uuid4()),
        name="server-1",
        flavor="m1.small",
        image="ubuntu-22.04",
        status="ACTIVE",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    store.add("instances", "server-1", inst)

    # Should not raise
    limiter.check("instances", store)


def test_limiter_raises_at_limit():
    """Test that limiter raises ResourceLimitExceededError at limit."""
    store = ResourceStore()
    limiter = ResourceLimiter(limits={"instances": 3})

    for i in range(3):
        inst = Instance(
            id=str(uuid.uuid4()),
            name=f"server-{i}",
            flavor="m1.small",
            image="ubuntu-22.04",
            status="ACTIVE",
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        store.add("instances", f"server-{i}", inst)

    import pytest

    with pytest.raises(ResourceLimitExceededError):
        limiter.check("instances", store)


def test_limiter_passes_after_deletion():
    """Test that limiter passes again after a resource is deleted."""
    store = ResourceStore()
    limiter = ResourceLimiter(limits={"instances": 3})

    for i in range(3):
        inst = Instance(
            id=str(uuid.uuid4()),
            name=f"server-{i}",
            flavor="m1.small",
            image="ubuntu-22.04",
            status="ACTIVE",
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        store.add("instances", f"server-{i}", inst)

    # At limit - should raise
    import pytest

    with pytest.raises(ResourceLimitExceededError):
        limiter.check("instances", store)

    # Delete one
    store.mark_deleted("instances", "server-0")

    # Now should pass
    limiter.check("instances", store)


def test_integration_full_lifecycle():
    """Full lifecycle: create, get, list, count, limit check, delete, limit freed."""
    store = ResourceStore()
    limiter = ResourceLimiter(limits={"instances": 3})

    # Create 3 instances (at limit)
    for i in range(3):
        inst = Instance(
            id=str(uuid.uuid4()),
            name=f"vm-{i}",
            flavor="m1.small",
            image="ubuntu-22.04",
            status="ACTIVE",
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        store.add("instances", f"vm-{i}", inst)

    # Verify all are retrievable
    for i in range(3):
        assert store.get("instances", f"vm-{i}") is not None

    # Verify count and list
    assert store.count_active("instances") == 3
    assert len(store.list_active("instances")) == 3

    # Verify limit is enforced
    import pytest

    with pytest.raises(ResourceLimitExceededError):
        limiter.check("instances", store)

    # Delete one instance
    store.mark_deleted("instances", "vm-1")

    # Verify deleted instance is gone
    assert store.get("instances", "vm-1") is None
    assert store.count_active("instances") == 2
    assert len(store.list_active("instances")) == 2

    # Verify limit is freed
    limiter.check("instances", store)  # Should not raise


def test_model_serialization_roundtrip():
    """Test Instance to_dict/from_dict round-trip."""
    instance = Instance(
        id=str(uuid.uuid4()),
        name="roundtrip-test",
        flavor="m1.large",
        image="centos-8",
        status="ACTIVE",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    data = instance.to_dict()
    restored = Instance.from_dict(data)

    assert restored.id == instance.id
    assert restored.name == instance.name
    assert restored.flavor == instance.flavor
    assert restored.image == instance.image
    assert restored.status == instance.status
    assert restored.created_at == instance.created_at
