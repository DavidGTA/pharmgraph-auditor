# cov_audit/run_baseline.py
import json
import logging
from pathlib import Path
import argparse
import sys
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from core.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CONFIG_PATH = Path("configs/settings.yaml")

def load_config(path):
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main(args):
    config = load_config(CONFIG_PATH)
    
    llm_client = LLMClient(
        api_key=config['llm']['api_key'],
        base_url=config['llm']['base_url'],
        model_name=config['llm']['model_name']
    )
    
    try:
        baseline_prompt_template = LLMClient.load_prompt_template(Path("prompts/baseline_1.txt"))
        # baseline_prompt_template = LLMClient.load_prompt_template(Path("prompts/baseline_2.txt"))
    except FileNotFoundError:
        logging.error("FATAL: prompts/baseline_1.txt not found. Exiting.")
        # logging.error("FATAL: prompts/baseline_2.txt not found. Exiting.")
        return

    logging.info(f"Loading audit cases from: {args.input_file}")
    cases = load_json(args.input_file)
    
    output_dir = args.input_file.parent / args.run_name
    logging.info(f"Results will be saved to: {output_dir}")

    for i, case in enumerate(cases):
        case_id = case.get("input_data", {}).get("case_id", f"unknown_case_{i}")
        logging.info(f"--- Processing Case (Baseline): {case_id} ({i+1}/{len(cases)}) ---")

        input_for_prompt = case.get("input_data", {}).copy()
        input_for_prompt.pop('case_id', None)
        input_json_str = json.dumps(input_for_prompt, ensure_ascii=False, indent=2)

        prompt = baseline_prompt_template.replace('{{PATIENT_PRESCRIPTION}}', input_json_str)

        response_str = llm_client.generate(prompt)

        result_data = {}
        try:
            result_data = json.loads(response_str)
        except json.JSONDecodeError:
            logging.error(f"LLM response for {case_id} was not valid JSON. Saving raw response.")
            result_data = {"error": "LLM response was not valid JSON.", "raw_response": response_str}
        
        output_filename = f"{case_id}.json"
        output_path = output_dir / output_filename
        save_json(result_data, output_path)
        logging.info(f"Saved baseline result for {case_id} to: {output_path}")

    logging.info("Baseline run complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a baseline LLM evaluation on a case file.")
    parser.add_argument("input_file", type=Path, help="Path to the JSON file containing audit cases.")
    parser.add_argument(
        "--run-name", 
        type=str, 
        default="baseline_run_1", 
        help="Name for the output subdirectory where results will be saved (e.g., 'baseline_1', 'gpt4o_baseline')."
    )
    args = parser.parse_args()
    
    main(args)