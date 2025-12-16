#!/usr/bin/env python
"""Test Document Intelligence on the patent PDF."""
import asyncio
import os
import sys

# Add shared_code to path
sys.path.insert(0, os.path.dirname(__file__))

from shared_code.document_intelligence import extract_with_document_intelligence

async def test():
    pdf_path = '../ui/hil-workflow/US20240416911A1 1.pdf'
    
    with open(pdf_path, 'rb') as f:
        content = f.read()
    
    print(f'Testing PDF: {len(content)} bytes')
    result = await extract_with_document_intelligence(content, 'pdf', 'test.pdf')
    
    if result.get('success'):
        print(f'SUCCESS: {len(result.get("pages", []))} pages extracted')
        print(f'First 300 chars: {result.get("full_text", "")[:300]}')
    else:
        print(f'FAILED: {result.get("error")}')

if __name__ == "__main__":
    asyncio.run(test())
