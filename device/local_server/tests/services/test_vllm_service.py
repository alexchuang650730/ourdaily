import pytest
import httpx
from unittest.mock import patch, AsyncMock

from local_server.core.config import AppSettings, VLLMSettings
from local_server.services.vllm_service import VLLMService, VLLMServiceError

# Default settings for tests, can be overridden via patching settings object
DEFAULT_VLLM_SETTINGS = VLLMSettings(
    api_base_url="http://testhost:8000/v1",
    model_name_or_path="test_model/test_model_awq",
    default_max_tokens=50,
    default_temperature=0.1,
    request_timeout=5.0
)

@pytest.fixture
def mock_settings():
    app_settings = AppSettings(vllm=DEFAULT_VLLM_SETTINGS)
    with patch("local_server.services.vllm_service.settings", app_settings):
        yield app_settings

@pytest.fixture
def vllm_service(mock_settings):
    # httpx_mock will be injected by pytest-httpx if used directly in test function
    # Here we instantiate the client manually for the service
    client = httpx.AsyncClient() 
    return VLLMService(http_client=client)

@pytest.mark.asyncio
async def test_vllm_service_initialization(mock_settings):
    client = httpx.AsyncClient()
    service = VLLMService(http_client=client)
    assert service.client == client
    assert service.chat_completions_url == "http://testhost:8000/v1/chat/completions"
    assert service.models_url == "http://testhost:8000/v1/models"
    assert service.health_check_url == "http://testhost:8000/health" # Based on current logic
    await client.aclose() # Clean up client

@pytest.mark.asyncio
async def test_generate_response_success(vllm_service, httpx_mock, mock_settings):
    prompt = "Hello vLLM!"
    expected_response_content = "Hello there!"
    mock_vllm_api_response = {
        "id": "cmpl-xxxxxxxxxxxx",
        "object": "chat.completion",
        "created": 1677652288,
        "model": mock_settings.vllm.model_name_or_path,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": expected_response_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
    httpx_mock.add_response(url=vllm_service.chat_completions_url, json=mock_vllm_api_response, status_code=200)

    response = await vllm_service.generate_response(prompt)
    
    assert response == mock_vllm_api_response
    assert response["choices"][0]["message"]["content"] == expected_response_content
    
    # Verify request payload
    request = httpx_mock.get_requests()[0]
    request_payload = json.loads(request.content)
    assert request_payload["model"] == mock_settings.vllm.model_name_or_path
    assert request_payload["messages"] == [{"role": "user", "content": prompt}]
    assert request_payload["max_tokens"] == mock_settings.vllm.default_max_tokens
    assert request_payload["temperature"] == mock_settings.vllm.default_temperature
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_generate_response_with_custom_params(vllm_service, httpx_mock, mock_settings):
    prompt = "Custom params test"
    custom_params = {"max_tokens": 100, "temperature": 0.9, "top_p": 0.8}
    httpx_mock.add_response(url=vllm_service.chat_completions_url, json={"choices": [{"message": {"content": "custom ok"}}]}, status_code=200)

    await vllm_service.generate_response(prompt, params=custom_params)
    
    request = httpx_mock.get_requests()[0]
    request_payload = json.loads(request.content)
    assert request_payload["max_tokens"] == 100
    assert request_payload["temperature"] == 0.9
    assert request_payload["top_p"] == 0.8
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_generate_response_http_status_error(vllm_service, httpx_mock):
    httpx_mock.add_response(url=vllm_service.chat_completions_url, status_code=500, text="Internal Server Error")
    with pytest.raises(VLLMServiceError) as excinfo:
        await vllm_service.generate_response("test prompt")
    assert excinfo.value.status_code == 500
    assert "vLLM API HTTP error: 500" in str(excinfo.value)
    assert "Internal Server Error" in str(excinfo.value)
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_generate_response_timeout_error(vllm_service, httpx_mock):
    httpx_mock.add_exception(httpx.TimeoutException("Request timed out"), url=vllm_service.chat_completions_url)
    with pytest.raises(VLLMServiceError) as excinfo:
        await vllm_service.generate_response("test prompt")
    assert "vLLM request timed out" in str(excinfo.value)
    assert isinstance(excinfo.value.underlying_exception, httpx.TimeoutException)
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_generate_response_request_error(vllm_service, httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("Connection failed"), url=vllm_service.chat_completions_url)
    with pytest.raises(VLLMServiceError) as excinfo:
        await vllm_service.generate_response("test prompt")
    assert "vLLM request network error" in str(excinfo.value)
    assert isinstance(excinfo.value.underlying_exception, httpx.ConnectError)
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_generate_response_empty_content(vllm_service, httpx_mock, mock_settings):
    # This test assumes that an empty content string is a valid scenario handled by the caller,
    # VLLMService itself should just return the response as is if API call is successful.
    # If VLLMService were to raise an error for empty content, this test would change.
    mock_vllm_api_response = {
        "choices": [{"message": {"content": ""}}]
    }
    httpx_mock.add_response(url=vllm_service.chat_completions_url, json=mock_vllm_api_response, status_code=200)
    response = await vllm_service.generate_response("prompt for empty")
    assert response["choices"][0]["message"]["content"] == ""
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_check_health_success_dedicated_endpoint(vllm_service, httpx_mock):
    httpx_mock.add_response(url=vllm_service.health_check_url, status_code=200, text="OK")
    assert await vllm_service.check_health() is True
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_check_health_success_models_endpoint(vllm_service, httpx_mock, mock_settings):
    # First, make dedicated health endpoints fail
    for url in [vllm_service.health_check_url, "http://testhost:8000/healthz", "http://testhost:8000/live", "http://testhost:8000/ready"]:
        httpx_mock.add_response(url=url, status_code=404)
    
    # Then, make models endpoint succeed with the target model
    mock_models_response = {"data": [{"id": mock_settings.vllm.model_name_or_path}, {"id": "other_model"}]}
    httpx_mock.add_response(url=vllm_service.models_url, json=mock_models_response, status_code=200)
    
    assert await vllm_service.check_health() is True
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_check_health_success_models_endpoint_model_not_listed_but_api_ok(vllm_service, httpx_mock, mock_settings, caplog):
    for url in [vllm_service.health_check_url, "http://testhost:8000/healthz", "http://testhost:8000/live", "http://testhost:8000/ready"]:
        httpx_mock.add_response(url=url, status_code=404)
    
    mock_models_response = {"data": [{"id": "another_model"}]}
    httpx_mock.add_response(url=vllm_service.models_url, json=mock_models_response, status_code=200)
    
    assert await vllm_service.check_health() is True # Still true as API i    expected_log_message = f"""target model \nRPT.Slice.Start------------------------------------------------------\n{mock_settings.vllm.model_name_or_path}\nRPT.Slice.End--------------------------------------------------------\n not found in list"""
    assert expected_log_message in caplog.text
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_check_health_all_endpoints_fail(vllm_service, httpx_mock):
    for url in [vllm_service.health_check_url, "http://testhost:8000/healthz", "http://testhost:8000/live", "http://testhost:8000/ready"]:
        httpx_mock.add_response(url=url, status_code=404)
    httpx_mock.add_response(url=vllm_service.models_url, status_code=503)
    
    assert await vllm_service.check_health() is False
    await vllm_service.client.aclose()

@pytest.mark.asyncio
async def test_check_health_models_endpoint_request_error(vllm_service, httpx_mock):
    for url in [vllm_service.health_check_url, "http://testhost:8000/healthz", "http://testhost:8000/live", "http://testhost:8000/ready"]:
        httpx_mock.add_response(url=url, status_code=404)
    httpx_mock.add_exception(httpx.ConnectError("Models endpoint connection failed"), url=vllm_service.models_url)
    
    assert await vllm_service.check_health() is False
    await vllm_service.client.aclose()

