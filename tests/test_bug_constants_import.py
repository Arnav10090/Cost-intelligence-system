"""
Bug Condition Exploration Test for SLA Scenario API Error Fix

**Validates: Requirements 2.1, 2.2, 2.3**

This test explores the bug condition where duplicate SCAN_SLA enum member
causes import failures in the constants module.

CRITICAL: This test is EXPECTED TO FAIL on unfixed code - failure confirms
the bug exists. When it passes after the fix, it validates the expected behavior.

Property 1: Bug Condition - Constants Module Import Success
For any code path that imports the TaskType enum from core.constants,
the fixed module SHALL import successfully without raising exceptions, and TaskType.SCAN_SLA
SHALL resolve to a single, valid enum value "scan_sla".
"""

import pytest
from hypothesis import given, strategies as st


def test_constants_module_import_succeeds():
    """
    Test that importing TaskType from constants module succeeds without exceptions.
    
    This test will FAIL on unfixed code due to duplicate SCAN_SLA enum member.
    Expected counterexample: TypeError: Attempted to reuse key: 'SCAN_SLA'
    """
    try:
        from core.constants import TaskType
        # If we reach here, import succeeded
        assert True, "Constants module imported successfully"
    except Exception as e:
        pytest.fail(f"Failed to import constants module: {type(e).__name__}: {e}")


def test_scan_sla_resolves_to_single_value():
    """
    Test that TaskType.SCAN_SLA resolves to a single, valid enum value "scan_sla".
    
    This test will FAIL on unfixed code if the duplicate causes undefined behavior.
    """
    from core.constants import TaskType
    
    # Verify SCAN_SLA exists and has the correct value
    assert hasattr(TaskType, "SCAN_SLA"), "TaskType.SCAN_SLA should exist"
    assert TaskType.SCAN_SLA.value == "scan_sla", "TaskType.SCAN_SLA should resolve to 'scan_sla'"


def test_tasktype_enum_has_exactly_7_members():
    """
    Test that TaskType enum has exactly 7 unique members after fix.
    
    This test will FAIL on unfixed code if duplicate members exist.
    Expected members: SCAN_DUPLICATES, SCAN_SLA, SCAN_LICENSES, RECONCILE,
                     SCAN_PRICING, SCAN_INFRA, DEMO_TRIGGER
    """
    from core.constants import TaskType
    
    # Get all enum members
    members = list(TaskType)
    member_names = [m.name for m in members]
    
    # Verify exactly 7 unique members
    assert len(members) == 7, f"Expected 7 members, got {len(members)}: {member_names}"
    
    # Verify all expected members exist
    expected_members = {
        "SCAN_DUPLICATES", "SCAN_SLA", "SCAN_LICENSES", 
        "RECONCILE", "SCAN_PRICING", "SCAN_INFRA", "DEMO_TRIGGER"
    }
    actual_members = set(member_names)
    assert actual_members == expected_members, f"Member mismatch. Expected: {expected_members}, Got: {actual_members}"


@given(st.sampled_from([
    "SCAN_DUPLICATES", "SCAN_SLA", "SCAN_LICENSES", 
    "RECONCILE", "SCAN_PRICING", "SCAN_INFRA", "DEMO_TRIGGER"
]))
def test_property_all_tasktype_members_accessible(member_name: str):
    """
    Property-based test: All TaskType enum members should be accessible by name.
    
    This property test generates test cases for all enum members to ensure
    they can be accessed without errors after the fix.
    """
    from core.constants import TaskType
    
    # Verify member exists and is accessible
    assert hasattr(TaskType, member_name), f"TaskType.{member_name} should be accessible"
    member = getattr(TaskType, member_name)
    
    # Verify it's a valid enum member with a string value
    assert isinstance(member.value, str), f"TaskType.{member_name} should have a string value"
    assert len(member.value) > 0, f"TaskType.{member_name} value should not be empty"
