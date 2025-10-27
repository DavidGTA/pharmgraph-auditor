# cov_audit/p3_1_query_executor.py
import logging
from database.mysql_handler import MySQLHandler
from database.neo4j_handler import Neo4jHandler

class QueryExecutor:
    """
    负责执行由QueryGenerator生成的查询计划。
    """
    def __init__(self, mysql_handler: MySQLHandler, neo4j_handler: Neo4jHandler):
        """
        初始化查询执行器。

        Args:
            mysql_handler (MySQLHandler): MySQL数据库处理器实例。
            neo4j_handler (Neo4jHandler): Neo4j数据库处理器实例。
        """
        self.mysql = mysql_handler
        self.neo4j = neo4j_handler
        logging.info("QueryExecutor initialized.")

    def execute_plan(self, query_plan: list) -> dict:
        """
        执行整个查询计划，并按查询语句聚合结果。

        Args:
            query_plan (list): 一个包含查询对象的列表，例如：
                               [{"lang": "sql", "query": "..."}, {"lang": "cypher", "query": "..."}]

        Returns:
            dict: 一个字典，键是原始的查询语句，值是查询结果。
        """
        all_results = {}
        logging.info(f"Executing query plan with {len(query_plan)} queries...")

        for query_item in query_plan:
            lang = query_item.get('lang')
            query = query_item.get('query')

            if not lang or not query:
                logging.warning(f"Skipping invalid query item: {query_item}")
                continue

            # 使用查询语句作为唯一的键，避免重复执行
            if query in all_results:
                continue

            try:
                if lang == 'sql':
                    logging.debug(f"Executing SQL: {query}")
                    result = self.mysql.execute_query(query)
                    all_results[query] = result
                elif lang == 'cypher':
                    logging.debug(f"Executing Cypher: {query}")
                    # 使用 execute_read，因为所有生成的查询都是为了检索数据
                    result = self.neo4j.execute_read(query)
                    all_results[query] = result
                else:
                    logging.warning(f"Unsupported query language '{lang}' for query: {query}")
                    all_results[query] = {"error": f"Unsupported language: {lang}"}
            except Exception as e:
                logging.error(f"Failed to execute query: {query}\nError: {e}", exc_info=True)
                all_results[query] = {"error": str(e)}

        logging.info("Query plan execution completed.")
        return all_results