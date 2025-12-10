from typing import List, Dict, Any, Optional
from agno.tools import Toolkit
from agno.knowledge.reader.reader_factory import ReaderFactory
import json

class DoclingTools(Toolkit):
    def __init__(self):
        super().__init__(name="docling_tools")
        self.register(self.get_document_outline)
        self.register(self.read_document_section)

    def get_document_outline(self, file_path: str) -> str:
        """
        Extracts the outline (headings/structure) of a document.
        Use this to understand the document's structure before reading specific sections.
        
        Args:
            file_path (str): The absolute path to the file.

        Returns:
            str: JSON string representing the document structure (list of headings).
        """
        try:
            # Guard: only use Docling-compatible types
            from pathlib import Path
            ext = Path(file_path).suffix.lower()
            if ext not in [".pdf", ".docx", ".doc", ".pptx", ".md", ".markdown", ".html", ".htm"]:
                return f"Outline not available for {ext} files. This tool supports PDF/DOCX/PPTX/MD/HTML. For CSV/XLSX, use csv_tools.list_columns / csv_tools.sample_rows."

            # Get the DoclingReader (it handles caching internally)
            reader = ReaderFactory.create_reader("docling")
            # We need to access the specific method on DoclingReader, so we cast/assume
            if hasattr(reader, "get_structure"):
                structure = reader.get_structure(file_path)
                return json.dumps(structure, indent=2)
            else:
                return "Error: The configured reader does not support structure extraction."
        except Exception as e:
            return f"Error getting outline: {str(e)}"

    def read_document_section(self, file_path: str, section_title: str) -> str:
        """
        Reads the content of a specific section in the document.
        
        Args:
            file_path (str): The absolute path to the file.
            section_title (str): The exact title of the section to read (from the outline).

        Returns:
            str: The text content of the section.
        """
        try:
            from pathlib import Path
            ext = Path(file_path).suffix.lower()
            if ext not in [".pdf", ".docx", ".doc", ".pptx", ".md", ".markdown", ".html", ".htm"]:
                return f"Section reading not available for {ext} files. This tool supports PDF/DOCX/PPTX/MD/HTML. For CSV/XLSX, read headers or rows directly."

            reader = ReaderFactory.create_reader("docling")
            if hasattr(reader, "read_section"):
                content = reader.read_section(file_path, section_title)
                if not content:
                    return f"No content found for section '{section_title}'. Please check the title from the outline."
                return content
            else:
                return "Error: The configured reader does not support section reading."
        except Exception as e:
            return f"Error reading section: {str(e)}"
