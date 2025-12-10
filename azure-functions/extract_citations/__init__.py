"""
Azure Function: extract_citations
Extract and aggregate citations from workflow outputs.
"""

import azure.functions as func
import json
import logging
import re

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('extract_citations triggered')

    try:
        try:
            req_body = req.get_json()
        except ValueError:
             return func.HttpResponse(
                json.dumps({"error": "Invalid JSON body"}),
                mimetype="application/json",
                status_code=400
            )

        outputs = req_body.get('outputs', [])
        if not isinstance(outputs, list):
             return func.HttpResponse(
                json.dumps({"error": "outputs must be a list"}),
                mimetype="application/json",
                status_code=400
            )

        citations = []
        
        # 1. Look for explicit "citations" list in JSON objects
        for item in outputs:
            if isinstance(item, dict):
                # Check top-level "citations"
                if "citations" in item and isinstance(item["citations"], list):
                    citations.extend(item["citations"])
                
                # Check for RAG-style "documents" or "sources"
                if "documents" in item and isinstance(item["documents"], list):
                    for doc in item["documents"]:
                        if isinstance(doc, dict):
                            # Construct citation from doc metadata
                            if "title" in doc:
                                citations.append(f"{doc['title']} (Score: {doc.get('score', 'N/A')})")
                            elif "id" in doc:
                                citations.append(doc["id"])
        
        # 2. Extract from text if no structured citations found
        # (Simple heuristic regex for [1], [Source: ...])
        if not citations:
            for item in outputs:
                text = ""
                if isinstance(item, str):
                    text = item
                elif isinstance(item, dict):
                    text = str(item) # fallback
                
                # Look for [Source: XYZ] or similar
                matches = re.findall(r'\[Source: ([^\]]+)\]', text)
                citations.extend(matches)
        
        # Remove duplicates
        unique_citations = list(set([str(c) for c in citations]))

        return func.HttpResponse(
            json.dumps({"citations": unique_citations, "count": len(unique_citations)}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error in extract_citations: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
