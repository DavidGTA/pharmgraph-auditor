# cov_audit/run_audit_pipeline.py
import json
import logging
from pathlib import Path
from datetime import datetime
import argparse
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from core.llm_client import LLMClient
from cov_audit.p1_task_generator import TaskGenerator
from cov_audit.p2_query_generator import QueryGenerator
from cov_audit.p3_query_executor import QueryExecutor
from cov_audit.p3_1_preprocessor import EvidencePreprocessor
from cov_audit.p3_2_context_retriever import ContextualInstructionRetriever
from cov_audit.p4_llm_analyzer import LLMAnalyzer
from database.mysql_handler import MySQLHandler
from database.neo4j_handler import Neo4jHandler

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CONFIG_PATH = Path("configs/settings.yaml")

def load_config(path):
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def json_serial_converter(o):
    from decimal import Decimal
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, (datetime, Path)): return str(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=json_serial_converter)

def main(args):
    config = load_config(CONFIG_PATH)
    
    llm_client = LLMClient(
        api_key=config['llm']['api_key'],
        base_url=config['llm']['base_url'],
        model_name=config['llm']['model_name']
    )
    
    mysql_handler = MySQLHandler(config['mysql'])
    neo4j_handler = Neo4jHandler(config['neo4j'])

    p1_prompt = LLMClient.load_prompt_template(Path("prompts/p1_task_generation.txt"))
    p1_generator = TaskGenerator(llm_client, p1_prompt)

    p2_generator = QueryGenerator()
    p3_executor = QueryExecutor(mysql_handler, neo4j_handler)
    p3_1_preprocessor = EvidencePreprocessor()

    p3_2_prompt = LLMClient.load_prompt_template(Path("prompts/p3_2_tag_selection.txt"))
    p3_2_retriever = ContextualInstructionRetriever(llm_client, mysql_handler, p3_2_prompt)

    p4_prompt = LLMClient.load_prompt_template(Path("prompts/p4_final_audit.txt"))
    p4_analyzer = LLMAnalyzer(llm_client, p4_prompt)
    
    logging.info(f"Loading audit cases from: {args.input_file}")
    cases = load_json(args.input_file)
    all_results = []

    output_dir = args.input_file.parent

    for i, case in enumerate(cases):
        case_id = case.get("input_data", {}).get("case_id", f"unknown_case_{i}")
        logging.info(f"--- Processing Case: {case_id} ({i+1}/{len(cases)}) ---")
        
        input_for_pipeline = case["input_data"].copy()
        input_for_pipeline.pop('case_id', None)

        case_result = {
            "case_id": case_id,
            "input_data": input_for_pipeline,
            "golden_audit_report": case.get("golden_audit_report"),
            "pipeline_results": {}
        }

        p1_tasks = p1_generator.generate_tasks_for_case(input_for_pipeline)
        case_result["pipeline_results"]["p1_generated_tasks"] = p1_tasks
        if not p1_tasks:
            logging.warning("P1 generated no tasks. Skipping to next case.")
            all_results.append(case_result)
            continue
            
        all_queries = []
        tasks_with_queries_map = []
        for task in p1_tasks:
            queries = p2_generator.generate_queries_for_task(task)
            all_queries.extend(queries)
            tasks_with_queries_map.append({"task_data": task, "queries": queries})
        
        unique_queries = list({q['query']: q for q in all_queries}.values())
        case_result["pipeline_results"]["p2_generated_queries"] = unique_queries

        p3_results = p3_executor.execute_plan(unique_queries)
        case_result["pipeline_results"]["p3_execution_results"] = p3_results

        curated_tasks = []
        for task_info in tasks_with_queries_map:
            evidence = {q['query']: p3_results.get(q['query'], []) for q in task_info['queries']}
            curated_task = p3_1_preprocessor.process_task({
                "task_data": task_info['task_data'],
                "evidence": evidence
            })
            curated_tasks.append(curated_task)
        case_result["pipeline_results"]["p3_1_curated_tasks_with_evidence"] = curated_tasks

        p3_2_instructions = p3_2_retriever.retrieve_instructions_for_case(
            patient_profile=case["input_data"]["patient_profile"],
            prescriptions=case["input_data"]["prescription_orders"]
        )
        case_result["pipeline_results"]["p3_2_contextual_instructions"] = p3_2_instructions

        p4_report = p4_analyzer.generate_audit_report(
            patient_profile=case["input_data"]["patient_profile"],
            prescriptions=case["input_data"]["prescription_orders"],
            curated_tasks=curated_tasks,
            contextual_instructions=p3_2_instructions
        )
        case_result["pipeline_results"]["p4_llm_generated_report"] = p4_report
        
        all_results.append(case_result)
        logging.info(f"--- Finished Case: {case_id} ---")

        # 在每个 case 完成后立即保存
        individual_filename = f"{args.input_file.stem}_audit_{case_id}.json"
        individual_output_path = output_dir / individual_filename
        save_json(case_result, individual_output_path)
        logging.info(f"Saved individual result for {case_id} to: {individual_output_path}")

    # --- 3. 保存所有结果 ---
    final_filename = f"{args.input_file.stem}_audit_all_cases.json"
    final_output_path = output_dir / final_filename
    save_json(all_results, final_output_path)
    logging.info(f"Batch processing complete. All results aggregated and saved to: {final_output_path}")

    # --- 4. 清理 ---
    neo4j_handler.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full audit pipeline on a case file.")
    parser.add_argument("input_file", type=Path, help="Path to the JSON file containing audit cases.")
    args = parser.parse_args()
    
    main(args)