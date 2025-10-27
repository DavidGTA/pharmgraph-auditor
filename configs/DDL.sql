create table administration_texts
(
    id                  bigint auto_increment
        primary key,
    drug_canonical_name varchar(255)                         not null comment '药物规范名称',
    tags                json                                 not null comment '用于快速筛选的上下文标签',
    instruction_text    text                                 not null comment '完整的原文片段',
    is_complex          tinyint(1) default 0                 not null comment '是否为复杂逻辑',
    llm_summary         text                                 null comment 'LLM生成的摘要',
    created_at          timestamp  default CURRENT_TIMESTAMP null
)
    comment '存储所有带标签的用法用量原文';

create index idx_drug_name_admin_texts
    on administration_texts (drug_canonical_name);

create table allergy_rules
(
    id                        bigint auto_increment
        primary key,
    drug_canonical_name       varchar(255)                        not null comment '药物规范名称',
    triggering_substance_name varchar(255)                        not null comment '引发过敏的物质名称',
    source_text               text                                not null comment '原始文本',
    created_at                timestamp default CURRENT_TIMESTAMP null,
    constraint uk_drug_substance
        unique (drug_canonical_name, triggering_substance_name)
)
    comment '存储因特定物质过敏导致的禁忌';

create index idx_substance_name
    on allergy_rules (triggering_substance_name);

create table contraindication_rules
(
    id                  bigint auto_increment
        primary key,
    drug_canonical_name varchar(255)                          not null comment '药物规范名称',
    age_min_years       decimal(5, 2)                         null comment '最小年龄（岁）',
    age_max_years       decimal(5, 2)                         null comment '最大年龄（岁）',
    weight_min_kg       decimal(5, 2)                         null comment '最小体重（kg）',
    weight_max_kg       decimal(5, 2)                         null comment '最大体重（kg）',
    sex                 enum ('男', '女')                     null comment '性别',
    renal_impairment    enum ('轻度', '中度', '重度', '衰竭') null comment '肾功能损害程度',
    hepatic_impairment  enum ('轻度', '中度', '重度', '衰竭') null comment '肝功能损害程度',
    pregnancy_status    enum ('未妊娠', '妊娠')               null comment '妊娠状态',
    lactation_status    enum ('非哺乳期', '哺乳期')           null comment '哺乳状态',
    other_conditions    json                                  null comment '其他医疗状况 (JSON数组)',
    source_text         text                                  not null comment '原始文本',
    created_at          timestamp default CURRENT_TIMESTAMP   null
)
    comment '存储结构化的禁忌规则';

create index idx_age
    on contraindication_rules (age_min_years, age_max_years);

create index idx_drug_name
    on contraindication_rules (drug_canonical_name);

create index idx_hepatic
    on contraindication_rules (hepatic_impairment);

create index idx_renal
    on contraindication_rules (renal_impairment);

create table dosage_rules
(
    id                   bigint auto_increment
        primary key,
    drug_canonical_name  varchar(255)                          not null comment '药物规范名称',
    age_min_years        decimal(5, 2)                         null,
    age_max_years        decimal(5, 2)                         null,
    weight_min_kg        decimal(5, 2)                         null,
    weight_max_kg        decimal(5, 2)                         null,
    sex                  enum ('男', '女')                     null,
    renal_impairment     enum ('轻度', '中度', '重度', '衰竭') null,
    hepatic_impairment   enum ('轻度', '中度', '重度', '衰竭') null,
    pregnancy_status     enum ('未妊娠', '妊娠')               null,
    lactation_status     enum ('非哺乳期', '哺乳期')           null,
    other_conditions     json                                  null,
    per_dose_min_value   decimal(10, 4)                        null,
    per_dose_max_value   decimal(10, 4)                        null,
    per_dose_unit        varchar(50)                           null,
    daily_dose_min_value decimal(10, 4)                        null,
    daily_dose_max_value decimal(10, 4)                        null,
    daily_dose_unit      varchar(50)                           null,
    frequency_value      decimal(5, 2)                         null,
    frequency_unit       varchar(50)                           null,
    route                varchar(100)                          null,
    duration_min_value   decimal(5, 2)                         null,
    duration_max_value   decimal(5, 2)                         null,
    duration_unit        varchar(50)                           null,
    notes                text                                  null,
    source_text          text                                  not null,
    created_at           timestamp default CURRENT_TIMESTAMP   null
)
    comment '存储可自动检查的常规剂量规则';

create index idx_drug_name_dosage
    on dosage_rules (drug_canonical_name);

create table interaction_details
(
    interaction_id           varchar(255)                        not null comment '对应Neo4j中的Interaction节点ID'
        primary key,
    precipitant_drug_name    varchar(255)                        not null comment '引发方药物',
    affected_target_name     varchar(255)                        not null comment '受影响方名称',
    affected_target_examples json                                null comment '受影响方具体示例',
    severity                 enum ('严重', '中度', '轻度')       not null comment '临床严重性',
    effect_summary           text                                not null comment '效应总结',
    mechanism                text                                null comment '作用机制',
    clinical_management      text                                null comment '临床管理建议',
    source_text              text                                not null comment '原始文本',
    created_at               timestamp default CURRENT_TIMESTAMP null
)
    comment '存储药物相互作用的详细信息';

create index idx_affected_target
    on interaction_details (affected_target_name);

create index idx_precipitant_drug
    on interaction_details (precipitant_drug_name);

create table llm_extraction_logs
(
    VARIABLE_NAME             varchar(64)               not null,
    id                        bigint auto_increment comment '日志的唯一主键'
        primary key
        primary key,
    VARIABLE_VALUE            varchar(1024)             null,
    source_document_id        varchar(255)              not null comment '源文档的唯一标识符 (例如, 文件名)',
    section_name              varchar(100)              not null comment '处理的说明书章节名 (例如, 【用法用量】)',
    drug_canonical_name       varchar(255)              null comment '如果适用，提取出的药物规范名称',
    attempt_number            int         default 1     not null comment '针对此文档此章节的尝试次数',
    system_prompt             text                      not null comment '发送给LLM的系统提示',
    user_prompt               mediumtext                not null comment '发送给LLM的用户提示 (可能很长)',
    original_response         mediumtext                null comment 'LLM返回的原始、未经处理的响应字符串',
    cleaned_output            json                      null comment '经过验证和清洗后，准备加载到数据库的JSON数据',
    is_successful             tinyint(1)  default 0     not null comment 'API调用是否成功返回200 OK',
    is_valid_json             tinyint(1)                null comment 'Original Response是否为有效的JSON格式',
    is_pydantic_valid         tinyint(1)                null comment 'Cleaned Output是否通过Pydantic模型验证',
    is_selected               tinyint(1)  default 0     not null comment '此条记录的Cleaned Output是否被最终选用并加载到知识库',
    error_message             text                      null comment '记录API调用失败或系统处理过程中的异常信息',
    pydantic_validation_error text                      null comment '如果Pydantic验证失败，记录详细的错误信息',
    model_name                varchar(100)              not null comment '使用的LLM模型名称',
    request_timestamp         datetime(3)               not null comment '请求发送时间',
    response_timestamp        datetime(3)               null comment '收到响应时间',
    duration_ms               int                       null comment '请求耗时（毫秒）',
    prompt_tokens             int                       null comment '输入的Token数',
    completion_tokens         int                       null comment '输出的Token数',
    total_tokens              int                       null comment '总Token数',
    prompt_version            varchar(20) default '1.0' not null comment '使用的Prompt模板版本号',
    reviewed_by               varchar(100)              null comment '人工审核员的ID',
    reviewed_at               timestamp                 null comment '人工审核的时间',
    notes                     text                      null comment '人工审核的备注'
)
    comment '记录每一次LLM提取任务的详细日志，用于审计、调试和模型迭代';

create unique index `PRIMARY`
    on llm_extraction_logs (VARIABLE_NAME)
    using hash;

create index idx_model_version
    on llm_extraction_logs (model_name, prompt_version);

create index idx_section_name
    on llm_extraction_logs (section_name);

create index idx_source_document
    on llm_extraction_logs (source_document_id);

create index idx_status
    on llm_extraction_logs (is_successful, is_valid_json, is_pydantic_valid, is_selected);

