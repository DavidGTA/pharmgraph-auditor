# cov_audit/cov_main.py
import json
import yaml
import logging
from pathlib import Path
from decimal import Decimal
from datetime import date, datetime
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from cov_audit.p2_query_generator import QueryGenerator
from cov_audit.p3_query_executor import QueryExecutor
from cov_audit.p3_1_preprocessor import EvidencePreprocessor
from cov_audit.p4_llm_analyzer import LLMAnalyzer
from core.llm_client import LLMClient
from database.mysql_handler import MySQLHandler
from database.neo4j_handler import Neo4jHandler
from utils.logger import setup_logger

# --- 配置 ---
setup_logger()
logger = logging.getLogger("MedKG-Extractor.CoVaudit")

CONFIG_PATH = Path("configs/settings.yaml")
PATIENT_CONTEXT_PATH = Path("cov_audit/test_case/patient_context.json")
TASKS_INPUT_PATH = Path("cov_audit/test_case/tasks.json")
FINAL_OUTPUT_PATH = Path("cov_audit/test_case/tasks_with_evidence.json") 
FINAL_REPORT_PATH = Path("cov_audit/test_case/audit_report.json")

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
    
def json_serial_converter(o):
    """
    一个处理JSON无法序列化的数据类型的函数。
    特别是处理 Decimal 和 datetime 对象。
    """
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

def save_json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=json_serial_converter)

def main():
    """主流程：加载 -> 生成并映射 -> 去重执行 -> 聚合结果 -> 保存"""
    
    logging.info("--- Pipeline Start ---")
    
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    patient_context = load_json(PATIENT_CONTEXT_PATH)
    patient_profile = patient_context.get("patient_profile", {})
    prescriptions = patient_context.get("prescription_orders", [])
    logging.info(f"Loaded patient context from {PATIENT_CONTEXT_PATH}")
    
    tasks = load_json(TASKS_INPUT_PATH)
    logging.info(f"Loaded {len(tasks)} tasks from {TASKS_INPUT_PATH}")
    
    mysql_handler = MySQLHandler(config['mysql'])
    neo4j_handler = Neo4jHandler(config['neo4j'])
    
    query_gen = QueryGenerator()
    tasks_with_queries = []
    all_queries_flat = []

    for i, task in enumerate(tasks):
        task_id = f"task_index_{i}" 
        
        generated_queries = query_gen.generate_queries_for_task(task)
        
        tasks_with_queries.append({
            "task_id": task_id,
            "task_data": task,
            "queries": generated_queries
        })
        
        all_queries_flat.extend(generated_queries)
        
    logging.info(f"Generated a total of {len(all_queries_flat)} queries (before deduplication).")
    
    unique_queries_dict = {q['query']: q for q in all_queries_flat}
    unique_queries_list = list(unique_queries_dict.values())
    
    logging.info(f"Reduced to {len(unique_queries_list)} unique queries for execution.")
    
    executor = QueryExecutor(mysql_handler, neo4j_handler)
    execution_results = executor.execute_plan(unique_queries_list)
    logging.info("All unique queries have been executed.")

    final_results_by_task = []
    logging.info("Aggregating execution results back to each task...")

    for task_info in tasks_with_queries:
        task_evidence = {}
        
        for query_item in task_info['queries']:
            query_string = query_item['query']
            if query_string in execution_results:
                task_evidence[query_string] = execution_results[query_string]
            else:
                task_evidence[query_string] = {"error": "Query was generated but not found in execution results."}

        final_results_by_task.append({
            "task_id": task_info['task_id'],
            "task_data": task_info['task_data'],
            "evidence": task_evidence
        })

    preprocessor = EvidencePreprocessor()
    final_curated_tasks = []
    logging.info("Starting P3.5: Evidence Pre-processing and Curation...")
    
    for task_with_evidence in final_results_by_task:
        curated_task = preprocessor.process_task(task_with_evidence)
        final_curated_tasks.append(curated_task)

    save_json(final_curated_tasks, FINAL_OUTPUT_PATH) 
    logging.info(f"Final curated results saved to {FINAL_OUTPUT_PATH}")
    
    neo4j_handler.close()

    logging.info("--- Starting P4: Final LLM Analysis ---")
    
    llm_client = LLMClient(
        api_key=config['llm']['api_key'],
        base_url=config['llm']['base_url'],
        model_name=config['llm']['model_name']
    )
    p4_prompt_template = LLMClient.load_prompt_template(Path("prompts/p4_final_audit.txt"))
    
    analyzer = LLMAnalyzer(llm_client, p4_prompt_template)
    
    report = analyzer.generate_audit_report(
        patient_profile=patient_profile,
        prescriptions=prescriptions,
        curated_tasks=final_curated_tasks
    )

    save_json(report, FINAL_REPORT_PATH)
    logging.info(f"Final audit report saved to {FINAL_REPORT_PATH}")
    
    logging.info("--- Pipeline End ---")

if __name__ == "__main__":
    main()