# pipeline/p3_2_context_retriever.py
import json
import logging
from typing import Dict, List

from core.llm_client import LLMClient
from database.mysql_handler import MySQLHandler

class ContextualInstructionRetriever:
    """
    P3.6 Stage: Retrieves relevant administrative/contextual instructions.
    """
    def __init__(self, llm_client: LLMClient, mysql_handler: MySQLHandler, prompt_template: str):
        self.llm = llm_client
        self.mysql = mysql_handler
        self.prompt_template = prompt_template
        logging.info("P3.6 ContextualInstructionRetriever initialized.")

    def retrieve_instructions_for_case(self, patient_profile: Dict, prescriptions: List[Dict]) -> str:
        """
        For a given case, fetches all instructions, uses an LLM to select relevant
        tags, and returns the corresponding instruction texts.
        """
        # For simplicity, we'll focus on the first drug in the prescription list.
        # This can be expanded to handle multiple drugs if needed.
        if not prescriptions:
            return ""
        drug_name = prescriptions[0].get("drug_name")
        if not drug_name:
            return ""

        # 1. Fetch all records for the drug
        query = f"SELECT tags, instruction_text, llm_summary FROM administration_texts WHERE drug_canonical_name = '{drug_name}'"
        all_records = self.mysql.execute_query(query)

        if not all_records:
            return "注：知识库中无额外的管理性/指令性说明。"

        # 2. Collect all unique tags
        unique_tags = set()
        for record in all_records:
            # The 'tags' column is a JSON string, so we need to parse it
            try:
                tags_list = json.loads(record['tags'])
                for tag in tags_list:
                    unique_tags.add(tag)
            except (json.JSONDecodeError, TypeError):
                continue
        
        if not unique_tags:
            return "注：知识库中无额外的管理性/指令性说明。"

        # 3. Use LLM to select relevant tags
        context_str = json.dumps({
            "patient_profile": patient_profile,
            "prescription_orders": prescriptions
        }, ensure_ascii=False, indent=2)
        
        tags_str = json.dumps(list(unique_tags), ensure_ascii=False, indent=2)

        prompt = self.prompt_template.replace('{{PATIENT_PRESCRIPTION_CONTEXT}}', context_str)
        prompt = prompt.replace('{{AVAILABLE_TAGS}}', tags_str)
        
        response_str = self.llm.generate(prompt)
        
        relevant_tags = []
        try:
            relevant_tags = json.loads(response_str)
        except json.JSONDecodeError:
            logging.error(f"P3.6 LLM failed to return a valid JSON list of tags. Response: {response_str}")
            return "注：AI在筛选指令性说明时出错。"

        if not relevant_tags:
            return "注：根据患者情况，未筛选出需要特别关注的管理性/指令性说明。"

        # 4. Filter records based on relevant tags and format output
        relevant_instructions = []
        for record in all_records:
            try:
                record_tags = set(json.loads(record['tags']))
                # Check for intersection between the record's tags and the relevant tags
                if not record_tags.isdisjoint(relevant_tags):
                    instruction_text = record['instruction_text']
                    llm_summary = record['llm_summary']
                    instruction_text = f"{instruction_text} （说明摘要：{llm_summary}）"
                    # Add to list if not already present to avoid duplicates
                    if instruction_text not in relevant_instructions:
                        relevant_instructions.append(instruction_text)
            except (json.JSONDecodeError, TypeError):
                continue

        if not relevant_instructions:
            return "注：根据患者情况，未筛选出需要特别关注的管理性/指令性说明。"
            
        # Format the final output string
        output_lines = ["\n补充说明（来自知识库）："]
        for text in relevant_instructions:
            output_lines.append(f"- {text}")
            
        return "\n".join(output_lines)