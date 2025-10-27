# core/llm_client.py

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from openai import OpenAI
import pydantic
from json_repair import repair_json
import logging

logger = logging.getLogger("MedKG-Extractor")

# 1. 定义自定义异常类
class LLMResponseError(ValueError):
    """
    当LLM响应无法被正确解析或验证时抛出。
    
    Attributes:
        message (str): 错误的描述信息。
        response_content (str): 从LLM获取的原始、未经处理的响应字符串。
        original_exception (Exception): 触发此错误的原始异常 (e.g., JSONDecodeError)。
    """
    def __init__(self, message: str, response_content: str, original_exception: Exception = None):
        super().__init__(message)
        self.response_content = response_content
        self.original_exception = original_exception

    def __str__(self):
        return f"{super().__str__()} | Raw Response: '{self.response_content[:100]}...'"


class LLMClient:
    """
    一个封装了与LLM API交互的客户端。
    """
    def __init__(self, api_key: str, base_url: str, model_name: str, timeout: int = 600):
        """
        初始化LLM客户端。

        Args:
            api_key (str): OpenAI API密钥。
            base_url (str): API的基础URL。
            model_name (str): 要使用的模型名称。
            timeout (int): API请求的超时时间（秒）。
        """
        try:
            self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            self.model_name = model_name
            logger.info(f"LLMClient initialized for model: {self.model_name}")
        except Exception as e:
            logger.critical(f"Failed to initialize OpenAI client: {e}", exc_info=True)
            raise
    
    def generate(self, prompt: str) -> str:
        """
        使用配置的模型生成文本。

        Args:
            prompt (str): 发送给模型的用户提示。

        Returns:
            str: 模型生成的文本内容。
        """
        try:
            logger.debug(f"Sending prompt to LLM: {prompt[:200]}...")
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            response_content = completion.choices[0].message.content
            # logger.debug("Received response from LLM.")
            # logger.debug(f"LLM raw response: {response_content}")
            cleaned_response = repair_json(response_content, ensure_ascii=False)
            logger.debug(f"LLM cleaned response: {cleaned_response}")

            return cleaned_response.strip()
        except Exception as e:
            logger.error(f"Error during LLM generation: {e}", exc_info=True)
            return "[]"
    
    @staticmethod
    def load_prompt_template(prompt_path: Path) -> str:
        """
        从文件加载Prompt模板。

        Args:
            prompt_path (Path): Prompt模板文件的路径。

        Returns:
            str: Prompt模板内容。
        """
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Prompt template not found at: {prompt_path}")
            raise
        except Exception as e:
            logger.error(f"Error reading prompt template {prompt_path}: {e}", exc_info=True)
            raise

    def invoke_with_details(
        self, 
        system_prompt: str, 
        user_prompt: str, 
        pydantic_model: pydantic.BaseModel
    ) -> Dict[str, Any]:
        """
        调用LLM API，获取响应，并使用Pydantic模型进行验证和解析。

        Args:
            system_prompt (str): 系统提示。
            user_prompt (str): 用户提示。
            pydantic_model (pydantic.BaseModel): 用于验证输出的Pydantic模型类。

        Returns:
            pydantic.BaseModel: 一个填充了LLM响应数据的Pydantic模型实例。
        
        Raises:
            LLMResponseError: 如果LLM响应无法解析为JSON或验证失败。
            Exception: 如果API调用失败。
        """
        logger.debug(f"Invoking LLM with model {self.model_name}...")
        
        response_content = None
        try:
            start_time = datetime.now()
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            response_content = response.choices[0].message.content
            cleaned_response = repair_json(response_content, ensure_ascii=False)
            logger.debug(f"LLM cleaned response: {cleaned_response}")

            llm_json = json.loads(cleaned_response)
            validated_data = pydantic_model.model_validate(llm_json)
            
            logger.info("LLM response successfully parsed and validated.")
            return {
                "data": validated_data,
                "raw_response": response_content,
                "usage": response.usage.model_dump() if response.usage else {},
                "duration_ms": duration_ms
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode LLM response into JSON: {e}")
            logger.error(f"LLM response that failed decoding: {response_content}")
            raise LLMResponseError(
                "LLM response is not valid JSON.",
                response_content=response_content,
                original_exception=e
            )
        except pydantic.ValidationError as e:
            logger.error(f"LLM response failed Pydantic validation: {e}")
            logger.error(f"LLM response that failed validation: {response_content}")
            raise LLMResponseError(
                "LLM response does not match the Pydantic model.",
                response_content=response_content,
                original_exception=e
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred during LLM invocation: {e}", exc_info=True)
            if response_content:
                 raise LLMResponseError(
                    f"An unexpected error occurred: {e}",
                    response_content=response_content,
                    original_exception=e
                )
            raise