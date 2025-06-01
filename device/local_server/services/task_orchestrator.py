import asyncio
import uuid
import logging
import time
from typing import Dict, Any, Optional, List, Tuple

from ..core.config import settings
from .vllm_service import VLLMService, VLLMServiceError
from .confidence_service import ConfidenceService, ConfidenceResult
from .owl_agent_service import OwlAgentService, OwlAgentServiceError
from ..communication.tcp_client import TCPRemoteClient, TCPClientError, TCPClientTimeoutError, TCPClientConnectionError
from ..communication.protocol_models import (
    BaseMessage,
    RemoteCommandToLocalPayload, ExecuteOwlTaskDetails, QueryLocalModelDirectDetails, GetLocalStatusDetails,
    LocalResponseToRemotePayload,
    LocalRequestCloudRefinementPayload, CloudRefinementResponseToLocalPayload, ConfidenceAssessmentData,
    LocalConfidentResultNotificationPayload
)

logger = logging.getLogger(__name__)

class TaskOrchestratorError(Exception):
    """Custom exception for Task Orchestrator errors."""
    pass

class TaskOrchestrator:
    def __init__(self,
                 vllm_service: VLLMService,
                 confidence_service: ConfidenceService,
                 owl_agent_service: OwlAgentService,
                 tcp_remote_client: TCPRemoteClient):
        self.vllm_service = vllm_service
        self.confidence_service = confidence_service
        self.owl_agent_service = owl_agent_service
        self.tcp_client = tcp_remote_client
        self._active_tasks_count = 0 # Simple counter for active tasks
        logger.info("TaskOrchestrator initialized.")

    async def get_active_tasks_count(self) -> int:
        return self._active_tasks_count

    async def _increment_active_tasks(self):
        self._active_tasks_count += 1

    async def _decrement_active_tasks(self):
        self._active_tasks_count = max(0, self._active_tasks_count - 1)

    async def process_user_request_full_flow(self, user_prompt: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Handles a user prompt through the full local processing and potential cloud refinement flow.
        This is the primary entry point for user-initiated tasks that require LLM generation.
        Returns a dictionary suitable for an API response to the end-user (e.g., desktop app).
        """
        await self._increment_active_tasks()
        task_start_time = time.monotonic()
        request_id = request_id or str(uuid.uuid4())
        logger.info(f"TaskOrchestrator (Request ID: {request_id}): Starting full flow for prompt: \nRPT.Slice.Start------------------------------------------------------\n{user_prompt[:100]}...\nRPT.Slice.End--------------------------------------------------------\n")

        final_result: Optional[str] = None
        source: str = "unknown"
        error_message: Optional[str] = None
        details: Dict[str, Any] = {"request_id": request_id, "stages": []}

        try:
            # 1. Local LLM Generation
            logger.debug(f"TaskOrchestrator (Request ID: {request_id}): Requesting local LLM generation.")
            local_llm_start_time = time.monotonic()
            try:
                # TODO: Add vLLM params if needed from user request context
                vllm_response = await self.vllm_service.generate_response(prompt=user_prompt)
                local_generated_text = vllm_response.get("choices", [{}])[0].get("message", {}).get("content")
                if not local_generated_text:
                    raise TaskOrchestratorError("Local LLM returned empty content.")
                details["stages"].append({
                    "name": "local_llm_generation", 
                    "status": "success", 
                    "duration_ms": int((time.monotonic() - local_llm_start_time) * 1000),
                    "output_preview": local_generated_text[:100] + "..."
                })
                logger.info(f"TaskOrchestrator (Request ID: {request_id}): Local LLM generation successful.")
            except VLLMServiceError as e:
                logger.error(f"TaskOrchestrator (Request ID: {request_id}): Local LLM generation failed: {e}")
                details["stages"].append({"name": "local_llm_generation", "status": "error", "error": str(e), "duration_ms": int((time.monotonic() - local_llm_start_time) * 1000)})
                raise TaskOrchestratorError(f"Local LLM generation failed: {e}") from e

            # 2. Confidence Assessment
            logger.debug(f"TaskOrchestrator (Request ID: {request_id}): Assessing confidence of local result.")
            confidence_start_time = time.monotonic()
            confidence_assessment_result: ConfidenceResult = await self.confidence_service.assess(
                generated_text=local_generated_text,
                original_prompt=user_prompt
            )
            details["stages"].append({
                "name": "confidence_assessment", 
                "status": "success", 
                "duration_ms": int((time.monotonic() - confidence_start_time) * 1000),
                "assessment": confidence_assessment_result.to_dict()
            })
            logger.info(f"TaskOrchestrator (Request ID: {request_id}): Confidence assessment complete. Needs refinement: {confidence_assessment_result.needs_refinement}")

            # 3. Decision: Use local result or request cloud refinement
            if not confidence_assessment_result.needs_refinement:
                final_result = local_generated_text
                source = "local_high_confidence"
                logger.info(f"TaskOrchestrator (Request ID: {request_id}): High confidence. Using local result.")
                # Notify remote server about confident local result (fire and forget)
                notification_payload = LocalConfidentResultNotificationPayload(
                    original_user_prompt=user_prompt,
                    local_model_final_result=final_result,
                    confidence_assessment=ConfidenceAssessmentData(**confidence_assessment_result.to_dict()), # Map fields
                    local_processing_time_ms=int((time.monotonic() - task_start_time) * 1000)
                )
                asyncio.create_task(self.tcp_client.send_confident_result_notification(notification_payload))
            else:
                logger.info(f"TaskOrchestrator (Request ID: {request_id}): Low confidence. Requesting cloud refinement.")
                cloud_refinement_start_time = time.monotonic()
                refinement_request_payload = LocalRequestCloudRefinementPayload(
                    original_user_prompt=user_prompt,
                    local_model_draft_result=local_generated_text,
                    confidence_assessment=ConfidenceAssessmentData(**confidence_assessment_result.to_dict()),
                    # refinement_hints: Optional - can be added if we have specific hints
                )
                try:
                    cloud_response: Optional[CloudRefinementResponseToLocalPayload] = await self.tcp_client.request_cloud_refinement(refinement_request_payload)
                    cloud_stage_details = {
                        "name": "cloud_refinement",
                        "duration_ms": int((time.monotonic() - cloud_refinement_start_time) * 1000)
                    }
                    if cloud_response and cloud_response.status == "success" and cloud_response.refined_result:
                        final_result = cloud_response.refined_result
                        source = "cloud_refined_success"
                        cloud_stage_details["status"] = "success"
                        cloud_stage_details["cloud_tokens_consumed"] = cloud_response.cloud_tokens_consumed
                        logger.info(f"TaskOrchestrator (Request ID: {request_id}): Cloud refinement successful.")
                    else:
                        # Cloud refinement failed, timed out, or returned error/no result
                        final_result = local_generated_text # Fallback to local result
                        source = "local_fallback_cloud_failure"
                        cloud_stage_details["status"] = "failure_or_fallback"
                        cloud_stage_details["cloud_response"] = cloud_response.model_dump() if cloud_response else None
                        logger.warning(f"TaskOrchestrator (Request ID: {request_id}): Cloud refinement failed or no result. Falling back to local. Response: {cloud_response}")
                    details["stages"].append(cloud_stage_details)
                except TCPClientTimeoutError as e_timeout:
                    final_result = local_generated_text
                    source = "local_fallback_cloud_timeout"
                    details["stages"].append({"name": "cloud_refinement", "status": "timeout", "error": str(e_timeout), "duration_ms": int((time.monotonic() - cloud_refinement_start_time) * 1000)})
                    logger.warning(f"TaskOrchestrator (Request ID: {request_id}): Cloud refinement timed out. Falling back to local. Error: {e_timeout}")
                except TCPClientError as e_tcp:
                    final_result = local_generated_text
                    source = "local_fallback_cloud_tcp_error"
                    details["stages"].append({"name": "cloud_refinement", "status": "tcp_error", "error": str(e_tcp), "duration_ms": int((time.monotonic() - cloud_refinement_start_time) * 1000)})
                    logger.error(f"TaskOrchestrator (Request ID: {request_id}): TCP error during cloud refinement. Falling back to local. Error: {e_tcp}")
        
        except TaskOrchestratorError as e_task:
            error_message = str(e_task)
            source = "error_orchestration"
            logger.error(f"TaskOrchestrator (Request ID: {request_id}): Orchestration error: {e_task}")
        except Exception as e_unexpected:
            error_message = f"Unexpected error: {str(e_unexpected)}"
            source = "error_unexpected"
            logger.error(f"TaskOrchestrator (Request ID: {request_id}): Unexpected error in full flow: {e_unexpected}", exc_info=True)
        finally:
            await self._decrement_active_tasks()
            total_duration_ms = int((time.monotonic() - task_start_time) * 1000)
            details["total_duration_ms"] = total_duration_ms
            logger.info(f"TaskOrchestrator (Request ID: {request_id}): Full flow finished. Duration: {total_duration_ms}ms, Source: {source}")

        return {
            "request_id": request_id,
            "result_text": final_result,
            "source": source,
            "error": error_message,
            "details": details
        }

    async def process_incoming_tcp_message(self, message_dict: Dict[str, Any], writer: asyncio.StreamWriter) -> Optional[Dict[str, Any]]:
        """
        Handles messages received from the TCP server (i.e., commands from the remote cloud server).
        Returns a payload for a response message, or None if no direct response is needed or sent by handler.
        """
        await self._increment_active_tasks()
        response_payload_content: Optional[Dict[str, Any]] = None
        original_task_id = "unknown_tcp_task"
        original_command_action = "unknown_action"
        try:
            base_msg = BaseMessage(**message_dict)
            original_task_id = base_msg.task_id
            logger.info(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Received TCP message type \n" +
                        f"RPT.Slice.Start------------------------------------------------------\n{base_msg.message_type}\nRPT.Slice.End--------------------------------------------------------\n")

            if base_msg.message_type == "remote_command_to_local":
                cmd_payload = RemoteCommandToLocalPayload(**base_msg.payload)
                original_command_action = cmd_payload.command_action
                cmd_details_dict = cmd_payload.command_details if cmd_payload.command_details else {}
                status = "error"
                data: Optional[Dict[str, Any]] = None
                error_msg: Optional[str] = None

                if cmd_payload.command_action == "execute_owl_task":
                    details = ExecuteOwlTaskDetails(**cmd_details_dict)
                    logger.info(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Executing Owl Agent task: {details.agent_task_description[:50]}...")
                    try:
                        owl_result = await self.owl_agent_service.execute_task(
                            task_description=details.agent_task_description,
                            agent_config_override=details.owl_agent_config
                        )
                        if owl_result.get("status") == "success":
                            status = "success"
                            data = owl_result
                        else:
                            error_msg = owl_result.get("error_message", "Owl Agent execution failed.")
                            data = owl_result # Include partial data or error details from agent
                    except OwlAgentServiceError as e_owl:
                        error_msg = f"Owl Agent service error: {e_owl}"
                    except Exception as e_owl_generic:
                        error_msg = f"Unexpected error during Owl Agent task: {e_owl_generic}"
                        logger.error(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Unexpected Owl Agent error", exc_info=True)
                
                elif cmd_payload.command_action == "query_local_model_direct":
                    details = QueryLocalModelDirectDetails(**cmd_details_dict)
                    logger.info(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Executing direct local model query: {details.prompt[:50]}...")
                    try:
                        vllm_response = await self.vllm_service.generate_response(prompt=details.prompt, params=details.vllm_params)
                        generated_text = vllm_response.get("choices", [{}])[0].get("message", {}).get("content")
                        if generated_text:
                            status = "success"
                            data = {"generated_text": generated_text, "vllm_full_response": vllm_response}
                        else:
                            error_msg = "Local model returned empty content."
                            data = {"vllm_full_response": vllm_response}
                    except VLLMServiceError as e_vllm:
                        error_msg = f"Local model query failed: {e_vllm}"
                    except Exception as e_vllm_generic:
                        error_msg = f"Unexpected error during local model query: {e_vllm_generic}"
                        logger.error(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Unexpected direct query error", exc_info=True)

                elif cmd_payload.command_action == "get_local_status":
                    logger.info(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Getting local status.")
                    vllm_healthy = await self.vllm_service.check_health()
                    owl_status = await self.owl_agent_service.check_agent_health()
                    status = "success"
                    data = {
                        "local_server_id": settings.local_server_id,
                        "vllm_service_status": "healthy" if vllm_healthy else "unhealthy",
                        "owl_agent_status": owl_status,
                        "active_orchestrator_tasks": self._active_tasks_count,
                        "tcp_client_connected": self.tcp_client.is_connected,
                        "config_summary": {
                            "vllm_model": settings.vllm.model_name_or_path,
                            "confidence_threshold": settings.confidence.rouge_l_threshold,
                            "remote_server_host": settings.remote_server.host,
                            "remote_server_port": settings.remote_server.command_port
                        }
                    }
                else:
                    error_msg = f"Unknown command_action: {cmd_payload.command_action}"
                
                response_payload_content = LocalResponseToRemotePayload(
                    original_command_action=original_command_action,
                    status=status,
                    data=data,
                    error_message=error_msg
                ).model_dump()
            
            # Handle other message types from remote server if any (e.g., acknowledgements, config updates)
            # For now, only remote_command_to_local is processed for a direct response payload.
            else:
                logger.warning(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Received unhandled TCP message type: {base_msg.message_type}. No direct response generated.")
                # No response_payload_content means no standard response will be sent by the TCP server handler for this message.

        except Exception as e:
            logger.error(f"TaskOrchestrator (TCP Task ID: {original_task_id}): Error processing TCP message: {e}", exc_info=True)
            # Construct a generic error response payload if an unexpected error occurs during message processing
            response_payload_content = LocalResponseToRemotePayload(
                original_command_action=original_command_action, # Best effort
                status="error",
                error_message=f"Internal error processing TCP message: {str(e)}"
            ).model_dump()
        finally:
            await self._decrement_active_tasks()
        
        return response_payload_content

    async def process_batch_prompts_concurrently(self, prompts: List[str], common_params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Processes a batch of prompts concurrently using the local vLLM service.
        This method bypasses the confidence check and cloud refinement for simplicity, focusing on batch vLLM calls.
        Returns a list of results, each corresponding to a prompt.
        """
        if not prompts:
            return []
        
        logger.info(f"TaskOrchestrator: Starting batch processing for {len(prompts)} prompts.")
        await self._increment_active_tasks() # Count batch as one orchestrator task for simplicity
        
        tasks = []
        for i, prompt_text in enumerate(prompts):
            # Create a unique request_id for each sub-task in the batch
            batch_item_request_id = str(uuid.uuid4())
            tasks.append(self._process_single_prompt_for_batch(prompt_text, common_params, batch_item_request_id, i))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        await self._decrement_active_tasks()
        logger.info(f"TaskOrchestrator: Batch processing for {len(prompts)} prompts completed.")
        return results

    async def _process_single_prompt_for_batch(self, prompt: str, params: Optional[Dict[str, Any]], request_id: str, index: int) -> Dict[str, Any]:
        """Helper to process a single prompt as part of a batch, directly via vLLM."""
        logger.debug(f"TaskOrchestrator (Batch Item Request ID: {request_id}, Index: {index}): Processing prompt: {prompt[:50]}...")
        try:
            vllm_response = await self.vllm_service.generate_response(prompt=prompt, params=params)
            generated_text = vllm_response.get("choices", [{}])[0].get("message", {}).get("content")
            if not generated_text:
                raise VLLMServiceError("Local LLM returned empty content for batch item.")
            return {
                "request_id": request_id,
                "index": index,
                "prompt": prompt,
                "status": "success",
                "generated_text": generated_text,
                "vllm_full_response": vllm_response
            }
        except VLLMServiceError as e:
            logger.error(f"TaskOrchestrator (Batch Item Request ID: {request_id}, Index: {index}): VLLM error: {e}")
            return {
                "request_id": request_id,
                "index": index,
                "prompt": prompt,
                "status": "error",
                "error_message": str(e)
            }
        except Exception as e_unexp:
            logger.error(f"TaskOrchestrator (Batch Item Request ID: {request_id}, Index: {index}): Unexpected error: {e_unexp}", exc_info=True)
            return {
                "request_id": request_id,
                "index": index,
                "prompt": prompt,
                "status": "error",
                "error_message": f"Unexpected error: {str(e_unexp)}"
            }

