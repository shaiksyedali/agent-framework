from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI

class ReasoningAgent:
    def __init__(self, model_provider="openai", model_name="gpt-4o"):
        if model_provider == "azure_openai":
            self.model = AzureOpenAI(id=model_name)
        else:
            self.model = OpenAIChat(id=model_name)
            
        self.agent = Agent(
            name="ReasoningEngine",
            role="Logic and Analysis",
            instructions="""
            You are a specialized Reasoning Agent.
            Your goal is to analyze data, perform calculations, and derive logical conclusions.
            
            - Break down complex problems into steps.
            - Use Python code for any math or data processing.
            - Be rigorous and cite your data sources.
            """,
            model=self.model,
            show_tool_calls=True,
            markdown=True,
            # In a real implementation, we'd add PythonTools or similar here
        )

    def run(self, task: str, context: str = "") -> str:
        prompt = f"Context: {context}\n\nTask: {task}"
        response = self.agent.run(prompt)
        return response.content
