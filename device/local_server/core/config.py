from pydantic_settings import BaseSettings
from typing import List, Optional, Dict, Any
import json
import os
import logging

logger = logging.getLogger(__name__)

# Define a base path for the project if needed, or resolve relative to this file.
# Assuming this file (config.py) is in local_server/core/
# And the project root is local_server/
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class VLLMSettings(BaseSettings):
    api_base_url: str = "http://localhost:8000/v1"
    model_name_or_path: str = "Qwen/Qwen1.5-14B-Chat-AWQ"
    default_max_tokens: int = 1024
    default_temperature: float = 0.7
    request_timeout: float = 60.0 # Timeout for requests to vLLM service

class ConfidenceSettings(BaseSettings):
    rouge_l_threshold: float = 0.3
    # Path relative to PROJECT_ROOT_DIR/config/
    keyword_triggers_file: str = "keyword_triggers.json" 

class RemoteServerSettings(BaseSettings):
    host: str = "127.0.0.1" # Default to localhost for easier local testing
    command_port: int = 5000 
    heartbeat_port: int = 5001 
    cloud_request_timeout_seconds: int = 15
    heartbeat_interval_seconds: int = 30
    tcp_client_reconnect_delay_seconds: int = 5
    tcp_client_max_reconnect_delay_seconds: int = 60

class OwlAgentSettings(BaseSettings):
    use_local_vllm: bool = True
    # Hypothetical config for Owl Agent to use local vLLM
    # vllm_for_owl_config: Dict[str, Any] = {
    #     "model_type": "openai", 
    #     "model_config_dict": {
    #         "model": "placeholder_model_name", # Will be replaced by vllm.model_name_or_path
    #         "api_base": "placeholder_api_base", # Will be replaced by vllm.api_base_url
    #         "api_key": "dummy_key_if_not_needed"
    #     }
    # }

class AppSettings(BaseSettings):
    vllm: VLLMSettings = VLLMSettings()
    confidence: ConfidenceSettings = ConfidenceSettings()
    remote_server: RemoteServerSettings = RemoteServerSettings()
    owl_agent: OwlAgentSettings = OwlAgentSettings()
    local_server_id: str = "local_server_dev_01"
    log_level: str = "INFO"

    class Config:
        env_file = os.path.join(PROJECT_ROOT_DIR, ".env") # .env file at project root
        env_prefix = "LOCAL_SERVER_" 
        env_nested_delimiter = '__'

settings = AppSettings()

# Update Owl Agent's conceptual config with actual vLLM settings
# if settings.owl_agent.use_local_vllm and hasattr(settings.owl_agent, 'vllm_for_owl_config'):
#     settings.owl_agent.vllm_for_owl_config['model_config_dict']['model'] = settings.vllm.model_name_or_path
#     settings.owl_agent.vllm_for_owl_config['model_config_dict']['api_base'] = settings.vllm.api_base_url

_loaded_keyword_triggers: Optional[List[str]] = None

async def load_keyword_triggers() -> List[str]:
    global _loaded_keyword_triggers
    if _loaded_keyword_triggers is not None:
        return _loaded_keyword_triggers

    file_path = os.path.join(PROJECT_ROOT_DIR, "config", settings.confidence.keyword_triggers_file)
    
    keywords_list: List[str] = []
    try:
        if not os.path.exists(file_path):
            logger.warning(f"Keyword triggers file not found at {file_path}. Creating an empty one.")
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            _loaded_keyword_triggers = []
            return []

        with open(file_path, "r", encoding="utf-8") as f:
            keywords_from_file = json.load(f)
            if isinstance(keywords_from_file, list) and all(isinstance(kw, str) for kw in keywords_from_file):
                keywords_list = [kw.lower() for kw in keywords_from_file]
                logger.info(f"Successfully loaded {len(keywords_list)} keyword triggers from {file_path}.")
            else:
                logger.warning(f"Keyword triggers file {file_path} does not contain a list of strings. Using empty list.")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from keyword triggers file {file_path}. Using empty list.", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading keywords from {file_path}: {e}. Using empty list.", exc_info=True)
    
    _loaded_keyword_triggers = keywords_list
    return _loaded_keyword_triggers

# Example to preload keywords if needed, or call it explicitly during app startup
# asyncio.run(load_keyword_triggers()) # This can't be run at module level directly if it's async

