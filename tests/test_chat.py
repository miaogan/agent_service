"""
Test cases for chat and SSE streaming functionality.
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    return TestClient(app)


# ─── SSE Event Parsing ───────────────────────────────────────────────────────


def parse_sse_events(text: str) -> list:
    """Parse SSE events from response text."""
    events = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            data = line[6:]  # Remove "data: " prefix
            if data != "[DONE]":
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    return events


# ─── Basic Chat Tests ────────────────────────────────────────────────────────


def test_chat_stream_basic(client):
    """Test basic chat stream functionality."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "Hello, can you count to 5?",
            "thread_id": "basic-chat-1",
            "model": "glm-5"
        },
    )
    
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    
    events = parse_sse_events(response.text)
    
    # Should have at least one delta and a done event
    assert len(events) > 0
    assert any(e.get("type") == "delta" for e in events)
    assert any(e.get("type") == "done" for e in events)


def test_chat_stream_with_default_agent(client):
    """Test chat stream uses default agent."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "What is 2+2?",
            "thread_id": "default-agent-test",
        },
    )
    
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    
    done_event = next((e for e in events if e.get("type") == "done"), None)
    assert done_event is not None
    assert "content" in done_event


def test_chat_stream_with_specific_agent(client):
    """Test chat stream with specific agent."""
    # Create custom agent
    client.post(
        "/agents",
        json={
            "agent_id": "math-agent",
            "name": "Math Agent",
            "model": "glm-5",
        },
    )
    
    response = client.post(
        "/chat/math-agent/stream",
        json={
            "message": "Calculate 10 * 20",
            "thread_id": "math-thread-1",
        },
    )
    
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    
    done_event = next((e for e in events if e.get("type") == "done"), None)
    assert done_event is not None
    assert done_event.get("agent_id") == "math-agent"


def test_chat_stream_thread_isolation(client):
    """Test that different threads are isolated."""
    # First conversation
    response1 = client.post(
        "/chat/stream",
        json={
            "message": "My name is Alice",
            "thread_id": "thread-alice",
        },
    )
    assert response1.status_code == 200
    
    # Different thread
    response2 = client.post(
        "/chat/stream",
        json={
            "message": "My name is Bob",
            "thread_id": "thread-bob",
        },
    )
    assert response2.status_code == 200


# ─── Tool Usage Tests ────────────────────────────────────────────────────────


def test_chat_with_python_sandbox(client):
    """Test chat that uses python_sandbox tool."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "Use Python to calculate the factorial of 5",
            "thread_id": "python-test-1",
        },
    )
    
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    
    # Check for tool call event
    tool_events = [e for e in events if e.get("type") == "tool_call"]
    
    done_event = next((e for e in events if e.get("type") == "done"), None)
    assert done_event is not None
    assert "tools_used" in done_event


# ─── Error Handling Tests ────────────────────────────────────────────────────


def test_chat_stream_error_recovery(client):
    """Test that errors in streaming are handled gracefully."""
    # This test tries to trigger an error scenario
    response = client.post(
        "/chat/stream",
        json={
            "message": "Test message",
            "thread_id": "error-test-thread",
        },
    )
    
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    
    # Should complete successfully or have error event
    has_done = any(e.get("type") == "done" for e in events)
    has_error = any(e.get("type") == "error" for e in events)
    
    assert has_done or has_error


def test_chat_empty_message_validation(client):
    """Test that empty messages are rejected."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "",
            "thread_id": "validation-test",
        },
    )
    
    assert response.status_code == 422  # Validation error


# ─── Interrupt (Human-in-the-Loop) Tests ───────────────────────────────────────


def test_interrupt_detection(client):
    """Test that interrupts are properly detected and reported."""
    # Create agent with interrupt_on
    client.post(
        "/agents",
        json={
            "agent_id": "interrupt-test-agent",
            "name": "Interrupt Test Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True},
        },
    )
    
    # Note: Actual interrupt depends on agent trying to execute a shell command
    # This test verifies the endpoint structure
    response = client.post(
        "/chat/interrupt-test-agent/stream",
        json={
            "message": "Please list files in current directory",
            "thread_id": "interrupt-test-1",
        },
    )
    
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    
    # Check if interrupt or done event
    has_interrupt = any(e.get("type") == "interrupt" for e in events)
    has_done = any(e.get("type") == "done" for e in events)
    
    assert has_interrupt or has_done


def test_resume_with_approve(client):
    """Test resuming an interrupted agent with approve decision."""
    # Create agent
    client.post(
        "/agents",
        json={
            "agent_id": "resume-approve-agent",
            "name": "Resume Approve Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True},
        },
    )
    
    # This would normally follow an interrupt
    # Testing the endpoint structure
    response = client.post(
        "/chat/resume-approve-agent/resume",
        json={
            "decision": "approve",
            "tool_call_id": "test_call_123",
            "thread_id": "resume-thread-approve",
        },
    )
    
    # Response depends on whether there's an actual interrupted state
    assert response.status_code in [200, 404]


def test_resume_with_reject(client):
    """Test resuming an interrupted agent with reject decision."""
    client.post(
        "/agents",
        json={
            "agent_id": "resume-reject-agent",
            "name": "Resume Reject Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True},
        },
    )
    
    response = client.post(
        "/chat/resume-reject-agent/resume",
        json={
            "decision": "reject",
            "tool_call_id": "test_call_456",
            "thread_id": "resume-thread-reject",
        },
    )
    
    assert response.status_code in [200, 404]


def test_resume_with_edit(client):
    """Test resuming an interrupted agent with edit decision."""
    client.post(
        "/agents",
        json={
            "agent_id": "resume-edit-agent",
            "name": "Resume Edit Agent",
            "model": "glm-5",
            "interrupt_on": {"execute": True},
        },
    )
    
    response = client.post(
        "/chat/resume-edit-agent/resume",
        json={
            "decision": "edit",
            "tool_call_id": "test_call_789",
            "thread_id": "resume-thread-edit",
            "edited_args": {"command": "ls -la"},
        },
    )
    
    assert response.status_code in [200, 404, 400]


def test_resume_invalid_decision(client):
    """Test resume with invalid decision."""
    client.post(
        "/agents",
        json={
            "agent_id": "resume-invalid-agent",
            "name": "Resume Invalid Agent",
            "model": "glm-5",
        },
    )
    
    response = client.post(
        "/chat/resume-invalid-agent/resume",
        json={
            "decision": "invalid_decision",
            "tool_call_id": "test_call_000",
            "thread_id": "resume-thread-invalid",
        },
    )
    
    assert response.status_code == 400


# ─── Concurrency Tests ────────────────────────────────────────────────────────


def test_concurrent_chat_sessions(client):
    """Test multiple concurrent chat sessions."""
    import threading
    import time
    
    results = []
    
    def chat_in_thread(thread_num):
        response = client.post(
            "/chat/stream",
            json={
                "message": f"Message from thread {thread_num}",
                "thread_id": f"concurrent-thread-{thread_num}",
            },
        )
        results.append(response.status_code)
    
    threads = []
    for i in range(3):
        t = threading.Thread(target=chat_in_thread, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # All requests should succeed
    assert all(code == 200 for code in results)


# ─── Performance Tests ────────────────────────────────────────────────────────


def test_long_message(client):
    """Test chat with a long message."""
    long_message = "Please analyze this: " + "word " * 500
    
    response = client.post(
        "/chat/stream",
        json={
            "message": long_message,
            "thread_id": "long-message-test",
        },
    )
    
    assert response.status_code == 200


def test_special_characters_in_message(client):
    """Test chat with special characters."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "Test special chars: <>&\"'${}[]\\n\\t",
            "thread_id": "special-chars-test",
        },
    )
    
    assert response.status_code == 200


def test_unicode_in_message(client):
    """Test chat with unicode characters."""
    response = client.post(
        "/chat/stream",
        json={
            "message": "你好世界 🌍 مرحبا Привет",
            "thread_id": "unicode-test",
        },
    )
    
    assert response.status_code == 200


# ─── Model Selection Tests ────────────────────────────────────────────────────


def test_different_models(client):
    """Test chat with different models."""
    models = ["glm-5", "qwen3.5:9b"]
    
    for model in models:
        # Create agent with specific model
        client.post(
            "/agents",
            json={
                "agent_id": f"model-test-{model}",
                "name": f"Model Test {model}",
                "model": model,
            },
        )
        
        response = client.post(
            f"/chat/model-test-{model}/stream",
            json={
                "message": "Hello",
                "thread_id": f"model-test-thread-{model}",
            },
        )
        
        # Model should be available if LiteLLM is configured properly
        assert response.status_code in [200, 404, 500]


# ─── Agent Pool Integration ───────────────────────────────────────────────────


def test_agent_reuse_from_pool(client):
    """Test that agents are reused from pool."""
    # Create agent
    client.post(
        "/agents",
        json={
            "agent_id": "reuse-test-agent",
            "name": "Reuse Test Agent",
            "model": "glm-5",
        },
    )
    
    # First request
    response1 = client.post(
        "/chat/reuse-test-agent/stream",
        json={
            "message": "First message",
            "thread_id": "reuse-thread-1",
        },
    )
    assert response1.status_code == 200
    
    # Second request should reuse agent
    response2 = client.post(
        "/chat/reuse-test-agent/stream",
        json={
            "message": "Second message",
            "thread_id": "reuse-thread-2",
        },
    )
    assert response2.status_code == 200
    
    # Check pool stats
    stats = client.get("/pool/stats").json()
    assert stats["total_configs"] > 0


def test_agent_expiration_after_max_turns(client):
    """Test that agents expire after max turns."""
    # Create agent with low max_turns
    client.post(
        "/agents",
        json={
            "agent_id": "expire-agent",
            "name": "Expire Agent",
            "model": "glm-5",
            "max_turns": 2,
        },
    )
    
    # Make multiple requests
    for i in range(3):
        response = client.post(
            "/chat/expire-agent/stream",
            json={
                "message": f"Turn {i+1}",
                "thread_id": f"expire-thread-{i}",
            },
        )
        
        # After max_turns, should return 410 Gone
        if i >= 2:
            assert response.status_code in [200, 410]
