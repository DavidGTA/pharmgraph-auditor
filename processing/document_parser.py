# processing/document_parser.py

import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("MedKG-Extractor")

class DocumentParser:
    """
    负责解析单个Markdown文档，按章节切分，并根据请求提供合并后的文本。
    该类在实例化时执行一次文件读取和解析，后续调用仅从内存中获取数据。
    """
    
    def __init__(self, file_path: Path):
        """
        初始化解析器并加载、解析文档。

        Args:
            file_path (Path): 要解析的Markdown文件的路径。

        Raises:
            FileNotFoundError: 如果文件不存在。
            Exception: 如果读取文件时发生其他错误。
        """
        self.file_path = file_path
        self._sections: Dict[str, str] = {}
        
        if not self.file_path.is_file():
            raise FileNotFoundError(f"Document not found at: {self.file_path}")
            
        logger.debug(f"Initializing DocumentParser for '{self.file_path.name}'.")
        self._parse()

    def _parse(self):
        """
        私有方法，执行实际的文件读取和章节切分。
        结果缓存到 self._sections 字典中。
        """
        try:
            content = self.file_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read file: {self.file_path}", exc_info=True)
            raise

        parts = re.split(r'(^##\s*【.*?】$)', content, flags=re.MULTILINE)
        
        if len(parts) < 2:
            logger.warning(f"No standard sections (## 【...】) found in '{self.file_path.name}'. Treating entire file as one section.")
            self._sections['__full_content__'] = content.strip()
            return

        for i in range(1, len(parts), 2):
            header = parts[i].strip()
            section_name = header.replace('##', '').strip()
            section_content = (parts[i] + parts[i+1]).strip()
            
            if section_name in self._sections:
                logger.warning(f"Duplicate section name '{section_name}' found in '{self.file_path.name}'. Overwriting with the last one.")
            
            self._sections[section_name] = section_content
        
        logger.info(f"Parsed '{self.file_path.name}' into {len(self._sections)} sections.")
        logger.debug(f"Available sections: {list(self._sections.keys())}")

    def get_combined_text(self, section_names: List[str]) -> Optional[str]:
        """
        根据提供的章节名列表，获取并合并相应的文本块。

        Args:
            section_names (List[str]): 一个包含所需章节名称的列表。
                                       例如: ["【用法用量】"] 或 ["【孕妇...】", "【儿童...】"]

        Returns:
            Optional[str]: 合并后的文本字符串，章节之间用两个换行符分隔。
                           如果没有找到任何一个指定的章节，则返回 None。
        """
        if not section_names:
            logger.warning("get_combined_text called with an empty list of section names.")
            return None
            
        text_parts = []
        for name in section_names:
            if name in self._sections:
                text_parts.append(self._sections[name])
            else:
                logger.debug(f"Section '{name}' requested but not found in '{self.file_path.name}'.")

        if not text_parts:
            logger.warning(f"None of the requested sections {section_names} were found in the document.")
            return None
        
        return "\n\n".join(text_parts)

    def get_all_sections(self) -> Dict[str, str]:
        """
        返回一个包含所有已解析章节的字典副本。

        Returns:
            Dict[str, str]: 章节名到章节内容的映射。
        """
        return self._sections.copy()

    def list_available_sections(self) -> List[str]:
        """
        返回文档中所有可用章节的名称列表。

        Returns:
            List[str]: 章节名称列表。
        """
        return list(self._sections.keys())