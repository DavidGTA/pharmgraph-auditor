# tools/run_single_task.py

import argparse
import yaml
import logging
import json
from pathlib import Path
import sys
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from utils.logger import setup_logger
from core.llm_client import LLMClient
from core import models as pydantic_models
from database.mysql_handler import MySQLHandler
from processing.document_parser import DocumentParser
from processing.task_runner import ExtractionTaskRunner

setup_logger()
logger = logging.getLogger("MedKG-Extractor.SingleTaskRunner")

def load_configs(settings_path: str, tasks_path: str) -> Dict[str, Any]:
    """加载系统设置和任务定义文件。"""
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        with open(tasks_path, 'r', encoding='utf-8') as f:
            tasks = yaml.safe_load(f)
        return {"settings": settings, "tasks": tasks}
    except FileNotFoundError as e:
        logger.critical(f"Configuration file not found: {e.filename}")
        exit(1)
    except Exception as e:
        logger.critical(f"Error loading configuration files: {e}", exc_info=True)
        exit(1)

def main():
    """主执行函数，用于调试和运行单个提取任务。"""
    parser = argparse.ArgumentParser(
        description="Run a single, specific extraction task defined in extraction_tasks.yaml."
    )
    parser.add_argument(
        "-t", "--task", required=True, type=str,
        help="The name of the task to run (e.g., 'extract_dosage_rules')."
    )
    parser.add_argument(
        "-f", "--file", required=True, type=str,
        help="Path to the input markdown file."
    )
    parser.add_argument(
        "-k", "--kwargs", nargs='+',
        help="Additional key-value arguments for the prompt template, format: key=value key2=value2"
    )
    parser.add_argument(
        "--settings", type=str, default="configs/settings.yaml",
        help="Path to the system settings configuration file."
    )
    parser.add_argument(
        "--tasks-config", type=str, default="configs/extraction_tasks.yaml",
        help="Path to the extraction tasks definition file."
    )
    parser.add_argument(
        '--force-rerun', action='store_true',
        help="Force the task to run even if a successful record exists in the database."
    )
    args = parser.parse_args()

    logger.info("Loading configurations...")
    configs = load_configs(args.settings, args.tasks_config)
    settings = configs['settings']
    task_definitions = configs['tasks']['tasks']

    if args.task not in task_definitions:
        logger.critical(f"Task '{args.task}' not found in '{args.tasks_config}'.")
        logger.info(f"Available tasks are: {list(task_definitions.keys())}")
        exit(1)
    
    task_config = task_definitions[args.task]
    logger.info(f"Found configuration for task: '{args.task}'")

    context_args = {}
    if args.kwargs:
        for item in args.kwargs:
            try:
                key, value = item.split('=', 1)
                context_args[key] = value
            except ValueError:
                logger.error(f"Invalid format for --kwargs argument '{item}'. Use 'key=value'.")
                exit(1)
    logger.info(f"Using context arguments: {context_args}")

    try:
        logger.info("Initializing core services...")
        file_path = Path(args.file)
        
        document_parser = DocumentParser(file_path)
        
        llm_client = LLMClient(**settings['llm'])
        db_handler = MySQLHandler(settings['mysql'])
        
        prompt_dir = Path(settings['paths']['prompt_dir'])

        task_runner = ExtractionTaskRunner(llm_client, db_handler, prompt_dir)

        model_name = task_config['output_model']
        pydantic_model = getattr(pydantic_models, model_name, None)
        if not pydantic_model:
            logger.critical(f"Pydantic model '{model_name}' defined for task '{args.task}' not found in src/core/models.py.")
            exit(1)

    except FileNotFoundError as e:
        logger.critical(f"Input file not found: {e}")
        exit(1)
    except Exception as e:
        logger.critical(f"Failed to initialize services: {e}", exc_info=True)
        exit(1)

    logger.info("Preparing to run the task...")
    
    input_text = document_parser.get_combined_text(task_config['input_sections'])
    if not input_text:
        logger.error(f"Could not find the required input sections {task_config['input_sections']} in '{file_path.name}'. Aborting task.")
        exit(1)

    result = task_runner.run(
        task_config=task_config,
        pydantic_model=pydantic_model,
        source_document_id=file_path.name,
        input_text=input_text,
        context_args=context_args,
        force_rerun=args.force_rerun
    )

    print("\n" + "="*20 + " TASK RESULT " + "="*20)
    if result:
        print("Task executed successfully.")
        print("Log record has been saved to the database.")
        print("Extracted data:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Task failed or was skipped.")
        print("Check the application logs (and database logs) for details.")
    print("="*53)


if __name__ == "__main__":
    main()