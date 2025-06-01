from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, Literal, List
import datetime
import uuid

# --- Base Message Structure ---
class BaseMessage(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message_type: str
    timestamp: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    payload: Dict[str, Any]

# --- Payload Definitions for Specific Message Types ---

# 3.1.1. remote_command_to_local
class ExecuteOwlTaskDetails(BaseModel):
    agent_task_description: str
    owl_agent_config: Optional[Dict[str, Any]] = None

class QueryLocalModelDirectDetails(BaseModel):
    prompt: str
    vllm_params: Optional[Dict[str, Any]] = {"max_tokens": 256, "temperature": 0.7}

class GetLocalStatusDetails(BaseModel):
    pass # No specific details needed

class RemoteCommandPayloadDetails(BaseModel):
    command_action: Literal["execute_owl_task", "query_local_model_direct", "get_local_status"]
    command_details: Dict[str, Any] # This will be one of the above detail models when parsed

class RemoteCommandToLocalPayload(BaseModel):
    # This structure is slightly different from the plan to make parsing command_details easier
    # The plan had command_action and command_details at the same level as payload.
    # Here, they are inside the payload for consistency with BaseMessage.
    # The actual `payload` in BaseMessage will be this model.
    command_action: Literal["execute_owl_task", "query_local_model_direct", "get_local_status"]
    command_details: Optional[Dict[str, Any]] = None # Specific to command_action

# 3.1.2. local_response_to_remote
class LocalResponseToRemotePayload(BaseModel):
    original_command_action: str
    status: Literal["success", "error", "processing_async"]
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

# 3.1.3. local_request_cloud_refinement
class ConfidenceAssessmentData(BaseModel):
    rouge_l_score: Optional[float] = None
    keyword_triggers_found: Optional[List[str]] = []
    requires_cloud_refinement: bool # This field is crucial
    # Potentially add more details from ConfidenceResult.details
    details: Optional[Dict[str, Any]] = None 

class LocalRequestCloudRefinementPayload(BaseModel):
    original_user_prompt: str
    local_model_draft_result: str
    confidence_assessment: ConfidenceAssessmentData 
    refinement_hints: Optional[Dict[str, Any]] = None

# 3.1.4. cloud_refinement_response_to_local
class CloudRefinementDiagnostics(BaseModel):
    cloud_processing_time_ms: Optional[int] = None
    reason_for_error_or_partial: Optional[str] = None

class CloudRefinementResponseToLocalPayload(BaseModel):
    status: Literal["success", "error", "partial_success"]
    refined_result: Optional[str] = None
    original_local_draft_preserved: Optional[str] = None # If cloud chooses to keep parts
    cloud_tokens_consumed: Optional[int] = None
    error_message: Optional[str] = None
    diagnostics: Optional[CloudRefinementDiagnostics] = None

# 3.1.5. local_confident_result_notification
class LocalConfidentResultNotificationPayload(BaseModel):
    original_user_prompt: str
    local_model_final_result: str
    confidence_assessment: ConfidenceAssessmentData # Re-use the assessment data model
    local_processing_time_ms: Optional[int] = None

# Heartbeat Message (from heartbeat_protocol_plan_v1_zh.md)
class HeartbeatPayload(BaseModel):
    local_server_id: str
    status: Literal["ok", "warning", "error"] = "ok"
    # Optional: add more metrics like GPU usage, active tasks, etc.
    gpu_usage_percent: Optional[float] = None
    active_tasks_count: Optional[int] = None
    model_name: Optional[str] = None
    vllm_health_status: Optional[bool] = None

# --- Helper for creating typed messages ---
# This is more of a conceptual helper, actual usage will involve constructing BaseMessage
# with the correct payload model instance (usually after .model_dump() if nested).

# Example of how to use:
# cmd_payload = RemoteCommandToLocalPayload(command_action="get_local_status")
# msg = BaseMessage(message_type="remote_command_to_local", payload=cmd_payload.model_dump())

# When receiving, you'd parse to BaseMessage, then based on message_type, parse payload dict to specific model:
# base_msg = BaseMessage(**incoming_dict)
# if base_msg.message_type == "remote_command_to_local":
#     cmd_payload = RemoteCommandToLocalPayload(**base_msg.payload)
#     if cmd_payload.command_action == "get_local_status":
#         details = GetLocalStatusDetails() # No details to parse for this one
#     elif cmd_payload.command_action == "query_local_model_direct":
#         details = QueryLocalModelDirectDetails(**cmd_payload.command_details)

