# cov_audit/p2_query_generator.py
import json
import yaml
from pathlib import Path
import sys
import logging
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
print(PROJECT_ROOT)
sys.path.append(str(PROJECT_ROOT))

from core.llm_client import LLMClient
from database.mysql_handler import MySQLHandler
from database.neo4j_handler import Neo4jHandler

def load_config(settings_path):
    with open(settings_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

class QueryGenerator:
    def __init__(self, llm_client=None, p2_llm_prompt: Optional[str] = None):
        """
        初始化查询生成器。LLM相关参数是可选的，为将来使用保留。
        """
        # self.llm = llm_client
        # self.p2_prompt_template = p2_llm_prompt
        logging.info("QueryGenerator initialized in rule-based mode.")

    def generate_queries_for_task(self, task: dict) -> list:
        """
        主调度函数：根据任务类型，分派给不同的规则生成器。
        """
        if isinstance(task.get('riskType'), str):
            task['riskType'] = [task.get('riskType')]
        risk_type = task.get('riskType', [])
        if not risk_type:
            logging.warning(f"Task has no riskType. Skipping. Task: {task}")
            return []
            
        main_risk_type = risk_type[0]
        params = task.get('params', {})

        # --- 规则驱动的分支 ---
        if main_risk_type == "INDICATION_MISMATCH":
            return self._generate_indication_query(params)
        
        if main_risk_type == "INTERACTION_DRUG_DRUG":
            return self._generate_interaction_query(params)
        
        if main_risk_type == "ALLERGY_CONFLICT":
            return self._generate_allergy_queries(params)

        if main_risk_type == "CONTRAINDICATION_CONDITION":
            return self._generate_contraindication_queries(params)

        # --- 剂量相关风险，使用无LLM的规则生成器 ---
        if any("DOSAGE" in rt or "FREQUENCY" in rt or "ROUTE" in rt or "DOSE_ADJUSTMENT" in rt for rt in risk_type):
            return self._generate_dosage_queries_without_llm(params)
        
        logging.warning(f"No query generation rule found for risk_type: {main_risk_type}")
        return []

    def _generate_indication_query(self, params: dict) -> list:
        drug = params.get('drug_name')
        if not drug: return []
        query = f"MATCH (d:Drug {{canonical_name: '{drug}'}})-[r:INDICATED_FOR]->(dis:Disease) RETURN dis.name AS approved_indication, r.source_text AS evidence"
        return [{"lang": "cypher", "query": query}]

    def _generate_interaction_query(self, params: dict) -> list:
        drug_pair = params.get('drug_pair')
        if not drug_pair or len(drug_pair) != 2: return []
            
        drug1, drug2 = drug_pair
        query1 = f"SELECT * FROM interaction_details WHERE precipitant_drug_name = '{drug1}';"
        query2 = f"SELECT * FROM interaction_details WHERE precipitant_drug_name = '{drug2}';"
        
        return [{"lang": "sql", "query": query1}, {"lang": "sql", "query": query2}]
        
    def _generate_allergy_queries(self, params: dict) -> list:
        drug = params.get('drug_name')
        if not drug: return []
        
        cypher_query = f"MATCH (d:Drug {{canonical_name: '{drug}'}})-[r:CONTAINS]->(s:Substance) RETURN s.name AS substance_name, r.source_text AS evidence, r.role AS role"
        sql_query = f"SELECT DISTINCT source_text FROM allergy_rules WHERE drug_canonical_name = '{drug}'"
        
        return [{"lang": "cypher", "query": cypher_query}, {"lang": "sql", "query": sql_query}]

    def _generate_contraindication_queries(self, params: dict) -> list:
        drug = params.get('drug_name')
        if not drug: return []
        
        patient = params.get('patient_info', {})
        queries = []
        base_query = f"SELECT * FROM contraindication_rules WHERE drug_canonical_name = '{drug}'"
        
        if not patient:
            return [{"lang": "sql", "query": base_query}]
        
        if patient.get('age'):
            queries.append({"lang": "sql", "query": f"{base_query} AND (age_min_years IS NOT NULL OR age_max_years IS NOT NULL);"})
        if patient.get('gender'):
            queries.append({"lang": "sql", "query": f"{base_query} AND sex IS NOT NULL;"})
        if patient.get('weight'):
            queries.append({"lang": "sql", "query": f"{base_query} AND weight_min_kg IS NOT NULL OR weight_max_kg IS NOT NULL;"})
        if patient.get('organ_function') and patient['organ_function'].get('renal_impairment') != '无':
            queries.append({"lang": "sql", "query": f"{base_query} AND renal_impairment IS NOT NULL;"})
        if patient.get('organ_function') and patient['organ_function'].get('hepatic_impairment') != '无':
            queries.append({"lang": "sql", "query": f"{base_query} AND hepatic_impairment IS NOT NULL;"})
        if patient.get('pregnancy_status') and patient['pregnancy_status'] not in ['非妊娠', '不适用', '不适用(仅男性)']:
            queries.append({"lang": "sql", "query": f"{base_query} AND pregnancy_status IS NOT NULL;"})
        if patient.get('lactation_status') and patient['lactation_status'] not in ['非哺乳期', '不适用', '不适用(仅男性)']:
            queries.append({"lang": "sql", "query": f"{base_query} AND lactation_status IS NOT NULL;"})
        # 始终查询与病史相关的文本条件
        queries.append({"lang": "sql", "query": f"{base_query} AND other_conditions IS NOT NULL;"})

        # 去重
        return list({q['query']: q for q in queries}.values())

    # --- LLM驱动的方法---
    # def _generate_dosage_queries_with_llm(self, task: dict) -> list:
    #     """
    #     [DEPRECATED/FUTURE USE]
    #     This is a pure LLM-driven complex task.
    #     It populates the P2 LLM prompt template and calls the LLM.
    #     """
    #     if not self.llm or not self.p2_prompt_template:
    #         logging.warning("LLM client not configured. Falling back to rule-based dosage query.")
    #         return self._generate_dosage_queries_without_llm(task.get('params', {}))
    # 
    #     prompt = self.p2_prompt_template.replace(
    #         '{{task_json}}', json.dumps(task, ensure_ascii=False, indent=2)
    #     )
    #     response_str = self.llm.generate(prompt)
    #     try:
    #         query_plan = json.loads(response_str)
    #         return query_plan
    #     except json.JSONDecodeError:
    #         logging.error(f"LLM failed to generate a valid JSON query plan for task. Response: {response_str}")
    #         return []

    def _generate_dosage_queries_without_llm(self, params: dict) -> list:
        """
        为剂量检查任务生成一个宽泛的SQL查询，获取所有相关规则。
        """
        drug = params.get('drug_name')
        if not drug: return []
        
        query = f"SELECT * FROM dosage_rules WHERE drug_canonical_name = '{drug}';"
        return [{"lang": "sql", "query": query}]
        