import pytest
import uuid
import datetime
from pydantic import ValidationError

from local_server.communication.protocol_models import (
    BaseMessage,
    ExecuteOwlTaskDetails, QueryLocalModelDirectDetails, GetLocalStatusDetails,
    RemoteCommandToLocalPayload,
    LocalResponseToRemotePayload,
    ConfidenceAssessmentData, LocalRequestCloudRefinementPayload,
    CloudRefinementResponseToLocalPayload, CloudRefinementDiagnostics,
    LocalConfidentResultNotificationPayload,
    HeartbeatPayload
)

# --- Test BaseMessage ---
def test_base_message_creation_default_ids():
    payload_data = {"key": "value"}
    msg = BaseMessage(message_type="test_type", payload=payload_data)
    assert isinstance(uuid.UUID(msg.task_id), uuid.UUID) # Check if valid UUID
    assert "Z" in msg.timestamp # Check if UTC timezone indicator is present
    assert msg.message_type == "test_type"
    assert msg.payload == payload_data

def test_base_message_creation_custom_ids():
    custom_task_id = "my_custom_task_123"
    custom_timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    payload_data = {"info": "detail"}
    msg = BaseMessage(task_id=custom_task_id, message_type="custom_type", timestamp=custom_timestamp, payload=payload_data)
    assert msg.task_id == custom_task_id
    assert msg.timestamp == custom_timestamp
    assert msg.message_type == "custom_type"
    assert msg.payload == payload_data

def test_base_message_missing_required_fields():
    with pytest.raises(ValidationError):
        BaseMessage(payload={"key": "value"}) # Missing message_type
    with pytest.raises(ValidationError):
        BaseMessage(message_type="test") # Missing payload

# --- Test Payload Definitions ---

# 3.1.1. remote_command_to_local
def test_execute_owl_task_details():
    details = ExecuteOwlTaskDetails(agent_task_description="Do something complex")
    assert details.agent_task_description == "Do something complex"
    assert details.owl_agent_config is None
    details_with_config = ExecuteOwlTaskDetails(agent_task_description="Task", owl_agent_config={"param": 1})
    assert details_with_config.owl_agent_config == {"param": 1}

def test_query_local_model_direct_details():
    details = QueryLocalModelDirectDetails(prompt="What is AI?")
    assert details.prompt == "What is AI?"
    assert details.vllm_params == {"max_tokens": 256, "temperature": 0.7} # Default
    details_custom_params = QueryLocalModelDirectDetails(prompt="Q", vllm_params={"max_tokens": 10})
    assert details_custom_params.vllm_params == {"max_tokens": 10}

def test_get_local_status_details():
    details = GetLocalStatusDetails() # No fields
    assert isinstance(details, GetLocalStatusDetails)

def test_remote_command_to_local_payload():
    # Test with ExecuteOwlTaskDetails
    owl_details = ExecuteOwlTaskDetails(agent_task_description="Run Owl")
    payload = RemoteCommandToLocalPayload(command_action="execute_owl_task", command_details=owl_details.model_dump())
    assert payload.command_action == "execute_owl_task"
    assert payload.command_details == owl_details.model_dump()

    # Test with GetLocalStatusDetails (no command_details needed in payload model, but can be empty dict)
    payload_status = RemoteCommandToLocalPayload(command_action="get_local_status")
    assert payload_status.command_action == "get_local_status"
    assert payload_status.command_details is None # Or {} depending on how it's used

    # Test validation for command_action
    with pytest.raises(ValidationError):
        RemoteCommandToLocalPayload(command_action="invalid_action", command_details={})

# 3.1.2. local_response_to_remote
def test_local_response_to_remote_payload():
    payload_success = LocalResponseToRemotePayload(original_command_action="execute_owl_task", status="success", data={"result": "done"})
    assert payload_success.status == "success"
    assert payload_success.data == {"result": "done"}

    payload_error = LocalResponseToRemotePayload(original_command_action="query_local_model_direct", status="error", error_message="Model unavailable")
    assert payload_error.status == "error"
    assert payload_error.error_message == "Model unavailable"
    assert payload_error.data is None

    with pytest.raises(ValidationError):
        LocalResponseToRemotePayload(original_command_action="test", status="invalid_status")

# 3.1.3. local_request_cloud_refinement
def test_confidence_assessment_data():
    data = ConfidenceAssessmentData(rouge_l_score=0.5, keyword_triggers_found=["urgent"], requires_cloud_refinement=True)
    assert data.rouge_l_score == 0.5
    assert data.requires_cloud_refinement is True

def test_local_request_cloud_refinement_payload():
    conf_data = ConfidenceAssessmentData(requires_cloud_refinement=True, details={"reason": "low score"})
    payload = LocalRequestCloudRefinementPayload(
        original_user_prompt="Tell me a story",
        local_model_draft_result="Once upon a time...",
        confidence_assessment=conf_data
    )
    assert payload.local_model_draft_result == "Once upon a time..."
    assert payload.confidence_assessment.requires_cloud_refinement is True
    assert payload.confidence_assessment.details == {"reason": "low score"}

# 3.1.4. cloud_refinement_response_to_local
def test_cloud_refinement_diagnostics():
    diag = CloudRefinementDiagnostics(cloud_processing_time_ms=1200)
    assert diag.cloud_processing_time_ms == 1200

def test_cloud_refinement_response_to_local_payload():
    payload_success = CloudRefinementResponseToLocalPayload(status="success", refined_result="A better story...")
    assert payload_success.status == "success"
    assert payload_success.refined_result == "A better story..."

    payload_error = CloudRefinementResponseToLocalPayload(status="error", error_message="Cloud model failed")
    assert payload_error.status == "error"
    assert payload_error.error_message == "Cloud model failed"

# 3.1.5. local_confident_result_notification
def test_local_confident_result_notification_payload():
    conf_data = ConfidenceAssessmentData(rouge_l_score=0.8, requires_cloud_refinement=False)
    payload = LocalConfidentResultNotificationPayload(
        original_user_prompt="What is 2+2?",
        local_model_final_result="2+2 is 4.",
        confidence_assessment=conf_data,
        local_processing_time_ms=50
    )
    assert payload.local_model_final_result == "2+2 is 4."
    assert payload.confidence_assessment.requires_cloud_refinement is False
    assert payload.local_processing_time_ms == 50

# Heartbeat Message
def test_heartbeat_payload():
    payload = HeartbeatPayload(local_server_id="server_001", status="ok", gpu_usage_percent=75.5)
    assert payload.local_server_id == "server_001"
    assert payload.status == "ok"
    assert payload.gpu_usage_percent == 75.5
    assert payload.active_tasks_count is None

    payload_warning = HeartbeatPayload(local_server_id="s2", status="warning", active_tasks_count=10)
    assert payload_warning.status == "warning"
    assert payload_warning.active_tasks_count == 10

    with pytest.raises(ValidationError):
        HeartbeatPayload(local_server_id="s3", status="invalid_hb_status")

# Test serialization/deserialization (model_dump_json and model_validate_json)
def test_base_message_serialization():
    payload_data = {"key": "value"}
    msg = BaseMessage(message_type="test_type", payload=payload_data)
    json_str = msg.model_dump_json()
    
    # Reconstruct from JSON string
    # For Pydantic v2, it's model_validate_json
    new_msg = BaseMessage.model_validate_json(json_str)
    
    assert new_msg.task_id == msg.task_id
    assert new_msg.timestamp == msg.timestamp
    assert new_msg.message_type == msg.message_type
    assert new_msg.payload == msg.payload

def test_nested_payload_serialization():
    owl_details = ExecuteOwlTaskDetails(agent_task_description="Run Owl Test")
    cmd_payload = RemoteCommandToLocalPayload(command_action="execute_owl_task", command_details=owl_details.model_dump())
    base_msg = BaseMessage(message_type="remote_command_to_local", payload=cmd_payload.model_dump())

    json_str = base_msg.model_dump_json()
    reconstructed_base_msg = BaseMessage.model_validate_json(json_str)

    assert reconstructed_base_msg.message_type == "remote_command_to_local"
    reconstructed_cmd_payload = RemoteCommandToLocalPayload(**reconstructed_base_msg.payload)
    assert reconstructed_cmd_payload.command_action == "execute_owl_task"
    reconstructed_owl_details = ExecuteOwlTaskDetails(**reconstructed_cmd_payload.command_details)
    assert reconstructed_owl_details.agent_task_description == "Run Owl Test"

