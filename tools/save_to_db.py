# tools/save_to_db.py

import argparse
import yaml
import logging
import json
from pathlib import Path
import sys
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from utils.logger import setup_logger
from database.mysql_handler import MySQLHandler
from database.neo4j_handler import Neo4jHandler

setup_logger()
logger = logging.getLogger("MedKG-Extractor.DBSaver")

class DatabaseLoader:
    """
    负责从llm_extraction_logs加载数据并存入最终的MySQL和Neo4j数据库。
    """
    def __init__(self, mysql_handler: MySQLHandler, neo4j_handler: Neo4jHandler):
        self.mysql = mysql_handler
        self.neo4j = neo4j_handler

    def fetch_data_for_drug(self, drug_name: str) -> Dict[str, Any]:
        """从llm_extraction_logs中获取指定药品的所有最新、被选中的记录。"""
        logger.info(f"Fetching latest selected data for drug: '{drug_name}'...")
        
        query = """
            WITH RankedLogs AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER(PARTITION BY section_name ORDER BY request_timestamp DESC) as rn
                FROM llm_extraction_logs
                WHERE drug_canonical_name = %s AND is_selected = TRUE
            )
            SELECT section_name, cleaned_output
            FROM RankedLogs
            WHERE rn = 1;
        """
        conn = None
        cursor = None
        try:
            conn = self.mysql._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (drug_name,))
            results = cursor.fetchall()
            
            if not results:
                logger.warning(f"No selected data found for drug '{drug_name}'. Nothing to load.")
                return {}

            data_map = {}
            for row in results:
                section_name = row['section_name']
                cleaned_output_str = row['cleaned_output']
                
                if cleaned_output_str:
                    try:
                        data_map[section_name] = json.loads(cleaned_output_str)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse JSON for section '{section_name}'. Skipping. Content: {cleaned_output_str[:200]}...")
                else:
                    logger.warning(f"Cleaned output for section '{section_name}' is NULL or empty. Skipping.")
            logger.info(f"Fetched {len(data_map)} records for '{drug_name}'.")
            return data_map
        except Exception as e:
            logger.error(f"Failed to fetch data from llm_extraction_logs: {e}", exc_info=True)
            raise
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    def load_to_databases(self, drug_name: str, data_map: Dict[str, Any]):
        """将数据分发并加载到MySQL和Neo4j。"""
        logger.info(f"Starting data loading process for '{drug_name}'...")
        
        self._load_composition_to_neo4j(drug_name, data_map.get('【成份】'))
        self._load_indication_to_neo4j(drug_name, data_map.get('【适应症】'))
        self._load_interaction_to_neo4j(drug_name, data_map.get('【药物相互作用】'))

        self._clear_existing_data(drug_name)

        self._load_contraindication_to_mysql(drug_name, data_map.get('【禁忌】'))
        self._load_dosage_to_mysql(drug_name, data_map.get('【用法用量】-Dosage'))
        self._load_administration_to_mysql(drug_name, data_map.get('【用法用量】-Administration'))
        self._load_special_populations_to_mysql(drug_name, data_map.get('【特殊人群用药】'))
        self._load_interaction_details_to_mysql(drug_name, data_map.get('【药物相互作用】'))

        logger.info(f"Successfully completed data loading for '{drug_name}'.")

    def _clear_existing_data(self, drug_name: str):
        """在加载新数据前，删除该药品在所有目标表中的旧数据。"""
        logger.warning(f"Clearing existing data for '{drug_name}' from target tables...")
        tables_to_clear = [
            'contraindication_rules', 'allergy_rules', 'dosage_rules', 
            'administration_texts'
        ]
        
        conn = None
        cursor = None
        try:
            conn = self.mysql._get_connection()
            cursor = conn.cursor()
            for table in tables_to_clear:
                cursor.execute(f"DELETE FROM {table} WHERE drug_canonical_name = %s", (drug_name,))
            cursor.execute("DELETE FROM interaction_details WHERE precipitant_drug_name = %s", (drug_name,))
            conn.commit()
            logger.info(f"Cleared data for '{drug_name}'.")
        except Exception as e:
            if conn: conn.rollback()
            logger.error(f"Failed to clear old data for '{drug_name}': {e}", exc_info=True)
            raise
        finally:
             if cursor: cursor.close()
             if conn: conn.close()
    
    def _load_composition_to_neo4j(self, drug_name, data):
        if not data or not data.get('for_graphdb_contains_relation'): return
        logger.info("Loading composition to Neo4j...")
        query = """
            UNWIND $substance_list AS substance
            MERGE (d:Drug {canonical_name: $drug_name})
            MERGE (s:Substance {name: substance.substance_name})
            MERGE (d)-[r:CONTAINS]->(s)
            SET r.role = substance.role,
                r.source_text = substance.source_text,
                s.type = substance.role
        """
        self.neo4j.execute_write(query, {"drug_name": drug_name, "substance_list": data['for_graphdb_contains_relation']})

    def _load_indication_to_neo4j(self, drug_name, data):
        if not data or not data.get('for_graphdb_indicated_for_relation'): return
        logger.info("Loading indications to Neo4j...")
        query = """
            UNWIND $indication_list AS indication
            MERGE (d:Drug {canonical_name: $drug_name})
            MERGE (dis:Disease {name: indication.disease_name})
            MERGE (d)-[r:INDICATED_FOR]->(dis)
            SET r.action = indication.action,
                r.context = indication.context,
                r.source_text = indication.source_text
        """
        self.neo4j.execute_write(query, {"drug_name": drug_name, "indication_list": data['for_graphdb_indicated_for_relation']})

    def _load_interaction_to_neo4j(self, drug_name, data):
        if not data or not data.get('interactions'): return
        logger.info("Loading interactions to Neo4j...")
        query = """
            UNWIND $interaction_list AS interaction
            MERGE (precipitant:Drug {canonical_name: $drug_name})
            MERGE (target:InteractionTarget {name: interaction.affected_target_name})
            MERGE (i:Interaction {interaction_id: interaction.interaction_id})
            SET i.severity = interaction.severity,
                i.effect_summary = interaction.effect_summary,
                i.mechanism = interaction.mechanism
            MERGE (precipitant)-[r1:AS_PRECIPITANT]->(i)
            SET r1.source_text = interaction.source_text
            MERGE (i)-[r2:AFFECTS]->(target)
            SET r2.source_text = interaction.source_text
        """
        self.neo4j.execute_write(query, {"drug_name": drug_name, "interaction_list": data['interactions']})

    def _load_contraindication_to_mysql(self, drug_name, data):
        if not data: return
        conn = self.mysql._get_connection()
        try:
            with conn.cursor() as cursor:
                if data.get('for_contraindication_rules'):
                    logger.info("Loading contraindication rules to MySQL...")
                    rules = data['for_contraindication_rules']
                    for rule in rules:
                        rule['other_conditions'] = json.dumps(rule.get('other_conditions'), ensure_ascii=False) if rule.get('other_conditions') else None
                        cols = ', '.join(f'`{k}`' for k in rule.keys())
                        placeholders = ', '.join(['%s'] * len(rule))
                        sql = f"INSERT INTO contraindication_rules (`drug_canonical_name`, {cols}) VALUES (%s, {placeholders})"
                        cursor.execute(sql, (drug_name, *rule.values()))
                
                if data.get('for_allergy_rules'):
                    logger.info("Loading allergy rules to MySQL...")
                    rules = data['for_allergy_rules']
                    for rule in rules:
                         sql = "INSERT INTO allergy_rules (drug_canonical_name, triggering_substance_name, source_text) VALUES (%s, %s, %s)"
                         cursor.execute(sql, (drug_name, rule['triggering_substance_name'], rule['source_text']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to load contraindications to MySQL: {e}", exc_info=True)
        finally:
            conn.close()

    def _load_dosage_to_mysql(self, drug_name, data):
        if not data or not data.get('for_dosage_rules'): return
        logger.info("Loading dosage rules to MySQL...")
        conn = self.mysql._get_connection()
        try:
            with conn.cursor() as cursor:
                rules = data['for_dosage_rules']
                for rule in rules:
                    flat_rule = {**rule['patient_profile'], **rule['dosage']}
                    flat_rule['other_conditions'] = json.dumps(flat_rule.get('other_conditions'), ensure_ascii=False) if flat_rule.get('other_conditions') else None
                    flat_rule['source_text'] = rule['source_text']
                    
                    cols = ', '.join(f'`{k}`' for k in flat_rule.keys())
                    placeholders = ', '.join(['%s'] * len(flat_rule))
                    sql = f"INSERT INTO dosage_rules (`drug_canonical_name`, {cols}) VALUES (%s, {placeholders})"
                    cursor.execute(sql, (drug_name, *flat_rule.values()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to load dosage rules to MySQL: {e}", exc_info=True)
        finally:
            conn.close()

    def _load_administration_to_mysql(self, drug_name, data):
        if not data or not data.get('for_administration_texts'): return
        logger.info("Loading administration texts to MySQL...")
        conn = self.mysql._get_connection()
        try:
            with conn.cursor() as cursor:
                texts = data['for_administration_texts']
                for text in texts:
                    sql = "INSERT INTO administration_texts (drug_canonical_name, tags, instruction_text, is_complex, llm_summary) VALUES (%s, %s, %s, %s, %s)"
                    cursor.execute(sql, (drug_name, json.dumps(text['tags'], ensure_ascii=False), text['instruction_text'], text['is_complex'], text['llm_summary']))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to load administration texts to MySQL: {e}", exc_info=True)
        finally:
            conn.close()
            
    def _load_special_populations_to_mysql(self, drug_name, data):
        if not data: return
        logger.info("Loading special populations data to MySQL...")
        if data.get('for_contraindication_rules'):
            self._load_contraindication_to_mysql(drug_name, {'for_contraindication_rules': data['for_contraindication_rules']})
        if data.get('for_administration_texts'):
            self._load_administration_to_mysql(drug_name, {'for_administration_texts': data['for_administration_texts']})

    def _load_interaction_details_to_mysql(self, drug_name, data):
        if not data or not data.get('interactions'): return
        logger.info("Loading interaction details to MySQL...")
        conn = self.mysql._get_connection()
        try:
            with conn.cursor() as cursor:
                interactions = data['interactions']
                for interaction in interactions:
                    interaction['precipitant_drug_name'] = drug_name
                    interaction['affected_target_examples'] = json.dumps(interaction.get('affected_target_examples'), ensure_ascii=False) if interaction.get('affected_target_examples') else None
                    
                    cols = ', '.join(f'`{k}`' for k in interaction.keys())
                    placeholders = ', '.join(['%s'] * len(interaction))
                    sql = f"INSERT INTO interaction_details ({cols}) VALUES ({placeholders})"
                    cursor.execute(sql, list(interaction.values()))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to load interaction details to MySQL: {e}", exc_info=True)
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Load extracted data for a specific drug into the final production databases (MySQL & Neo4j)."
    )
    parser.add_argument(
        "drug_name", type=str,
        help="The canonical name of the drug to load."
    )
    parser.add_argument(
        "--settings", type=str, default="configs/settings.yaml",
        help="Path to the system settings configuration file."
    )
    args = parser.parse_args()

    try:
        with open(args.settings, 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        
        mysql_handler = MySQLHandler(settings['mysql'])
        neo4j_handler = Neo4jHandler(settings['neo4j'])
    except Exception as e:
        logger.critical(f"Failed to initialize database handlers: {e}", exc_info=True)
        exit(1)

    loader = DatabaseLoader(mysql_handler, neo4j_handler)
    try:
        data_map = loader.fetch_data_for_drug(args.drug_name)
        if data_map:
            loader.load_to_databases(args.drug_name, data_map)
    finally:
        neo4j_handler.close()


if __name__ == "__main__":
    main()