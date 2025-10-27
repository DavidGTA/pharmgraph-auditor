# cov_audit/p1_task_generator.py
import json
import logging
from pathlib import Path
import sys
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from core.llm_client import LLMClient

class TaskGenerator:
    """
    P1 阶段：使用 LLM 根据患者和处方信息生成审核任务列表。
    """
    def __init__(self, llm_client: LLMClient, prompt_template: str):
        self.llm = llm_client
        self.prompt_template = prompt_template
        logging.info("P1 TaskGenerator initialized.")

    def generate_tasks_for_case(self, input_data: Dict) -> List[Dict]:
        """
        为一个独立的病例生成审核任务。
        """
        input_json_str = json.dumps(input_data, ensure_ascii=False, indent=2)
        
        prompt = self.prompt_template.replace('{{input_json}}', input_json_str)
        # print(prompt)
        logging.info(f"Generating tasks for case:")
        response_str = self.llm.generate(prompt)
        
        try:
            tasks = json.loads(response_str)
            if isinstance(tasks, list):
                return tasks
            else:
                logging.error("P1 LLM returned valid JSON but not a list.")
                return []
        except json.JSONDecodeError:
            logging.error(f"P1 LLM failed to generate valid JSON task list. Response:\n{response_str}")
            return []