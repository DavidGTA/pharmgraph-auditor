# core/models.py

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

# --- 通用子模型 ---

class PatientProfile(BaseModel):
    age_min_years: Optional[float] = Field(default=None, description="最小年龄（单位：岁）")
    age_max_years: Optional[float] = Field(default=None, description="最大年龄（单位：岁）")
    weight_min_kg: Optional[float] = Field(default=None, description="最小体重（单位：kg）")
    weight_max_kg: Optional[float] = Field(default=None, description="最大体重（单位：kg）")
    sex: Optional[Literal['男', '女']] = Field(default=None, description="性别")
    renal_impairment: Optional[Literal['轻度', '中度', '重度', '衰竭']] = Field(default=None, description="肾功能损害程度")
    hepatic_impairment: Optional[Literal['轻度', '中度', '重度', '衰竭']] = Field(default=None, description="肝功能损害程度")
    pregnancy_status: Optional[Literal['未妊娠', '妊娠']] = Field(default=None, description="妊娠状态")
    lactation_status: Optional[Literal['非哺乳期', '哺乳期']] = Field(default=None, description="哺乳状态")
    other_conditions: Optional[List[str]] = Field(default=None, description="其他不适合映射到特定字段的医疗状况")

class AdministrationText(BaseModel):
    tags: List[str] = Field(..., description="标签数组")
    instruction_text: str = Field(..., description="完整的原始文本片段")
    is_complex: bool = Field(..., description="是否为复杂逻辑")
    llm_summary: str = Field(..., description="文本片段的一句话摘要")

# --- 各章节的主Payload模型 ---

class DrugMetadata(BaseModel):
    canonical_name: str
    generic_name: str
    brand_names: Optional[List[str]] = None
    english_name: Optional[str] = None

class SubstanceInfo(BaseModel):
    substance_name: str = Field(..., description="物质的清洗后规范名称")
    role: Literal['活性成份', '辅料'] = Field(..., description="物质角色")
    source_text: str = Field(..., description="原始文本/句子")

class DescriptionPayload(BaseModel):
    for_graphdb_contains_relation: List[SubstanceInfo]

class IndicationInfo(BaseModel):
    disease_name: str = Field(..., description="核心疾病或医疗状况的名称")
    action: Literal['治疗', '预防', '管理'] = Field(..., description="治疗行为")
    context: Optional[str] = Field(default=None, description="具体的患者亚群或治疗情景描述")
    source_text: str = Field(..., description="原始文本/句子")

class IndicationPayload(BaseModel):
    for_graphdb_indicated_for_relation: List[IndicationInfo]

class ContraindicationRule(PatientProfile):
    source_text: str = Field(..., description="原始文本")

class AllergyRule(BaseModel):
    triggering_substance_name: str = Field(..., description="引发过敏的物质名称")
    source_text: str = Field(..., description="原始文本")

class ContraindicationPayload(BaseModel):
    for_contraindication_rules: List[ContraindicationRule]
    for_allergy_rules: List[AllergyRule]

class Dosage(BaseModel):
    per_dose_min_value: Optional[float] = None
    per_dose_max_value: Optional[float] = None
    per_dose_unit: Optional[str] = None
    daily_dose_min_value: Optional[float] = None
    daily_dose_max_value: Optional[float] = None
    daily_dose_unit: Optional[str] = None
    frequency_value: Optional[float] = None
    frequency_unit: Optional[str] = None
    route: Optional[str] = None
    duration_min_value: Optional[float] = None
    duration_max_value: Optional[float] = None
    duration_unit: Optional[str] = None
    notes: Optional[str] = None

class DosageRule(BaseModel):
    patient_profile: PatientProfile
    dosage: Dosage
    source_text: str

class DosagePayload(BaseModel):
    """用于验证仅提取剂量规则的LLM调用的模型"""
    for_dosage_rules: List[DosageRule]

class AdministrationPayload(BaseModel):
    """用于验证仅提取用法说明的LLM调用的模型"""
    for_administration_texts: List[AdministrationText]
    
class DosageAdminPayload(BaseModel):
    """最终合并【用法用量】所有信息的模型"""
    for_dosage_rules: List[DosageRule]
    for_administration_texts: List[AdministrationText]
    
class SpecialPopulationsPayload(BaseModel):
    for_contraindication_rules: List[ContraindicationRule]
    for_administration_texts: List[AdministrationText]

class InteractionInfo(BaseModel):
    interaction_id: str
    affected_target_name: str
    affected_target_examples: Optional[List[str]] = None
    severity: Literal['严重', '中度', '轻度']
    effect_summary: str
    mechanism: Optional[str] = None
    clinical_management: str
    source_text: str

class InteractionPayload(BaseModel):
    interactions: List[InteractionInfo]


# --- 用于映射的模型字典 ---
# The single source of truth for mapping sections to their validation models
SECTION_MODEL_MAP: Dict[str, Any] = {
    "【药品名称】": DrugMetadata,
    "【成份】": DescriptionPayload,
    "【适应症】": IndicationPayload,
    "【禁忌】": ContraindicationPayload,
    "【用法用量】": DosageAdminPayload,
    "【特殊人群用药】": SpecialPopulationsPayload,
    "【药物相互作用】": InteractionPayload,
}