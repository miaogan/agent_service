# Test Documentation

## Overview

This project includes comprehensive test coverage for all major components:

- **API Tests** (`test_api.py`) - HTTP endpoint testing
- **Agent Pool Tests** (`test_agent_pool.py`) - Agent lifecycle and pool management
- **Storage Tests** (`test_storage.py`) - Configuration persistence
- **Chat Tests** (`test_chat.py`) - SSE streaming and chat functionality

## Running Tests

### Prerequisites

Ensure dev dependencies are installed:

```bash
uv sync
```

### Run All Tests

**Windows:**
```bash
run_tests.bat
```

**Linux/Mac:**
```bash
chmod +x run_tests.sh
./run_tests.sh
```

### Run Specific Test Files

```bash
# API tests
uv run pytest tests/test_api.py -v

# Agent pool tests
uv run pytest tests/test_agent_pool.py -v

# Storage tests
uv run pytest tests/test_storage.py -v

# Chat tests
uv run pytest tests/test_chat.py -v
```

### Run Specific Tests

```bash
# Run specific test function
uv run pytest tests/test_api.py::test_health_check -v

# Run tests matching pattern
uv run pytest tests/test_api.py -k "agent" -v
```

### Coverage Report

```bash
uv run pytest tests/ --cov=app --cov-report=html
```

## Test Categories

### 1. Health & Monitoring Tests

- `test_health_check` - Health endpoint returns correct status
- `test_list_models` - Models endpoint lists available models
- `test_pool_stats` - Pool statistics endpoint

### 2. Agent CRUD Tests

**Create:**
- `test_create_agent_config` - Basic agent creation
- `test_create_duplicate_agent` - Duplicate ID validation
- `test_create_agent_with_interrupt_on` - Human-in-the-loop config
- `test_create_agent_with_mcp_servers` - MCP server configuration

**Read:**
- `test_list_agents` - List all agents
- `test_get_agent` - Get specific agent
- `test_get_nonexistent_agent` - 404 handling
- `test_default_agent_exists` - Default agent auto-creation

**Update:**
- `test_update_agent` - Update agent name
- `test_update_agent_interrupt_on` - Update interrupt config
- `test_update_agent_model` - Update model
- `test_update_nonexistent_agent` - 404 handling

**Delete:**
- `test_delete_agent` - Delete agent
- `test_delete_nonexistent_agent` - 404 handling

### 3. Chat Tests

**Basic Chat:**
- `test_chat_stream_basic` - Basic SSE streaming
- `test_chat_stream_with_default_agent` - Default agent usage
- `test_chat_stream_with_specific_agent` - Specific agent selection
- `test_chat_stream_thread_isolation` - Thread isolation

**Tool Usage:**
- `test_chat_with_python_sandbox` - Python execution tool

**Error Handling:**
- `test_chat_stream_error_recovery` - Error handling in streams
- `test_chat_empty_message_validation` - Input validation

### 4. Human-in-the-Loop Tests

- `test_interrupt_detection` - Interrupt event detection
- `test_resume_with_approve` - Approve interrupted action
- `test_resume_with_reject` - Reject interrupted action
- `test_resume_with_edit` - Edit and approve action
- `test_resume_invalid_decision` - Decision validation

### 5. Agent Pool Tests

- `test_pool_start_stop` - Pool lifecycle
- `test_register_config` - Configuration registration
- `test_get_agent_creates_instance` - Lazy instantiation
- `test_get_agent_reuses_instance` - Agent reuse
- `test_increment_turn` - Turn counter
- `test_max_turns_exceeded` - Turn limit enforcement
- `test_remove_agent` - Agent removal
- `test_pool_stats` - Statistics

### 6. Storage Tests

- `test_save_config` - Save configuration
- `test_load_nonexistent_config` - Null handling
- `test_load_all_configs` - Load all
- `test_delete_config` - Delete configuration
- `test_update_config` - Update configuration

### 7. Integration Tests

- `test_full_agent_lifecycle` - Complete CRUD cycle
- `test_multiple_agents_isolation` - Agent isolation
- `test_pool_stats_updates` - Stats reflect changes
- `test_agent_reuse_from_pool` - Pool reuse
- `test_agent_expiration_after_max_turns` - TTL enforcement

### 8. Concurrency & Performance Tests

- `test_concurrent_chat_sessions` - Concurrent requests
- `test_long_message` - Long message handling
- `test_special_characters_in_message` - Special chars
- `test_unicode_in_message` - Unicode support

## Test Fixtures

### Common Fixtures

```python
@pytest.fixture
def client():
    """FastAPI test client"""
    app = create_app()
    return TestClient(app)

@pytest.fixture
def sample_config():
    """Sample agent configuration"""
    return AgentConfig(
        agent_id="test-agent-1",
        name="Test Agent",
        model="glm-5",
    )

@pytest.fixture
def mock_agent_factory():
    """Mock agent factory for pool tests"""
    return AsyncMock(return_value=MagicMock())
```

## Testing Best Practices

### 1. Test Independence
Each test should be independent and not rely on state from other tests.

### 2. Descriptive Names
Test names should describe the scenario being tested.

### 3. Arrange-Act-Assert
Structure tests clearly:
```python
def test_example():
    # Arrange
    agent_id = "test-agent"
    
    # Act
    response = client.get(f"/agents/{agent_id}")
    
    # Assert
    assert response.status_code == 200
```

### 4. Test Edge Cases
Include tests for:
- Empty inputs
- Invalid inputs
- Boundary conditions
- Error scenarios

### 5. SSE Testing
For Server-Sent Events:
```python
def parse_sse_events(text: str) -> list:
    """Parse SSE events from response"""
    events = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            data = line[6:]
            if data != "[DONE]":
                events.append(json.loads(data))
    return events
```

## Known Issues

### Type Errors in LSP
Some type errors shown by LSP are false positives:
- `Import "pytest" could not be resolved` - pytest is in dev dependencies
- Type mismatches in `agent_service.py` - Due to strict typing, doesn't affect runtime

### Service Restart Required
After code changes, restart the service to apply fixes:
```bash
# Stop current service (Ctrl+C)
# Restart
uv run python -m app.main
```

## Continuous Integration

For CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    uv sync
    uv run pytest tests/ -v --junitxml=test-results.xml
```

## Test Coverage Goals

- **API Endpoints**: 100%
- **Agent Pool**: 90%+
- **Storage**: 90%+
- **Chat/SSE**: 80%+

## Debugging Failed Tests

1. **Check service is running**: Tests require LiteLLM and MCP server
2. **Check environment**: Verify `.env` configuration
3. **Check logs**: Review test output for errors
4. **Isolate test**: Run single test with `-v` flag
5. **Check dependencies**: Run `uv sync` to ensure packages installed

## Test Data Cleanup

Tests create temporary agents. To clean up:

```bash
# Remove test data
rm -f data/agent_configs.json

# Restart service to recreate default agent
uv run python -m app.main
```
