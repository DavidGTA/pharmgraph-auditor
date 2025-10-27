# tools/manual_entry.py

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

import pydantic
import yaml

from core import models as pydantic_models
from database.mysql_handler import MySQLHandler
from utils.logger import setup_logger

setup_logger(log_level="INFO")
logger = logging.getLogger("MedKG-Extractor.ManualEntry")

def load_task_definitions(tasks_path="configs/extraction_tasks.yaml"):
    try:
        with open(tasks_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)['tasks']
    except Exception as e:
        logger.critical(f"Failed to load task definitions from '{tasks_path}': {e}")
        return None

class ManualEntryTool:
    def __init__(self, db_handler: MySQLHandler, task_definitions: Dict[str, Any]):
        self.db_handler = db_handler
        self.task_definitions = task_definitions

    def run(self):
        print("="*50)
        print(" MedKG Extractor: 人工标准答案录入工具")
        print("="*50)

        # 1. 获取基本信息
        source_document_id = input("请输入源文档的文件名 (例如, 阿贝西利片.md): ").strip()
        drug_canonical_name = input("请输入该药物的规范名称 (例如, 阿贝西利片): ").strip()
        
        task_name = self._select_task()
        if not task_name:
            return

        json_file_path_str = input(f"请输入已填写的 '{task_name}' 任务的JSON答案文件路径: ").strip()
        json_file_path = Path(json_file_path_str)

        if not source_document_id or not drug_canonical_name or not json_file_path.is_file():
            print("\n错误: 输入信息不完整或JSON文件不存在。请重试。")
            return

        # 2. 读取并验证JSON文件
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
        except Exception as e:
            print(f"\n错误: 读取或解析JSON文件失败: {e}")
            return
            
        task_config = self.task_definitions[task_name]
        model_name = task_config['output_model']
        pydantic_model = getattr(pydantic_models, model_name, None)

        if not pydantic_model:
            print(f"\n错误: 在core/models.py中找不到模型 '{model_name}'。")
            return

        try:
            # 使用Pydantic模型进行严格验证
            validated_data_obj = pydantic_model.model_validate(user_data)
            validated_data_dict = validated_data_obj.model_dump()
            print("\n数据验证成功！")
        except pydantic.ValidationError as e:
            print("\n错误: 您的JSON数据未能通过Pydantic模型验证。请根据以下错误信息修改您的文件：")
            print(e)
            return

        # 3. 准备并存入数据库
        task_id = task_config['task_id']
        log_data = {
            "source_document_id": source_document_id,
            "section_name": task_id,
            "drug_canonical_name": drug_canonical_name,
            "attempt_number": 1,
            "system_prompt": "N/A - Manual Entry",
            "user_prompt": "N/A - Manual Entry",
            "original_response": json.dumps(validated_data_dict, ensure_ascii=False),
            "cleaned_output": validated_data_dict,
            "is_successful": True,
            "is_valid_json": True,
            "is_pydantic_valid": True,
            "is_selected": True,
            "model_name": "human_ground_truth",
            "request_timestamp": datetime.now(),
            "response_timestamp": datetime.now(),
            "duration_ms": 0,
            "prompt_version": "manual_v1.0"
        }

        try:
            self.db_handler.log_llm_extraction(log_data)
            print(f"\n成功！标准答案已作为任务 '{task_id}' 存入数据库。")
            print("您现在可以运行 `tools/save_to_db.py` 将这条记录加载到生产库中。")
        except Exception as e:
            print(f"\n错误: 存入数据库时发生错误: {e}")

    def _select_task(self) -> str | None:
        """让用户从列表中选择一个任务。"""
        task_names = list(self.task_definitions.keys())
        print("\n请选择您要录入答案的任务:")
        for i, name in enumerate(task_names):
            print(f"  {i+1}: {name}")
        
        try:
            choice = int(input(f"请输入选项编号 (1-{len(task_names)}): ").strip())
            if 1 <= choice <= len(task_names):
                return task_names[choice - 1]
            else:
                print("无效的选项。")
                return None
        except ValueError:
            print("无效的输入，请输入数字。")
            return None

def main():
    # --- Load Config and Init Handlers ---
    try:
        with open("configs/settings.yaml", 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        
        task_definitions = load_task_definitions()
        if not task_definitions:
            return
            
        mysql_handler = MySQLHandler(settings['mysql'])
    except Exception as e:
        logger.critical(f"Failed to initialize: {e}", exc_info=True)
        exit(1)

    tool = ManualEntryTool(mysql_handler, task_definitions)
    tool.run()

if __name__ == "__main__":
    main()