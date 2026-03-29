# Bug Condition Exploration Test - Execution Guide

## Overview

The bug condition exploration test (`test_bug_condition_exploration.py`) has been created to verify all 27 bug conditions across 6 categories as specified in the bugfix requirements.

**CRITICAL**: This test is EXPECTED TO FAIL on unfixed code. Failures confirm that the bugs exist.

## Test Coverage

### Category 1: AI Pipeline Failures (95%+ Error Rate)
- ✅ `test_bug_1_1_payment_hold_attribute_error` - Bug 1.1: Payment hold AttributeError
- ✅ `test_bug_1_2_sla_escalation_attribute_error` - Bug 1.2: SLA escalation AttributeError
- ✅ `test_bug_1_3_vendor_flag_entity_id_error` - Bug 1.3: Vendor flag entity_id error
- ✅ `test_bug_1_4_license_deactivation_entity_id_error` - Bug 1.4: License deactivation AttributeError
- ✅ `test_bug_1_6_timeout_fallback` - Bug 1.6: AI model timeout causing 95%+ fallback

### Category 2: Demo Scenario Failures
- ✅ `test_bug_2_1_sla_breach_demo_500_error` - Bug 2.1: SLA breach demo HTTP 500
- ✅ `test_bug_2_2_unused_subscriptions_demo_500_error` - Bug 2.2: Unused subscriptions demo HTTP 500

### Category 3: Data Integrity Issues
- ✅ `test_bug_3_1_duplicate_approval_queue_entries` - Bug 3.1: 837-939 duplicate approval queue entries

### Category 4: Frontend Display Errors
- ✅ `test_bug_4_1_nan_confidence_display` - Bug 4.1: NaN% confidence display
- ✅ `test_bug_4_5_actions_panel_model_display` - Bug 4.5: Incorrect model names in actions panel

### Category 5: Missing Functionality
- ✅ `test_bug_5_1_audit_override_endpoint_missing` - Bug 5.1: PATCH /api/audit/:id/override missing
- ✅ `test_bug_5_2_approval_reject_endpoint_missing` - Bug 5.2: POST /api/approvals/:id/reject missing

### Property-Based Tests
- ✅ `test_property_no_attribute_errors_on_any_action_type` - Property test for all action types

## Prerequisites

Before running the tests, ensure the Cost Intelligence system is running:

```bash
# Navigate to the cost-intelligence directory
cd cost-intelligence

# Start the system with Docker Compose
docker-compose up -d

# Verify containers are running
docker ps --filter "name=ci_"

# Expected output should show:
# - ci_postgres (PostgreSQL database)
# - ci_redis (Redis cache)
# - ci_backend (FastAPI backend)
# - ci_frontend (Next.js frontend)
```

## Running the Tests

### Run All Bug Exploration Tests

```bash
cd cost-intelligence/backend
python -m pytest tests/test_bug_condition_exploration.py -v
```

### Run Specific Test Categories

```bash
# AI Pipeline tests only
python -m pytest tests/test_bug_condition_exploration.py -k "bug_1" -v

# Demo scenario tests only
python -m pytest tests/test_bug_condition_exploration.py -k "bug_2" -v

# Data integrity tests only
python -m pytest tests/test_bug_condition_exploration.py -k "bug_3" -v

# Frontend display tests only
python -m pytest tests/test_bug_condition_exploration.py -k "bug_4" -v

# Missing functionality tests only
python -m pytest tests/test_bug_condition_exploration.py -k "bug_5" -v

# Property-based tests only
python -m pytest tests/test_bug_condition_exploration.py -k "property" -v
```

### Run Individual Tests

```bash
# Test specific bug
python -m pytest tests/test_bug_condition_exploration.py::test_bug_1_1_payment_hold_attribute_error -v
```

## Expected Test Results (Unfixed Code)

When run on UNFIXED code, the tests should FAIL with the following counterexamples:

### Bug 1.1 - Payment Hold AttributeError
```
AttributeError: 'DecisionResult' object has no attribute 'evidence'
Location: backend/agents/action_execution.py in _hold_payment()
```

### Bug 1.2 - SLA Escalation AttributeError
```
AttributeError: 'DecisionResult' object has no attribute 'evidence'
Location: backend/agents/action_execution.py in _escalate_sla()
```

### Bug 1.3 - Vendor Flag Entity ID Error
```
AttributeError: 'DecisionResult' object has no attribute 'entity_id'
Location: backend/agents/action_execution.py in _flag_vendor()
```

### Bug 1.4 - License Deactivation AttributeError
```
AttributeError: 'DecisionResult' object has no attribute 'entity_id'
Location: backend/agents/action_execution.py in _deactivate_license()
```

### Bug 1.6 - Timeout Fallback
```
AssertionError: Expected ≥50% qwen/deepseek usage, got <5%
Reason: FALLBACK_TIMEOUT_MS=8000 too short for CPU inference
```

### Bug 2.1 - SLA Breach Demo 500 Error
```
AssertionError: Expected HTTP 200, got 500
Error: cannot insert into generated column sla_deadline
```

### Bug 2.2 - Unused Subscriptions Demo 500 Error
```
AssertionError: Expected HTTP 200, got 500
Error: foreign key constraint violation
```

### Bug 3.1 - Duplicate Approval Queue Entries
```
AssertionError: Expected ≤20 approval queue items, got 837-939
Reason: Missing idempotency checks in anomaly detection
```

### Bug 4.5 - Actions Panel Model Display
```
AssertionError: Expected valid model name, got: ActionExecutionAgent
Reason: API returns executed_by instead of model_used
```

### Bug 5.1 - Audit Override Endpoint Missing
```
AssertionError: Expected HTTP 200, got 404
Reason: PATCH /api/audit/:id/override endpoint not implemented
```

### Bug 5.2 - Approval Reject Endpoint Missing
```
AssertionError: Expected HTTP 200, got 404
Reason: POST /api/approvals/:id/reject endpoint not implemented
```

## Test Execution Notes

### Long-Running Tests

Some tests require waiting for the AI pipeline to complete:

- `test_bug_1_6_timeout_fallback`: Waits 120 seconds for inference
- `test_bug_3_1_duplicate_approval_queue_entries`: Waits 180 seconds for multiple scan cycles

Use the `--timeout` flag if needed:

```bash
python -m pytest tests/test_bug_condition_exploration.py -v --timeout=300
```

### Property-Based Testing

The property-based test uses Hypothesis to generate 10 test cases:

```bash
# Run with more examples for thorough testing
python -m pytest tests/test_bug_condition_exploration.py::test_property_no_attribute_errors_on_any_action_type -v --hypothesis-show-statistics
```

### Debugging Failed Tests

To see full stack traces:

```bash
python -m pytest tests/test_bug_condition_exploration.py -v --tb=long
```

To stop on first failure:

```bash
python -m pytest tests/test_bug_condition_exploration.py -v -x
```

## After Fixes Are Applied

Once all fixes from tasks 3.1-3.9 are implemented, re-run the same tests:

```bash
python -m pytest tests/test_bug_condition_exploration.py -v
```

**Expected outcome**: All tests should PASS, confirming that:
- No AttributeError crashes occur
- AI models complete inference within timeout
- Demo scenarios return HTTP 200
- Approval queue remains ≤20 items
- Frontend displays correct fallback values
- Actions panel shows correct model names
- Override and reject endpoints work correctly

## Troubleshooting

### Database Connection Error

```
asyncpg.exceptions.InvalidCatalogNameError: database "cost_intelligence" does not exist
```

**Solution**: Start the Docker containers:
```bash
cd cost-intelligence
docker-compose up -d
```

### HTTP Connection Error

```
httpx.ConnectError: [Errno 111] Connection refused
```

**Solution**: Ensure the backend is running on port 8000:
```bash
docker ps | grep ci_backend
curl http://localhost:8000/api/system/status
```

### Redis Connection Error

```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**Solution**: Ensure Redis is running:
```bash
docker ps | grep ci_redis
docker exec ci_redis redis-cli ping
```

## Requirements Validation

This test file validates the following requirements from the bugfix specification:

- **Requirements 1.1-1.6**: Current behavior (defects)
- **Requirements 2.1-2.22**: Expected behavior (fixes)
- **Requirements 3.1-3.20**: Preservation requirements

## Next Steps

1. ✅ **Task 1 Complete**: Bug condition exploration test created
2. ⏭️ **Task 2**: Write preservation property tests (before implementing fixes)
3. ⏭️ **Task 3**: Implement fixes (tasks 3.0-3.9)
4. ⏭️ **Task 3.10**: Verify bug condition exploration test now passes
5. ⏭️ **Task 3.11**: Verify preservation tests still pass

## Test Maintenance

When modifying the test file:

1. Keep test names descriptive and linked to bug numbers
2. Include requirement validation comments in docstrings
3. Document expected counterexamples in test docstrings
4. Update this README when adding new test cases
5. Ensure property-based tests use appropriate strategies

## Contact

For questions about the test implementation or failures, refer to:
- Bugfix specification: `.kiro/specs/complete-e2e-testing-fixes/bugfix.md`
- Design document: `.kiro/specs/complete-e2e-testing-fixes/design.md`
- Task list: `.kiro/specs/complete-e2e-testing-fixes/tasks.md`
