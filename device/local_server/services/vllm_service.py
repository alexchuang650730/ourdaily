import httpx
from typing import Dict, Any, Optional
import logging

from ..core.config import settings # Adjusted import path

logger = logging.getLogger(__name__)

class VLLMServiceError(Exception):
    """Custom exception for VLLM Service errors."""
    def __init__(self, message, status_code=None, underlying_exception=None):
        super().__init__(message)
        self.status_code = status_code
        self.underlying_exception = underlying_exception
        self.message = message

    def __str__(self):
        return f"VLLMServiceError: {self.message} (Status Code: {self.status_code})"

class VLLMService:
    def __init__(self, http_client: httpx.AsyncClient):
        self.client = http_client
        # Ensure the URL ends with a slash if it's a base, or construct full path here
        base_url = settings.vllm.api_base_url.rstrip("/")
        self.chat_completions_url = f"{base_url}/chat/completions"
        self.completions_url = f"{base_url}/completions" # For completion endpoint if needed
        # Try to find a health endpoint. Common patterns are /health or /v1/health or at root.
        # vLLM OpenAI API server might not have a standard /health. Listing models is a good check.
        self.models_url = f"{base_url}/models"
        self.health_check_url = f"{base_url.rsplit('/v1', 1)[0]}/health" # Guessing a root health endpoint

        logger.info(f"VLLMService initialized. Chat completions URL: {self.chat_completions_url}, Models URL: {self.models_url}")

    async def generate_response(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """向vLLM服务发送请求并获取生成结果 using chat completions endpoint"""
        current_params = params if params else {}
        request_payload = {
            "model": settings.vllm.model_name_or_path,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": current_params.get("max_tokens", settings.vllm.default_max_tokens),
            "temperature": current_params.get("temperature", settings.vllm.default_temperature),
        }
        # Allow overriding other valid OpenAI API parameters if provided in params
        for key, value in current_params.items():
            if key not in request_payload and value is not None:
                request_payload[key] = value

        logger.debug(f"Sending request to vLLM ({self.chat_completions_url}): {request_payload}")
        try:
            response = await self.client.post(
                self.chat_completions_url, 
                json=request_payload, 
                timeout=settings.vllm.request_timeout
            )
            response.raise_for_status() # Raises HTTPStatusError for 4xx/5xx responses
            logger.debug(f"vLLM response status: {response.status_code}, content: {response.text[:200]}...")
            return response.json()
        except httpx.HTTPStatusError as e:
            error_message = f"vLLM API HTTP error: {e.response.status_code} - {e.response.text}"
            logger.error(error_message, exc_info=True)
            raise VLLMServiceError(error_message, status_code=e.response.status_code, underlying_exception=e) from e
        except httpx.TimeoutException as e:
            error_message = f"vLLM request timed out after {settings.vllm.request_timeout}s: {e}"
            logger.error(error_message, exc_info=True)
            raise VLLMServiceError(error_message, underlying_exception=e) from e
        except httpx.RequestError as e:
            error_message = f"vLLM request network error: {e}"
            logger.error(error_message, exc_info=True)
            raise VLLMServiceError(error_message, underlying_exception=e) from e
        except Exception as e: # Catch any other unexpected errors
            error_message = f"Unexpected error during vLLM request: {e}"
            logger.error(error_message, exc_info=True)
            raise VLLMServiceError(error_message, underlying_exception=e) from e

    async def check_health(self) -> bool:
        """
        Checks vLLM service health.
        Tries a dedicated health endpoint first, then listing models.
        """
        # Try a common health endpoint pattern (often at the root of the service, not under /v1)
        health_endpoints_to_try = [
            self.health_check_url, 
            settings.vllm.api_base_url.rstrip("/v1").rstrip("/") + "/healthz", # another common one
            settings.vllm.api_base_url.rstrip("/v1").rstrip("/") + "/live",
            settings.vllm.api_base_url.rstrip("/v1").rstrip("/") + "/ready",
        ]
        for endpoint in health_endpoints_to_try:
            try:
                logger.debug(f"Attempting health check at {endpoint}")
                response = await self.client.get(endpoint, timeout=5.0)
                if response.status_code == 200:
                    logger.info(f"vLLM health check: OK (endpoint {endpoint} responded with 200).")
                    return True
                logger.debug(f"Health check at {endpoint} failed with status {response.status_code}")
            except httpx.RequestError:
                logger.debug(f"Health check at {endpoint} failed (RequestError).")
            except Exception:
                logger.debug(f"Health check at {endpoint} failed (Exception).", exc_info=True)
        
        # Fallback to listing models if specific health endpoints fail
        logger.info("Specific health endpoints failed or not found, trying to list models as health check.")
        try:
            response = await self.client.get(self.models_url, timeout=10.0)
            if response.status_code == 200:
                models_data = response.json().get("data", [])
                if any(m.get("id") == settings.vllm.model_name_or_path for m in models_data):
                    logger.info(f"vLLM health check: OK (models endpoint responded, and target model '{settings.vllm.model_name_or_path}' is listed).")
                    return True
                elif models_data: # Service is up but model might not be loaded or name mismatch
                    logger.warning(f"vLLM health check: Models endpoint OK, but target model '{settings.vllm.model_name_or_path}' not found in list. Available: {[m.get('id') for m in models_data]}")
                    # Consider this healthy if the service is responsive, but log a warning.
                    return True 
                else:
                    logger.warning(f"vLLM health check: Models endpoint OK, but no models listed or unexpected format.")
                    return False # Or True if API being up is enough
            logger.warning(f"vLLM health check: Models endpoint responded with status {response.status_code}.")
            return False
        except httpx.RequestError as e:
            logger.error(f"vLLM health check failed (RequestError on models endpoint): {e}")
            return False
        except Exception as e:
            logger.error(f"vLLM health check failed (Exception on models endpoint): {e}", exc_info=True)
            return False

