# cov_audit/p4_preprocessor.py
import logging
from typing import Dict, Any, List
import json

class EvidencePreprocessor:
    def process_task(self, task_with_evidence: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理单个任务，对原始证据进行筛选、评分和格式化。
        """
        task_data = task_with_evidence['task_data']
        evidence = task_with_evidence['evidence']
        risk_type = task_data['riskType'][0]

        # 主分发逻辑
        curated_text = "未找到适用于此风险类型的证据处理规则。"
        
        if "DOSAGE" in risk_type or "DOSE_ADJUSTMENT" in risk_type:
            curated_text = self._process_dosage_evidence(task_data, evidence)
        elif risk_type == "INDICATION_MISMATCH":
            curated_text = self._process_indication_evidence(task_data, evidence)
        elif risk_type == "INTERACTION_DRUG_DRUG":
            curated_text = self._process_interaction_evidence(task_data, evidence)
        elif risk_type == "ALLERGY_CONFLICT":
            curated_text = self._process_allergy_evidence(task_data, evidence)
        elif risk_type == "CONTRAINDICATION_CONDITION":
            curated_text = self._process_contraindication_evidence(task_data, evidence)

        task_with_evidence['curated_evidence'] = curated_text
        return task_with_evidence

    # --- 以下是针对各类风险的具体处理方法 ---
    def _process_dosage_evidence(self, task_data: Dict, evidence: Dict) -> str:
        """
        对剂量证据进行精细化评分、筛选和格式化，区分常规和调整任务。
        """
        params = task_data.get('params', {})
        risk_types = task_data.get('riskType', [])
        
        # --- 1. 统一提取任务信息 ---
        # 兼容两种 task 格式
        prescription = params.get('current_prescription', params)
        
        patient_info = params.get('patient_info', {})
        if isinstance(patient_info.get('age'), dict):
            patient_age = patient_info.get('age', {}).get('value')
        elif isinstance(patient_info.get('age'), (int, float)):
            patient_age = patient_info.get('age')
        else:
            patient_age = None
        
        if isinstance(patient_info.get('organ_function'), dict):
            patient_renal = patient_info.get('organ_function', {}).get('renal_impairment', '未知')
            patient_hepatic = patient_info.get('organ_function', {}).get('hepatic_impairment', '未知')
        else:
            patient_renal = '未知'
            patient_hepatic = '未知'
        
        diagnoses = params.get('context', {}).get('diagnoses', [])

        # --- 2. 提取所有规则 ---
        all_rules = []
        for _, result_list in evidence.items():
            if isinstance(result_list, list):
                all_rules.extend(result_list)
        
        if not all_rules:
            return "知识库中未找到与该药物相关的任何剂量规则。"

        # --- 3. 精细化评分阶段 ---
        scored_rules = []
        for rule in all_rules:
            score = 0
            is_adjustment_rule = False # 标记这是否是一条“调整”规则

            # 检查点 A: 硬性条件筛选 (不匹配则直接跳过)
            if patient_age is not None:
                if rule.get('age_min_years') and patient_age < rule['age_min_years']: continue
                if rule.get('age_max_years') and patient_age > rule['age_max_years']: continue

            # 检查点 B: 特殊人群匹配 (核心评分项)
            # 肝肾功能
            if rule.get('renal_impairment'):
                is_adjustment_rule = True
                if rule['renal_impairment'] == patient_renal:
                    score += 15 # 高分：患者情况与规则完全匹配
                else:
                    score -= 5 # 减分：规则针对特殊人群，但患者不符
            
            if rule.get('hepatic_impairment'):
                is_adjustment_rule = True
                if rule['hepatic_impairment'] == patient_hepatic:
                    score += 15 # 高分
                else:
                    score -= 5 # 减分
            
            # 其他条件 (如合并用药)
            if rule.get('other_conditions'):
                is_adjustment_rule = True
                # 这是一个简化的匹配，实际应用中可能需要更复杂的逻辑
                # 这里我们只给它一个基础分，表示它是一条特殊规则
                # score += 5 
            
            # 检查点 C: 标准/通用规则匹配
            is_standard_rule = not (rule.get('renal_impairment') or rule.get('hepatic_impairment'))
            
            if is_standard_rule:
                if patient_renal == '无' and patient_hepatic == '无':
                    score += 5 # 患者是标准人群，匹配标准规则
                else:
                    # 患者是特殊人群，标准规则的参考价值降低
                    score += 1 

            # 检查点 D: 适应症/上下文匹配
            # 在数据库中，notes字段通常包含适应症信息
            rule_context = rule.get('notes', '') + rule.get('source_text', '')
            if diagnoses and any(diag_keyword in rule_context for diag_keyword in diagnoses):
                score += 3 # 适应症相关，加分

            # 检查点 E: 任务类型偏好调整
            # 如果是剂量调整任务，我们更偏爱“调整”规则
            if "DOSE_ADJUSTMENT_MISSED" in risk_types and is_adjustment_rule:
                score += 10 # 额外加分，突出调整规则的重要性
            # 如果是常规剂量任务，我们更偏爱“标准”规则
            if "DOSAGE_OVER" in risk_types and is_standard_rule:
                score += 5 # 额外加分

            scored_rules.append({'rule': rule, 'score': score})

        # --- 4. 筛选和排序 ---
        top_rules = sorted([r for r in scored_rules], key=lambda x: x['score'], reverse=True)
        
        if not top_rules:
            return "根据患者信息，未筛选到高度匹配的剂量规则。请人工核对所有可用规则。"

        # --- 5. 格式化输出 ---
        # 显示当前处方信息，给LLM一个清晰的对比基准
        current_dose_val = prescription.get('dose_per_admin', {}).get('value')
        current_dose_unit = prescription.get('dose_per_admin', {}).get('unit')
        current_freq_str = prescription.get('frequency', '未知')
        current_route_str = prescription.get('route', '未知')
        
        # header = [
        #     "待审核处方信息:",
        #     f"- 用法: {current_dose_val}{current_dose_unit}, {current_freq_str}, {current_route_str}。",
        #     "\n根据患者情况，筛选出以下最相关的剂量证据（按匹配度排序）："
        # ]
        
        output_lines = []
        for i, scored_rule in enumerate(top_rules[:3]): # 最多取前3条
            rule = scored_rule['rule']
            score = scored_rule['score']
            
            # --- 增强的规则文本构建 ---
            parts = []

            # 单次剂量
            if rule.get('per_dose_min_value') is not None:
                min_dose = rule['per_dose_min_value']
                max_dose = rule.get('per_dose_max_value', min_dose)
                unit = rule.get('per_dose_unit', '')
                if min_dose == max_dose:
                    parts.append(f"{min_dose}{unit}")
                else:
                    parts.append(f"{min_dose}-{max_dose}{unit}")
            
            # 频次
            if rule.get('frequency_value') is not None:
                freq_val = rule['frequency_value']
                # 转换为整数显示，如果它是整数的话
                freq_display = int(freq_val) if freq_val == int(freq_val) else freq_val
                freq_unit = rule.get('frequency_unit', '')
                parts.append(f"{freq_display}{freq_unit}")
                
            # 途径
            if rule.get('route'):
                parts.append(rule['route'])
                
            # 疗程
            if rule.get('duration_min_value') is not None:
                min_dur = rule['duration_min_value']
                max_dur = rule.get('duration_max_value', min_dur)
                unit = rule.get('duration_unit', '')
                if min_dur == max_dur:
                    parts.append(f"疗程{min_dur}{unit}")
                else:
                    parts.append(f"疗程{min_dur}-{max_dur}{unit}")

            usage_text = ", ".join(parts)
            
            # 每日总剂量 (作为补充信息)
            daily_dose_info = ""
            if rule.get('daily_dose_min_value') is not None:
                min_daily = rule['daily_dose_min_value']
                max_daily = rule.get('daily_dose_max_value', min_daily)
                unit = rule.get('daily_dose_unit', '')
                if min_daily == max_daily:
                    daily_dose_info = f"(每日总剂量: {min_daily}{unit})"
                else:
                    daily_dose_info = f"(每日总剂量: {min_daily}-{max_daily}{unit})"
            
            notes = f"({rule.get('notes')})" if rule.get('notes') else ""

            line = (
                f"{i+1}. 推荐用法: {usage_text} {daily_dose_info}。{notes}\n"
                f"   说明书原始内容: “{rule.get('source_text')}”"
            )
            output_lines.append(line)
            
        # return "\n".join(header + output_lines)
        return "\n".join(output_lines)
    

    def _process_indication_evidence(self, task_data: Dict, evidence: Dict) -> str:
        indications = []
        for query, result_list in evidence.items():
            if isinstance(result_list, list):
                indications.extend(result_list)
        
        if not indications:
            return f"知识库中未找到药物 '{task_data['params']['drug_name']}' 的任何适应症信息。"
            
        output_lines = [f"根据知识库，药物 '{task_data['params']['drug_name']}' 的官方批准适应症包括："]
        for item in indications:
            output_lines.append(f"- {item.get('approved_indication', '未知适应症')} (说明书原始内容: {item.get('evidence', '未知')})")
            
        return "\n".join(output_lines)

    def _get_base_drug_name(self, drug_name: str) -> str:
        """
        一个简单的辅助函数，用于从药物全名中提取核心名称。
        例如："利福平胶囊" -> "利福平", "阿司匹林肠溶片" -> "阿司匹林"
        """
        if not isinstance(drug_name, str):
            return ""
        # 可以根据需要扩展这个列表
        suffixes = ["片", "胶囊", "颗粒", "注射液", "口服液", "缓释片", "肠溶片", "缓释胶囊"]
        for suffix in suffixes:
            if drug_name.endswith(suffix):
                return drug_name[:-len(suffix)]
        return drug_name

    def _process_interaction_evidence(self, task_data: Dict, evidence: Dict) -> str:
        """
        (新版) 对相互作用证据进行Python端过滤和格式化。
        采用“宽查询，精过滤”策略。
        """
        all_rules = []
        for query, result_list in evidence.items():
            if isinstance(result_list, list):
                all_rules.extend(result_list)
        
        if not all_rules:
            # 这种情况通常意味着两个药在数据库里都没有作为“引发方”的记录
            return "知识库中未查询到与处方药物相关的相互作用记录。"

        drug1, drug2 = task_data['params']['drug_pair']
        drug1_base = self._get_base_drug_name(drug1)
        drug2_base = self._get_base_drug_name(drug2)

        matched_interactions = []
        for rule in all_rules:
            # 获取规则中的引发方和受影响方信息
            precipitant_base = self._get_base_drug_name(rule['precipitant_drug_name'])
            affected_target_base = self._get_base_drug_name(rule['affected_target_name'])
            
            # 尝试解析受影响方示例列表
            examples = []
            examples_json = rule.get('affected_target_examples')
            if examples_json:
                try:
                    # 数据库返回的可能是JSON字符串
                    examples = json.loads(examples_json) if isinstance(examples_json, str) else examples_json
                except json.JSONDecodeError:
                    logging.warning(f"Failed to parse affected_target_examples: {examples_json}")
            
            # --- 核心匹配逻辑 ---
            # 场景1: drug1是引发方, drug2是受影响方
            if drug1_base in precipitant_base:
                # 检查drug2是否匹配受影响方名称或示例
                if drug2_base in affected_target_base:
                    if rule not in matched_interactions: matched_interactions.append(rule)
                    continue # 匹配成功，继续下一条规则
                for ex in examples:
                    if drug2_base in self._get_base_drug_name(ex):
                        if rule not in matched_interactions: matched_interactions.append(rule)
                        break # 匹配成功

            # 场景2: drug2是引发方, drug1是受影响方
            elif drug2_base in precipitant_base:
                # 检查drug1是否匹配受影响方名称或示例
                if drug1_base in affected_target_base:
                    if rule not in matched_interactions: matched_interactions.append(rule)
                    continue
                for ex in examples:
                    if drug1_base in self._get_base_drug_name(ex):
                        if rule not in matched_interactions: matched_interactions.append(rule)
                        break
        
        # --- 格式化输出 ---
        if not matched_interactions:
            return f"根据知识库筛选，未发现 '{drug1}' 与 '{drug2}' 之间存在明确记录的相互作用。"

        output_lines = [f"查询并筛选到关于 '{drug1}' 与 '{drug2}' 的相互作用信息如下："]
        for i, item in enumerate(matched_interactions):
            line = (
                f"{i+1}. 相互作用记录:\n"
                f"  - 引发方: {item['precipitant_drug_name']}\n"
                f"  - 受影响方: {item['affected_target_name']}\n"
                f"  - 严重等级: {item.get('severity', '未知')}\n"
                f"  - 效应总结: {item.get('effect_summary', '无详细描述')}\n"
                f"  - 临床管理建议: {item.get('clinical_management', '请遵医嘱')}\n"
                f"  - 说明书原始内容：{item.get('source_text', '未知')}"
            )
            output_lines.append(line)
            
        return "\n\n".join(output_lines)
    
    def _process_allergy_evidence(self, task_data: Dict, evidence: Dict) -> str:
        components = []
        rules = []
        for query, result_list in evidence.items():
            if not isinstance(result_list, list): continue
            # 根据查询关键字来区分结果类型
            if "CONTAINS" in query and "Substance" in query:
                components.extend(result_list)
            elif "allergy_rules" in query:
                rules.extend(result_list)
                
        drug_name = task_data['params']['drug_name']
        output_lines = [f"关于药物 '{drug_name}' 的过敏风险信息如下："]
        
        if components:
            # 分离活性成分和辅料
            active_ingredients = [c.get('substance_name') for c in components if c.get('role') == '活性成份']
            excipients = [c.get('substance_name') for c in components if c.get('role') == '辅料']
            
            if active_ingredients:
                output_lines.append(f"1. 活性成分: {', '.join(active_ingredients)}。")
            if excipients:
                output_lines.append(f"2. 辅料包括: {', '.join(excipients)}。")
        else:
            output_lines.append("1. 未查询到该药物的详细成分信息。")
            
        if rules:
            output_lines.append("3. 相关过敏警告/规则:")
            for rule in rules:
                # result_list中的每个元素是{'source_text': '...'}
                output_lines.append(f"   - “{rule.get('source_text', '规则描述缺失')}”")
        else:
            output_lines.append("3. 未查询到与此药物直接相关的特定过敏规则。")
            
        return "\n".join(output_lines)

    def _process_contraindication_evidence(self, task_data: Dict, evidence: Dict) -> str:
        rules = []
        for query, result_list in evidence.items():
            if isinstance(result_list, list):
                rules.extend(result_list)
                
        drug_name = task_data['params']['drug_name']
        
        if not rules:
            # 这是一个重要的信息，明确指出“未发现”
            return f"根据患者提供的现有信息，未在知识库中查询到与药物 '{drug_name}' 相关的特定禁忌症。"
            
        # 按 source_text 去重，因为多个查询可能返回相同的规则
        unique_rules_texts = sorted(list(set(r['source_text'] for r in rules)))
        
        output_lines = [f"警告：根据知识库，药物 '{drug_name}' 存在以下绝对禁忌情况，请务必核对："]
        for text in unique_rules_texts:
            output_lines.append(f"- {text}")
            
        return "\n".join(output_lines)