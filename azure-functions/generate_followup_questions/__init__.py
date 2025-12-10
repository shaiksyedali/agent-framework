"""
Azure Function: generate_followup_questions
Generate relevant follow-up questions based on context using Azure OpenAI.
"""

import azure.functions as func
import json
import logging
import os


async def main(req: func.HttpRequest) -> func.HttpResponse:
    # Add vendored packages to path
    import sys
    import os
    site_packages = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.python_packages', 'lib', 'site-packages')
    if site_packages not in sys.path:
        sys.path.append(site_packages)

    logging.info('generate_followup_questions triggered')

    try:
        from openai import AsyncAzureOpenAI

        try:
            req_body = req.get_json()
        except ValueError:
             return func.HttpResponse(
                json.dumps({"error": "Invalid JSON body"}),
                mimetype="application/json",
                status_code=400
            )

        context = req_body.get('context')
        if not context:
            return func.HttpResponse(
                json.dumps({"error": "context is required"}),
                mimetype="application/json",
                status_code=400
            )
            
        count = req_body.get('count', 3)

        # Initialize Azure OpenAI Client
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o"
        
        if not api_key or not endpoint:
             return func.HttpResponse(
                json.dumps({"error": "Azure OpenAI configuration missing (API Key/Endpoint)"}),
                mimetype="application/json",
                status_code=500
            )

        client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            azure_endpoint=endpoint
        )

        # Construct prompt
        # We assume context is a dict or string
        context_str = json.dumps(context) if isinstance(context, dict) else str(context)
        
        prompt = f"""Based on the following context, generate {count} relevant follow-up questions that a user might ask next.
        
Context:
{context_str[:2000]} # Truncate to avoid token limits

Output only the questions as a JSON list of strings. Example: ["Question 1?", "Question 2?"]
"""

        response = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates follow-up questions."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )

        content = response.choices[0].message.content
        questions = json.loads(content)
        
        # Handle if "questions" key is used by model instead of raw list
        if isinstance(questions, dict):
            # Look for common keys
            for key in ["questions", "follow_up_questions", "result"]:
                if key in questions and isinstance(questions[key], list):
                    questions = questions[key]
                    break
        
        if not isinstance(questions, list):
             questions = [] # Fallback

        return func.HttpResponse(
            json.dumps({"questions": questions}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        import traceback
        logging.error(f"Error in generate_followup_questions: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc()
            }),
            mimetype="application/json",
            status_code=500
        )
