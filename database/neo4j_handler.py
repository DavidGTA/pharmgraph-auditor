# database/neo4j_handler.py
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, Driver, Transaction

logger = logging.getLogger("MedKG-Extractor")

class Neo4jHandler:
    """
    处理所有与Neo4j数据库交互的类。
    明确区分读写操作，并使用驱动推荐的事务函数。
    """
    _driver: Driver = None

    def __init__(self, db_config: Dict[str, Any]):
        """
        初始化Neo4j处理器并创建驱动实例。

        Args:
            db_config (Dict[str, Any]): 包含数据库连接参数的字典。
        """
        if Neo4jHandler._driver is None:
            try:
                logger.info("Initializing Neo4j driver...")
                uri = db_config['uri']
                user = db_config['user']
                password = db_config['password']
                Neo4jHandler._driver = GraphDatabase.driver(uri, auth=(user, password))
                Neo4jHandler._driver.verify_connectivity()
                logger.info("Neo4j driver initialized and connected successfully.")
            except Exception as e:
                logger.critical(f"Failed to initialize Neo4j driver: {e}", exc_info=True)
                raise

    def execute_read(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行一个只读的Cypher查询，并返回结果。
        这是从数据库检索数据时应使用的方法。

        Args:
            query (str): 要执行的Cypher查询语句 (例如, MATCH ... RETURN ...)。
            parameters (Optional[Dict[str, Any]], optional): 查询的参数。默认为None。

        Returns:
            List[Dict[str, Any]]: 查询结果的列表，每个结果是一个字典。
                                  如果查询失败或没有结果，则返回空列表。
        """
        if parameters is None:
            parameters = {}
        try:
            with self._driver.session() as session:
                logger.debug(f"Executing Cypher read query: {query} with params: {parameters}")
                results = session.execute_read(self._run_read_transaction, query, parameters)
                return results
        except Exception as e:
            logger.error(f"Cypher read query failed: {e}\nQuery: {query}", exc_info=True)
            return []

    @staticmethod
    def _run_read_transaction(tx: Transaction, query: str, parameters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """在事务中运行读查询并处理结果的内部函数。"""
        result = tx.run(query, **parameters)
        return [record.data() for record in result]

    def execute_write(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> None:
        """
        执行一个写操作的Cypher查询（如 CREATE, MERGE, SET, DELETE）。
        此方法不返回任何数据。

        Args:
            query (str): 要执行的Cypher查询语句。
            parameters (Dict[str, Any], optional): 查询参数。
        """
        if parameters is None:
            parameters = {}
        try:
            with self._driver.session() as session:
                logger.debug(f"Executing Cypher write query: {query} with params: {parameters}")
                session.execute_write(self._run_write_transaction, query, parameters)
        except Exception as e:
            logger.error(f"Error executing Neo4j write query: {e}", exc_info=True)
            logger.error(f"Failed Query: {query}")
            logger.error(f"Failed Parameters: {parameters}")
            raise

    @staticmethod
    def _run_write_transaction(tx: Transaction, query: str, parameters: Dict[str, Any]) -> None:
        """在事务中运行写查询的内部函数。"""
        tx.run(query, **parameters)

    def close(self):
        """关闭驱动连接。"""
        if Neo4jHandler._driver:
            Neo4jHandler._driver.close()
            Neo4jHandler._driver = None
            logger.info("Neo4j driver closed.")