# cov_audit/p4_llm_analyzer.py
import json
import logging
from typing import List, Dict, Any

from core.llm_client import LLMClient

class LLMAnalyzer:
    def __init__(self, llm_client: LLMClient, prompt_template: str):
        """
        初始化LLM分析器。
        Args:
            llm_client: LLM客户端实例。
            prompt_template: 用于生成审核报告的P4主Prompt模板。
        """
        self.llm = llm_client
        self.prompt_template = prompt_template
        logging.info("P4 LLMAnalyzer initialized.")

    def _aggregate_context(self, curated_tasks: List[Dict]):
        """
        从所有任务中聚合出统一的患者信息和处方列表。
        """
        patient_info_parts = {}
        prescriptions = {}

        for task in curated_tasks:
            params = task.get('task_data', {}).get('params', {})
            
            # 聚合患者信息
            if 'patient_info' in params:
                for key, value in params['patient_info'].items():
                    if key not in patient_info_parts and value:
                        patient_info_parts[key] = value

            # 聚合处方信息 (兼容两种task格式)
            drug_name = params.get('drug_name')
            prescription_details = params.get('current_prescription', params)
            
            if drug_name and drug_name not in prescriptions:
                dose = prescription_details.get('dose_per_admin', {})
                prescriptions[drug_name] = (
                    f"- {drug_name}: "
                    f"{dose.get('value')}{dose.get('unit', '')}, "
                    f"{prescription_details.get('frequency', 'N/A')}, "
                    f"{prescription_details.get('route', 'N/A')}"
                )
        
        patient_profile_str = json.dumps(patient_info_parts, ensure_ascii=False, indent=2)
        prescription_list_str = "\n".join(prescriptions.values())
        
        return patient_profile_str, prescription_list_str

    def _format_risk_checks(self, curated_tasks: List[Dict]) -> str:
        """
        将每个任务及其整理后的证据格式化为清晰的文本块。
        """
        output_blocks = []
        for i, task in enumerate(curated_tasks):
            task_data = task.get('task_data', {})
            curated_evidence = task.get('curated_evidence', '无可用证据。')
            if isinstance(task_data.get('riskType'), str):
                task_data['riskType'] = [task_data['riskType']]
            
            block = (
                f"--- 风险审核项 {i+1}: {task_data.get('description', 'N/A')} ---\n"
                f"涉及风险类型: {', '.join(task_data.get('riskType', []))}\n"
                f"相关证据:\n{curated_evidence}"
            )
            output_blocks.append(block)
        
        return "\n\n".join(output_blocks)

    def generate_audit_report(self, 
                              patient_profile: Dict, 
                              prescriptions: List[Dict],  
                              curated_tasks: List[Dict],
                              contextual_instructions: str) -> Dict:
        """
        生成最终的用药审核报告。
        
        Args:
            patient_profile (Dict): 完整的患者信息档案。
            prescriptions (List[Dict]): 完整的处方列表。
            curated_tasks (List[Dict]): 经过P3.5处理后的任务列表。

        Returns:
            Dict: LLM生成的审核报告。
        """
        if not curated_tasks:
            logging.warning("No curated tasks provided to generate report.")
            return {}

        patient_profile_str = json.dumps(patient_profile, ensure_ascii=False, indent=2)
        prescription_list_str = json.dumps(prescriptions, ensure_ascii=False, indent=2)
        risk_checks_str = self._format_risk_checks(curated_tasks)
        
        # 填充主Prompt
        prompt = self.prompt_template.replace('{{PATIENT_PROFILE}}', patient_profile_str)
        prompt = prompt.replace('{{PRESCRIPTION_LIST}}', prescription_list_str)
        prompt = prompt.replace('{{CONTEXTUAL_INSTRUCTIONS}}', contextual_instructions)
        prompt = prompt.replace('{{RISK_CHECKS_AND_EVIDENCE}}', risk_checks_str)
        
        logging.info("Generating final audit report with LLM...")
        logging.debug(f"P4 Prompt sent to LLM:\n{prompt}") # 调试时可以打开
        print(prompt)
        response_str = self.llm.generate(prompt)
        
        try:
            report = json.loads(response_str)
            return report
        except json.JSONDecodeError:
            logging.error(f"Failed to decode LLM response into JSON. Response:\n{response_str}")
            return {"error": "LLM response was not valid JSON.", "raw_response": response_str}