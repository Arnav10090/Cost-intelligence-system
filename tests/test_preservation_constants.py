"""
Preservation Property Tests for SLA Scenario API Error Fix

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

This test suite verifies that the fix for duplicate SCAN_SLA enum member
preserves all existing behavior for non-buggy enum members and modules.

IMPORTANT: These tests should PASS on unfixed code (with duplicate temporarily
commented out to observe baseline) and continue to PASS after the fix.

Property 2: Preservation - Other Enum Members Unchanged
For any code that references TaskType enum members other than SCAN_SLA,
the fixed code SHALL produce exactly the same enum values and behavior as
the original code, preserving all existing task routing and processing functionality.
"""

import pytest
from hypothesis import given, strategies as st, settings


# ═══════════════════════════════════════════════════════════════════════════
# Property 2.1: Other TaskType Enum Members Resolve Correctly
# ═══════════════════════════════════════════════════════════════════════════

def test_other_tasktype_members_exist():
    """
    Test that all non-SCAN_SLA TaskType enum members exist and are accessible.
    
    This verifies requirement 3.2: Other TaskType enum members continue to resolve correctly.
    """
    from core.constants import TaskType
    
    # Expected non-SCAN_SLA members
    expected_members = [
        "SCAN_DUPLICATES",
        "SCAN_LICENSES", 
        "RECONCILE",
        "SCAN_PRICING",
        "SCAN_INFRA",
        "DEMO_TRIGGER"
    ]
    
    for member_name in expected_members:
        assert hasattr(TaskType, member_name), f"TaskType.{member_name} should exist"
        member = getattr(TaskType, member_name)
        assert isinstance(member.value, str), f"TaskType.{member_name} should have a string value"


def test_other_tasktype_members_have_correct_values():
    """
    Test that all non-SCAN_SLA TaskType enum members resolve to their expected string values.
    
    This verifies requirement 3.2: Other TaskType enum members continue to resolve correctly.
    """
    from core.constants import TaskType
    
    # Expected member name -> value mappings (observed baseline behavior)
    expected_values = {
        "SCAN_DUPLICATES": "scan_duplicates",
        "SCAN_LICENSES": "scan_licenses",
        "RECONCILE": "reconcile",
        "SCAN_PRICING": "scan_pricing",
        "SCAN_INFRA": "scan_infra",
        "DEMO_TRIGGER": "demo_trigger"
    }
    
    for member_name, expected_value in expected_values.items():
        member = getattr(TaskType, member_name)
        assert member.value == expected_value, \
            f"TaskType.{member_name} should resolve to '{expected_value}', got '{member.value}'"


@given(st.sampled_from([
    ("SCAN_DUPLICATES", "scan_duplicates"),
    ("SCAN_LICENSES", "scan_licenses"),
    ("RECONCILE", "reconcile"),
    ("SCAN_PRICING", "scan_pricing"),
    ("SCAN_INFRA", "scan_infra"),
    ("DEMO_TRIGGER", "demo_trigger")
]))
@settings(max_examples=50)
def test_property_other_tasktype_members_unchanged(member_tuple):
    """
    Property-based test: All non-SCAN_SLA TaskType enum members should resolve
    to their expected string values consistently.
    
    This property test generates many test cases to ensure preservation of
    existing enum member behavior across all non-buggy members.
    
    **Validates: Requirements 3.2**
    """
    member_name, expected_value = member_tuple
    from core.constants import TaskType
    
    # Verify member exists
    assert hasattr(TaskType, member_name), f"TaskType.{member_name} should exist"
    
    # Verify member has correct value
    member = getattr(TaskType, member_name)
    assert member.value == expected_value, \
        f"TaskType.{member_name} should resolve to '{expected_value}'"
    
    # Verify member is a valid enum instance
    assert member in TaskType, f"TaskType.{member_name} should be a valid TaskType enum member"


# ═══════════════════════════════════════════════════════════════════════════
# Property 2.2: Demo Scenarios Can Import Constants Successfully
# ═══════════════════════════════════════════════════════════════════════════

def test_demo_router_imports_constants():
    """
    Test that the demo router module can import TaskType from constants.
    
    This verifies requirement 3.1: Other demo scenarios continue to process successfully.
    """
    try:
        from routers.demo import TaskType
        assert TaskType is not None, "TaskType should be imported successfully"
    except ImportError as e:
        pytest.fail(f"Failed to import TaskType in demo router: {e}")


def test_demo_scenarios_use_correct_task_types():
    """
    Test that demo scenarios use the correct TaskType enum values.
    
    This verifies requirement 3.1: Other demo scenarios continue to process successfully.
    """
    from core.constants import TaskType
    
    # Demo scenarios and their expected TaskType usage (observed baseline)
    # duplicate_payment -> DEMO_TRIGGER
    # sla_breach -> SCAN_SLA (this is the buggy one, but we test others)
    # unused_subscriptions -> SCAN_LICENSES
    # approval_queue -> DEMO_TRIGGER
    
    # Verify the TaskTypes used by non-SLA demo scenarios
    assert TaskType.DEMO_TRIGGER.value == "demo_trigger", \
        "DEMO_TRIGGER should resolve correctly for duplicate_payment and approval_queue scenarios"
    
    assert TaskType.SCAN_LICENSES.value == "scan_licenses", \
        "SCAN_LICENSES should resolve correctly for unused_subscriptions scenario"


@given(st.sampled_from([
    "duplicate_payment",
    "unused_subscriptions", 
    "approval_queue"
]))
@settings(max_examples=30)
def test_property_non_sla_demo_scenarios_import_constants(scenario_name):
    """
    Property-based test: All non-SLA demo scenarios should be able to import
    constants module successfully.
    
    This property test verifies that the fix doesn't break other demo scenarios
    that depend on the constants module.
    
    **Validates: Requirements 3.1**
    """
    # Verify constants module can be imported (prerequisite for demo scenarios)
    try:
        from core.constants import TaskType
        assert TaskType is not None
    except ImportError as e:
        pytest.fail(f"Demo scenario '{scenario_name}' cannot import constants: {e}")
    
    # Verify the TaskTypes used by these scenarios are accessible
    from core.constants import TaskType
    
    if scenario_name in ["duplicate_payment", "approval_queue"]:
        # These use DEMO_TRIGGER
        assert hasattr(TaskType, "DEMO_TRIGGER")
        assert TaskType.DEMO_TRIGGER.value == "demo_trigger"
    elif scenario_name == "unused_subscriptions":
        # This uses SCAN_LICENSES
        assert hasattr(TaskType, "SCAN_LICENSES")
        assert TaskType.SCAN_LICENSES.value == "scan_licenses"


# ═══════════════════════════════════════════════════════════════════════════
# Property 2.3: Modules Importing Constants Continue to Work
# ═══════════════════════════════════════════════════════════════════════════

def test_agents_import_constants():
    """
    Test that agent modules can import from constants successfully.
    
    This verifies requirement 3.3: Constants module imported by other modules
    (agents, routers, services) continue to import successfully.
    """
    try:
        # Test various agent imports
        from agents.base_agent import AgentName, ModelName, Severity
        from agents.anomaly_detection import TaskType, AnomalyType
        from agents.decision_agent import ActionType
        
        assert all([AgentName, ModelName, Severity, TaskType, AnomalyType, ActionType])
    except ImportError as e:
        pytest.fail(f"Failed to import constants in agents: {e}")


def test_routers_import_constants():
    """
    Test that router modules can import from constants successfully.
    
    This verifies requirement 3.3: Constants module imported by other modules
    (agents, routers, services) continue to import successfully.
    """
    try:
        # Test router imports
        from routers.demo import TaskType
        from routers.approvals import ActionState
        
        assert all([TaskType, ActionState])
    except ImportError as e:
        pytest.fail(f"Failed to import constants in routers: {e}")


def test_services_import_constants():
    """
    Test that service modules can import from constants successfully.
    
    This verifies requirement 3.3: Constants module imported by other modules
    (agents, routers, services) continue to import successfully.
    """
    try:
        # Test service imports
        from services.redis_client import TaskType, RedisQueue
        from services.approval_service import ActionState, ActionType
        from services.llm_router import ModelName, Severity
        
        assert all([TaskType, RedisQueue, ActionState, ActionType, ModelName, Severity])
    except ImportError as e:
        pytest.fail(f"Failed to import constants in services: {e}")


@given(st.sampled_from([
    "agents.base_agent",
    "agents.anomaly_detection",
    "agents.decision_agent",
    "routers.demo",
    "routers.approvals",
    "services.redis_client",
    "services.approval_service",
    "services.llm_router"
]))
@settings(max_examples=40)
def test_property_modules_import_constants_successfully(module_name):
    """
    Property-based test: All modules that import from constants should continue
    to import successfully after the fix.
    
    This property test generates test cases across different module types
    (agents, routers, services) to ensure the fix doesn't break any imports.
    
    **Validates: Requirements 3.3**
    """
    try:
        # Attempt to import the module
        import importlib
        module = importlib.import_module(module_name)
        assert module is not None, f"Module {module_name} should import successfully"
        
        # Verify constants module is accessible from this module's context
        from core.constants import TaskType
        assert TaskType is not None
        
    except ImportError as e:
        pytest.fail(f"Module '{module_name}' failed to import (may depend on constants): {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Property 2.4: Task Routing Functionality Preserved
# ═══════════════════════════════════════════════════════════════════════════

def test_tasktype_enum_is_iterable():
    """
    Test that TaskType enum can be iterated over (used in task routing logic).
    
    This verifies requirement 3.4: Existing functionality using TaskType enum
    for task routing continues to operate with same behavior.
    """
    from core.constants import TaskType
    
    # Verify enum is iterable
    members = list(TaskType)
    assert len(members) > 0, "TaskType enum should have members"
    
    # Verify all members are TaskType instances
    for member in members:
        assert isinstance(member, TaskType), f"All members should be TaskType instances"


def test_tasktype_enum_supports_value_lookup():
    """
    Test that TaskType enum supports value-based lookup (used in task routing).
    
    This verifies requirement 3.4: Existing functionality using TaskType enum
    for task routing continues to operate with same behavior.
    """
    from core.constants import TaskType
    
    # Test value-based lookup for non-SCAN_SLA members
    test_values = [
        "scan_duplicates",
        "scan_licenses",
        "reconcile",
        "scan_pricing",
        "scan_infra",
        "demo_trigger"
    ]
    
    for value in test_values:
        # Verify we can look up enum member by value
        member = TaskType(value)
        assert member.value == value, f"TaskType('{value}') should resolve correctly"


@given(st.sampled_from([
    "scan_duplicates",
    "scan_licenses",
    "reconcile",
    "scan_pricing",
    "scan_infra",
    "demo_trigger"
]))
@settings(max_examples=50)
def test_property_tasktype_value_lookup_preserved(task_value):
    """
    Property-based test: TaskType enum should support value-based lookup
    for all non-SCAN_SLA task types, preserving task routing functionality.
    
    This property test verifies that task routing logic using TaskType(value)
    continues to work correctly after the fix.
    
    **Validates: Requirements 3.4**
    """
    from core.constants import TaskType
    
    # Verify value-based lookup works
    member = TaskType(task_value)
    assert member.value == task_value, \
        f"TaskType('{task_value}') should resolve to member with value '{task_value}'"
    
    # Verify the member is in the enum
    assert member in TaskType, \
        f"TaskType('{task_value}') should be a valid TaskType enum member"
