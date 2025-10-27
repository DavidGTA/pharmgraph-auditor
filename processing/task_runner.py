# processing/task_runner.py

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Type, Optional

import pydantic

from core.llm_client import LLMClient, LLMResponseError
from core.models import DrugMetadata
from database.mysql_handler import MySQLHandler

logger = logging.getLogger("MedKG-Extractor")

class ExtractionTaskRunner:
    """
    负责执行单个、具体的提取任务。
    这是一个无状态的服务类，接收所有必要的依赖项和数据来完成工作。
    """

    def __init__(self, llm_client: LLMClient, db_handler: MySQLHandler, prompt_dir: Path):
        """
        初始化任务执行器。

        Args:
            llm_client (LLMClient): 用于与大语言模型交互的客户端。
            db_handler (MySQLHandler): 用于与数据库交互的处理器。
            prompt_dir (Path): 存放Prompt模板的目录路径。
        """
        self.llm_client = llm_client
        self.db_handler = db_handler
        self.prompt_dir = prompt_dir
        logger.debug("ExtractionTaskRunner initialized.")

    def run(
        self,
        task_config: Dict[str, Any],
        pydantic_model: Type[pydantic.BaseModel],
        source_document_id: str,
        input_text: str,
        context_args: Dict[str, Any],
        force_rerun: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        执行一个提取任务，包括检查断点续传、调用LLM、验证和日志记录。

        Args:
            task_config (Dict[str, Any]): 来自 extraction_tasks.yaml 的单个任务定义。
            pydantic_model (Type[pydantic.BaseModel]): 用于验证输出的Pydantic模型类。
            source_document_id (str): 源文档的唯一标识符（例如文件名）。
            input_text (str): 供LLM处理的输入文本。
            context_args (Dict[str, Any]): 用于格式化Prompt的上下文参数（如 drug_canonical_name）。
            force_rerun (bool): 如果为True，则忽略数据库中的已有成功记录。

        Returns:
            Optional[Dict[str, Any]]: 如果提取成功，返回经过Pydantic验证和序列化后的数据字典。
                                     如果任务被跳过或失败，则返回 None。
        """
        task_id = task_config['task_id']
        logger.info(f"--- Running Task: {task_id} for document: {source_document_id} ---")

        if not force_rerun:
            existing_data = self.db_handler.find_successful_extraction(source_document_id, task_id)
            if existing_data:
                logger.info(f"Task '{task_id}' skipped. Found existing successful record in database.")
                return existing_data
        
        log_data = {
            "source_document_id": source_document_id,
            "section_name": task_id,
            "model_name": self.llm_client.model_name,
            "prompt_version": task_config.get('version', '1.0'),
            "drug_canonical_name": context_args.get("drug_canonical_name"),
            "attempt_number": 1
        }

        extracted_data = None

        try:
            system_prompt_path = self.prompt_dir / "system_prompts" / task_config['prompts']['system']
            user_prompt_path = self.prompt_dir / "user_prompts" / task_config['prompts']['user']
            
            system_prompt = self.llm_client.load_prompt_template(system_prompt_path)
            user_prompt_template = self.llm_client.load_prompt_template(user_prompt_path)

            format_args = {"text_to_process": input_text, **context_args}
            
            try:
                user_prompt = user_prompt_template.format(**format_args)
            except KeyError as e:
                logger.critical(f"Task '{task_id}' failed. Prompt requires context key '{e.args[0]}' which was not provided in context_args: {list(context_args.keys())}")
                raise ValueError(f"Missing required context for prompt: {e}") from e

            log_data.update({
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "request_timestamp": datetime.now()
            })

            response_payload = self.llm_client.invoke_with_details(system_prompt, user_prompt, pydantic_model)
            extracted_data = response_payload["data"].model_dump()

            drug_name_for_log = None
            if pydantic_model is DrugMetadata:
                drug_name_for_log = extracted_data.get('canonical_name')
            else:
                drug_name_for_log = context_args.get('drug_canonical_name')

            log_data.update({
                "response_timestamp": datetime.now(),
                "duration_ms": response_payload["duration_ms"],
                "original_response": response_payload["raw_response"],
                "cleaned_output": extracted_data,
                "is_successful": True,
                "is_valid_json": True,
                "is_pydantic_valid": True,
                "is_selected": False,
                "prompt_tokens": response_payload["usage"].get("prompt_tokens"),
                "completion_tokens": response_payload["usage"].get("completion_tokens"),
                "total_tokens": response_payload["usage"].get("total_tokens"),
                "drug_canonical_name": drug_name_for_log
            })
            
            logger.info(f"Task '{task_id}' executed successfully.")

        except Exception as e:
            logger.error(f"Task '{task_id}' failed with error: {e}", exc_info=True)
            
            is_valid_json = not isinstance(getattr(e, 'original_exception', None), json.JSONDecodeError)
            is_pydantic_valid = not isinstance(getattr(e, 'original_exception', None), pydantic.ValidationError)

            log_data.update({
                "response_timestamp": datetime.now(),
                "is_successful": False,
                "is_valid_json": is_valid_json if isinstance(e, LLMResponseError) else None,
                "is_pydantic_valid": is_pydantic_valid if isinstance(e, LLMResponseError) else None,
                "is_selected": False,
                "error_message": str(e),
                "original_response": getattr(e, 'response_content', None)
            })
            if isinstance(getattr(e, 'original_exception', None), pydantic.ValidationError):
                log_data["pydantic_validation_error"] = str(e.original_exception)
            
            if isinstance(e, ValueError):
                log_data["error_message"] = f"Configuration Error: {e}"

        finally:
            if "request_timestamp" in log_data:
                self.db_handler.log_llm_extraction(log_data)

        return extracted_data