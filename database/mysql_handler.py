# database/mysql_handler.py

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import mysql.connector
from mysql.connector import pooling

logger = logging.getLogger("MedKG-Extractor")

class MySQLHandler:
    """
    处理所有与MySQL数据库交互的类。
    使用连接池来管理数据库连接。
    """
    _pool = None

    def __init__(self, db_config: Dict[str, Any]):
        """
        初始化MySQL处理器并创建连接池。

        Args:
            db_config (Dict[str, Any]): 包含数据库连接参数的字典。
        """
        if MySQLHandler._pool is None:
            try:
                logger.info("Initializing MySQL connection pool...")
                MySQLHandler._pool = pooling.MySQLConnectionPool(
                    pool_name="medkg_pool",
                    pool_size=5,
                    host=db_config['host'],
                    port=db_config['port'],
                    user=db_config['user'],
                    password=db_config['password'],
                    database=db_config['database'],
                    auth_plugin='mysql_native_password'
                )
                logger.info("MySQL connection pool initialized successfully.")
            except mysql.connector.Error as err:
                logger.critical(f"Failed to initialize MySQL connection pool: {err}", exc_info=True)
                raise

    def _get_connection(self):
        """从连接池获取一个数据库连接。"""
        try:
            return MySQLHandler._pool.get_connection()
        except mysql.connector.Error as err:
            logger.error(f"Error getting connection from pool: {err}", exc_info=True)
            raise

    def log_llm_extraction(self, log_data: Dict[str, Any]):
        """
        将一次LLM提取的详细信息记录到 llm_extraction_logs 表中。

        Args:
            log_data (Dict[str, Any]): 包含日志信息的字典，键应与表列名对应。
        """
        columns = [
            'source_document_id', 'section_name', 'drug_canonical_name', 'attempt_number',
            'system_prompt', 'user_prompt', 'original_response', 'cleaned_output',
            'is_successful', 'is_valid_json', 'is_pydantic_valid', 'is_selected',
            'error_message', 'pydantic_validation_error', 'model_name',
            'request_timestamp', 'response_timestamp', 'duration_ms',
            'prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_version',
            'reviewed_by', 'reviewed_at', 'notes'
        ]
        
        values = {col: log_data.get(col) for col in columns}

        if values['cleaned_output'] is not None:
            values['cleaned_output'] = json.dumps(values['cleaned_output'], ensure_ascii=False)

        cols_str = ", ".join([f"`{col}`" for col in columns])
        vals_str = ", ".join([f"%({col})s" for col in columns])
        sql = f"INSERT INTO llm_extraction_logs ({cols_str}) VALUES ({vals_str})"

        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()
            logger.debug(f"Successfully logged extraction for '{values['source_document_id']}' - '{values['section_name']}'.")
        except mysql.connector.Error as err:
            logger.error(f"Failed to log LLM extraction to MySQL: {err}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    def find_successful_extraction(self, source_document_id: str, section_name: str) -> Optional[Dict[str, Any]]:
        """
        查找特定文档和章节的最新一次成功提取记录。

        Args:
            source_document_id (str): 源文档ID。
            section_name (str): 章节名称。

        Returns:
            Optional[Dict[str, Any]]: 如果找到，返回包含 'cleaned_output' 的字典，否则返回 None。
        """
        sql = """
            SELECT cleaned_output 
            FROM llm_extraction_logs
            WHERE source_document_id = %s 
              AND section_name = %s
              AND is_successful = TRUE 
              AND is_pydantic_valid = TRUE
              AND is_selected = TRUE
            ORDER BY request_timestamp DESC
            LIMIT 1
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (source_document_id, section_name))
            result = cursor.fetchone()
            if result and result['cleaned_output']:
                logger.info(f"Found existing successful extraction for '{source_document_id}' - '{section_name}'.")
                return result['cleaned_output']
            return None
        except mysql.connector.Error as err:
            logger.error(f"Error finding successful extraction in MySQL: {err}", exc_info=True)
            return None
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        执行一个SQL查询并返回所有结果。

        Args:
            query (str): 要执行的SQL查询语句。

        Returns:
            List[Dict[str, Any]]: 查询结果的列表，每个结果是一个字典。
                                  如果查询失败或没有结果，则返回空列表。
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            logger.debug(f"Executing SQL query: {query}")
            cursor.execute(query)
            results = cursor.fetchall()
            return results
        except mysql.connector.Error as err:
            logger.error(f"SQL query failed: {err}\nQuery: {query}", exc_info=True)
            return []
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                # 将连接放回池中
                conn.close()

    def close_pool(self):
        """关闭连接池。"""
        logger.info("MySQLHandler does not manage pool lifecycle. Pool persists for application lifetime.")