from typing import Dict, Any
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI
from pydantic import BaseModel, Field

class VisualizationData(BaseModel):
    type: str = Field(..., description="Type of chart: bar, line, pie, table")
    title: str
    data: Dict[str, Any]

class FinalResponse(BaseModel):
    summary: str
    visualizations: list[VisualizationData] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

class ResponseAgent:
    def __init__(self, model_provider="openai", model_name="gpt-4o"):
        if model_provider == "azure_openai":
            self.model = AzureOpenAI(id=model_name)
        else:
            self.model = OpenAIChat(id=model_name)
            
        self.agent = Agent(
            name="ResponseGenerator",
            role="Content Formatter",
            instructions="""
            You are a specialized Response Generation Agent.
            Your goal is to format the final output for the user.
            
            - Synthesize all previous steps into a clear summary.
            - Generate structured data for visualizations if applicable.
            - Suggest next steps.
            """,
            model=self.model,
            output_schema=FinalResponse,
            markdown=True,
        )

    def generate_response(self, workflow_context: Dict[str, Any]) -> FinalResponse:
        prompt = f"Generate final response based on this context: {workflow_context}"
        response = self.agent.run(prompt)
        return response.content
