# src/processing/document_processor.py

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from processing.document_parser import DocumentParser
from processing.task_runner import ExtractionTaskRunner
from core import models as pydantic_models
from core.models import DosageAdminPayload

logger = logging.getLogger("MedKG-Extractor")

class DocumentProcessor:
    """
    编排整个文档处理流程。
    它读取任务配置，并按顺序执行每个提取任务，管理任务间的上下文依赖。
    """

    def __init__(self, tasks_config: Dict[str, Any], task_runner: ExtractionTaskRunner):
        """
        初始化文档处理器。

        Args:
            tasks_config (Dict[str, Any]): 从 extraction_tasks.yaml 加载的配置。
            task_runner (ExtractionTaskRunner): 用于执行单个任务的实例。
        """
        self.task_definitions = tasks_config.get('tasks', {})
        self.task_order = tasks_config.get('task_execution_order', [])
        self.task_runner = task_runner
        
        if not self.task_definitions or not self.task_order:
            raise ValueError("Tasks configuration is missing 'tasks' or 'task_execution_order'.")
            
        logger.info("DocumentProcessor initialized with %d tasks in order.", len(self.task_order))

    def _get_context_from_result(self, task_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据任务配置，从成功的结果中提取需要传递给后续任务的上下文。
        支持从字符串或字典格式的 'provides_context' 配置中提取。

        Args:
            task_name (str): 任务的名称 (e.g., 'extract_composition').
            result (Dict[str, Any]): 任务成功执行后返回的数据。

        Returns:
            Dict[str, Any]: 提取出的上下文键值对。
        """
        new_context = {}
        task_config = self.task_definitions.get(task_name, {})
        context_provider_config  = task_config.get('provides_context')

        if not context_provider_config:
            return {}

        if isinstance(context_provider_config, dict):
            for context_key, source in context_provider_config.items():
                if source == "__custom_logic__":
                    if task_name == 'extract_composition' and context_key == 'active_ingredient_name':
                        substances = result.get('for_graphdb_contains_relation', [])
                        active_ingredients = [
                            s['substance_name'] for s in substances if s.get('role') == '活性成份'
                        ]
                        if active_ingredients:
                            value = ', '.join(active_ingredients)
                            new_context[context_key] = value
                            logger.info(f"Provided context via custom logic '{context_key}': '{value}'")
                        else:
                            logger.warning(f"Task '{task_name}' custom logic for '{context_key}' found no active ingredients.")
                
                elif source in result:
                    value = result[source]
                    new_context[context_key] = value
                    logger.info(f"Provided context via mapping '{context_key}' (from result key '{source}'): '{value}'")
                else:
                    logger.warning(f"Task '{task_name}' was configured to provide context '{context_key}' from result key '{source}', but this key was not found.")

        elif isinstance(context_provider_config, str):
             if context_provider_config in result:
                new_context[context_provider_config] = result[context_provider_config]
             else:
                logger.warning(f"Task '{task_name}' was configured to provide context '{context_provider_config}', but this key was not found in the result.")


        return new_context

    def _post_process_results(self, successful_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        在所有任务执行完毕后，对结果进行最终处理，例如合并子任务。
        """
        final_results = successful_results.copy()
        
        dosage_result = final_results.pop('extract_dosage_rules', None)
        admin_result = final_results.pop('extract_administration_texts', None)

        if dosage_result or admin_result:
            logger.info("Post-processing: Merging dosage and administration results.")
            merged_dosage_admin = DosageAdminPayload(
                for_dosage_rules=dosage_result.get('for_dosage_rules', []) if dosage_result else [],
                for_administration_texts=admin_result.get('for_administration_texts', []) if admin_result else []
            ).model_dump()
            final_results['dosage_and_administration'] = merged_dosage_admin

        return final_results


    def process(self, file_path: Path, force_rerun: bool = False) -> Optional[Dict[str, Any]]:
        """
        处理单个Markdown文档的完整流水线。

        Args:
            file_path (Path): 要处理的文档路径。
            force_rerun (bool): 是否强制重新运行所有任务。

        Returns:
            Optional[Dict[str, Any]]: 如果处理成功，返回一个包含所有提取结果的字典。
                                     如果发生严重错误，返回 None。
        """
        logger.info(f"--- Starting to process document: {file_path.name} ---")
        try:
            parser = DocumentParser(file_path)
        except FileNotFoundError:
            logger.error(f"Document not found: {file_path.name}. Aborting.")
            return None
        
        execution_context: Dict[str, Any] = {}
        successful_results: Dict[str, Any] = {}

        for task_name in self.task_order:
            if task_name not in self.task_definitions:
                logger.error(f"Task '{task_name}' is in execution order but not defined in tasks. Skipping.")
                continue

            task_config = self.task_definitions[task_name]
            
            input_text = parser.get_combined_text(task_config['input_sections'])
            if not input_text:
                logger.warning(f"Skipping task '{task_name}' because its required input sections {task_config['input_sections']} were not found.")
                continue

            required_context_keys = task_config.get('requires_context', [])
            try:
                context_args = {key: execution_context[key] for key in required_context_keys}
            except KeyError as e:
                logger.error(f"Cannot run task '{task_name}'. Missing required context: {e}. This might happen if a preceding task that provides this context failed.")
                continue

            model_name = task_config['output_model']
            pydantic_model = getattr(pydantic_models, model_name, None)
            if not pydantic_model:
                logger.error(f"Cannot run task '{task_name}'. Pydantic model '{model_name}' not found.")
                continue

            result = self.task_runner.run(
                task_config=task_config,
                pydantic_model=pydantic_model,
                source_document_id=file_path.name,
                input_text=input_text,
                context_args=context_args,
                force_rerun=force_rerun
            )

            if result:
                successful_results[task_name] = result
                new_context = self._get_context_from_result(task_name, result)
                execution_context.update(new_context)
        
        final_processed_results = self._post_process_results(successful_results)
        
        logger.info(f"--- Finished processing document: {file_path.name} ---")
        logger.info(f"Successfully executed {len(successful_results)} out of {len(self.task_order)} tasks.")

        return final_processed_results