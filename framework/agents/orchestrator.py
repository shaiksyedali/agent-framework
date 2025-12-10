import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from ..schema import WorkflowConfig, JobStatus, UserConfirmationStep
from ..registry import WorkflowRegistry
from ..builder import WorkflowBuilder

import warnings
warnings.filterwarnings("ignore", message="The api_key client option must be set")

class Orchestrator:
    def __init__(self, registry: WorkflowRegistry):
        self.registry = registry
        self.builder = WorkflowBuilder(registry)

    def start_workflow(self, workflow_id: str, input_data: Dict[str, Any], hil_mode: bool = True) -> JobStatus:
        workflow_config = self.registry.get_workflow(workflow_id)
        if not workflow_config:
            raise ValueError(f"Workflow {workflow_id} not found")

        job = JobStatus(
            workflow_id=workflow_id,
            status="running",
            context=input_data,
            logs=["Workflow started"],
            hil_mode=hil_mode
        )
        self.registry.save_job(job)
        
        # Start execution (in a real system, this would be a background task)
        self._execute_job(job, workflow_config)
        return job

    def resume_workflow(self, job_id: str, user_input: str) -> JobStatus:
        print(f"DEBUG: resume_workflow called for {job_id} with input: '{user_input}'")
        job = self.registry.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        print(f"DEBUG: Job loaded. Index: {job.current_step_index}, Status: {job.status}")

        if job.status != "waiting_for_user":
            raise ValueError(f"Job {job_id} is not waiting for user input")

        workflow_config = self.registry.get_workflow(job.workflow_id)
        
        # Check if we are resuming a specific UserConfirmationStep
        # Note: We need to check the step type at the current index
        current_step = None
        if job.current_step_index < len(workflow_config.steps):
            current_step = workflow_config.steps[job.current_step_index]

        if isinstance(current_step, UserConfirmationStep):
             job.context[f"{current_step.name}_response"] = user_input
             job.logs.append(f"User provided input for {current_step.name}")
             job.current_step_index += 1
        else:
            # Generic HIL Resume Logic
            # Treat whitespace-only input as empty (Proceed)
            cleaned_input = user_input.strip() if user_input else ""
            
            if cleaned_input:
                # User provided feedback -> RETRY current step
                print(f"DEBUG: User provided feedback: '{cleaned_input}'. Retrying current step (Index {job.current_step_index}).")
                job.logs.append(f"User Feedback: {cleaned_input}")
                if "user_feedback_history" not in job.context:
                    job.context["user_feedback_history"] = []
                job.context["user_feedback_history"].append({
                    "step_index": job.current_step_index,
                    "feedback": cleaned_input,
                    "timestamp": datetime.now().isoformat()
                })
                # Do NOT increment step index. The step will be re-executed.
            else:
                # User provided empty input -> PROCEED to next step
                
                # Safety Check: If the agent asked a question, we CANNOT proceed with empty input.
                last_log = job.logs[-1] if job.logs else ""
                if "Agent requested feedback:" in last_log:
                    raise ValueError("Agent asked a question. You must provide feedback/answer to proceed.")

                print(f"DEBUG: User provided empty input. Proceeding to next step (Index {job.current_step_index} -> {job.current_step_index + 1}).")
                job.logs.append("User approved step. Proceeding.")
                job.current_step_index += 1
        
        # Resume execution
        job.status = "running"
        self.registry.save_job(job)
        print(f"DEBUG: Calling _execute_job with Index: {job.current_step_index}")
        self._execute_job(job, workflow_config)
        print(f"DEBUG: _execute_job returned. Final Index: {job.current_step_index}")
        return job

    def _execute_job(self, job: JobStatus, config: WorkflowConfig):
        try:
            # Build the runnable workflow (Agno object)
            # Note: We are rebuilding it every time. In a stateful system, we might cache it.
            # But since we are handling steps manually here to support HIL, we use the Builder mainly for Agents.
            
            # 1. Build Agents
            # We need to instantiate agents to call them.
            # Optimization: Only build agents needed for the remaining steps? 
            # For now, build all.
            agno_workflow = self.builder.build_workflow(config)
            agents = agno_workflow.agents
            
            # Import StepOutput for structured parsing
            from ..schema import StepOutput
            import re
            
            while job.current_step_index < len(config.steps):
                step = config.steps[job.current_step_index]
                
                if isinstance(step, UserConfirmationStep):
                    job.status = "waiting_for_user"
                    job.logs.append(f"Waiting for user confirmation: {step.message}")
                    self.registry.save_job(job)
                    return # Stop execution and wait for resume

                elif step.type == "agent_call":
                    # Rebuild agent for each step to ensure fresh context/memory
                    # Find the agent config
                    agent_config = next((a for a in (config.agents or []) if a.id == step.agent_id), None)
                    
                    if agent_config:
                        # Build the agent just-in-time
                        # We need data_sources which was built earlier
                        # Extract data_sources from config again (or pass it)
                        data_sources = {ds.id: ds for ds in (config.data_sources or [])}
                        agent = self.builder.build_agent(agent_config, data_sources)
                        
                        job.logs.append(f"Executing step {step.name} with agent {agent.name}")
                        # Format prompt
                        prompt = step.input_template.format(**job.context)
                        
                        # Inject User Feedback History
                        if "user_feedback_history" in job.context and job.context["user_feedback_history"]:
                            history_text = "\n".join([f"- {item['feedback']}" for item in job.context["user_feedback_history"]])
                            prompt += f"\n\n[USER FEEDBACK HISTORY]:\n{history_text}"

                        print(f"--- Executing Step: {step.name} ---")
                        print(f"Agent: {agent.name} (Role: {agent.role})")
                        print(f"Prompt: {prompt}")
                        
                        try:
                            # Use structured output parsing
                            response = agent.run(prompt, response_model=StepOutput)

                            # Handle Structured Response using Helper
                            step_output = self._parse_step_output(response)
                            step_output = self._sanitize_visualizations(step_output)

                            # Extract diagnostic metrics if present in content (e.g., from SQL strategy)
                            diag_match = None
                            if isinstance(step_output.content, str):
                                diag_match = re.search(r"\[Diagnostics:\s*(.*?)\]", step_output.content)
                            if diag_match:
                                raw_diag = diag_match.group(1)
                                metrics_pairs = [p.strip() for p in raw_diag.split(",")]
                                for pair in metrics_pairs:
                                    if "=" in pair:
                                        k, v = pair.split("=", 1)
                                        k = k.strip()
                                        v = v.strip()
                                        # store as string; parsing can be done client-side if needed
                                        step_output.metrics[k] = v

                            # If the agent returned a QUESTION, mark status so UI can prompt
                            if isinstance(step_output.content, str) and step_output.content.strip().startswith("QUESTION:"):
                                job.status = "waiting_for_user"
                                job.logs.append(step_output.content.strip())
                                self.registry.save_job(job)
                                return

                            # Store main content
                            job.context[step.output_key] = step_output.content
                            
                            # Store rich outputs (metrics, visualizations, insights)
                            if "step_outputs" not in job.context:
                                job.context["step_outputs"] = {}
                            
                            job.context["step_outputs"][step.name] = step_output.model_dump()
                            
                            # Log summary
                            log_msg = f"Step {step.name} completed."
                            if step_output.metrics:
                                log_msg += f" Metrics: {step_output.metrics}"
                            job.logs.append(log_msg)

                            print(f"DEBUG: Step {step.name} output: {step_output.content[:200]}...")
                            if step_output.visualizations:
                                print(f"DEBUG: Generated {len(step_output.visualizations)} visualizations")
                                # Surface visualizations to the shared job context for the UI tab
                                if "visualizations" not in job.context or not isinstance(job.context.get("visualizations"), list):
                                    job.context["visualizations"] = []
                                job.context["visualizations"].extend(step_output.visualizations)

                            # Expose flattened context for downstream templates
                            job.context["last_step_output"] = step_output.content
                            job.context["last_step_metrics"] = step_output.metrics

                        except Exception as agent_err:
                            print(f"Agent execution failed: {agent_err}")
                            # Fallback for agents that might fail structured output?
                            # For now, we assume strict adherence as per instructions.
                            raise agent_err
                        
                        # Check for Agent Question (HITL Request) - Logic might need adjustment for StepOutput
                        # If the agent wants to ask a question, it should probably be in 'content' or a specific field.
                        # For now, check 'content'.
                        if "QUESTION:" in step_output.content:
                            job.status = "waiting_for_user"
                            job.logs.append(f"Agent requested feedback: {step_output.content}")
                            # We do NOT increment step index, so it retries on resume
                            self.registry.save_job(job)
                            return

                    else:
                        job.logs.append(f"Error: Agent {step.agent_id} not found")

                elif step.type == "team_call":
                    # Find the team config
                    team_config = next((t for t in (config.teams or []) if t.id == step.team_id), None)
                    
                    if team_config:
                        # Build agents first (needed for team)
                        data_sources = {ds.id: ds for ds in (config.data_sources or [])}
                        agents = {}
                        for agent_config in (config.agents or []):
                            agents[agent_config.id] = self.builder.build_agent(agent_config, data_sources)
                            
                        # Build the team
                        team = self.builder.build_team(team_config, agents)
                        
                        job.logs.append(f"Executing step {step.name} with team {team.name}")
                        # Format prompt
                        prompt = step.input_template.format(**job.context)
                        
                        # Inject User Feedback History
                        if "user_feedback_history" in job.context and job.context["user_feedback_history"]:
                            history_text = "\n".join([f"- {item['feedback']}" for item in job.context["user_feedback_history"]])
                            prompt += f"\n\n[USER FEEDBACK HISTORY]:\n{history_text}"

                        print(f"--- Executing Step: {step.name} ---")
                        print(f"Team: {team.name}")
                        print(f"Prompt: {prompt}")
                        
                        try:
                            # Team run might not support response_model directly if it's a multi-agent chat.
                            # We might need to wrap it or instruct the final agent.
                            # For now, let's assume Team.run returns a standard response and we try to parse it manually if needed,
                            # OR we force the team leader to output JSON.
                            # Let's try response_model on team.run if supported, otherwise fallback.
                            # Agno Team.run usually returns a RunResponse.
                            
                            # TODO: Check if Team supports response_model. 
                            # If not, we might need to rely on the prompt instructions and manual parsing.
                            # For safety, let's use the standard run and try to parse JSON if it looks like it,
                            # or just treat as text.
                            
                            response = team.run(prompt)
                            
                            # Try to parse as StepOutput if possible
                            content = response.content
                            # ... (Parsing logic would go here, but for now let's treat Team output as raw content)
                            # To be robust, we should probably update Team to support structured output or wrap it.
                            # For this iteration, we'll keep Team output as simple text to avoid breaking it,
                            # but we can wrap it in a pseudo-StepOutput for the UI.
                            
                            step_output = StepOutput(
                                thought_process="Team Execution",
                                content=str(content),
                                metrics={},
                                visualizations=[]
                            )
                            step_output = self._sanitize_visualizations(step_output)
                            
                        except Exception as team_err:
                            print(f"Team execution failed: {team_err}")
                            raise team_err
                        
                        # Store result
                        job.context[step.output_key] = step_output.content
                        
                        if "step_outputs" not in job.context:
                            job.context["step_outputs"] = {}
                        job.context["step_outputs"][step.name] = step_output.model_dump()

                        # Expose flattened context for downstream templates
                        job.context["last_step_output"] = step_output.content
                        job.context["last_step_metrics"] = step_output.metrics

                        # Mirror visualizations from team outputs as well
                        if step_output.visualizations:
                            if "visualizations" not in job.context or not isinstance(job.context.get("visualizations"), list):
                                job.context["visualizations"] = []
                            job.context["visualizations"].extend(step_output.visualizations)

                        job.logs.append(f"Step {step.name} completed. Output length: {len(str(step_output.content))}")
                        print(f"DEBUG: Step {step.name} output: {str(step_output.content)[:200]}...")
                    else:
                        job.logs.append(f"Error: Team {step.team_id} not found")

                elif step.type == "tool_call":
                    # HACK: Handle "Visualize Results" specifically since we don't have a generic tool runner yet
                    if "Visualize" in step.name:
                        job.logs.append(f"Executing visualization step: {step.name}")
                        print(f"--- Executing Step: {step.name} ---")
                        
                        # Create a temporary agent for visualization
                        from ..schema import AgentConfig
                        import json
                        import re
                        
                        import os
                        model_provider = "openai"
                        model_name = "gpt-4o"
                        
                        if os.getenv("AZURE_OPENAI_API_KEY"):
                            model_provider = "azure_openai"
                            model_name = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

                        viz_agent_config = AgentConfig(
                            name="Visualizer",
                            role="Data Visualization Expert",
                            model_provider=model_provider,
                            model_name=model_name,
                            instructions="""
                            You are an expert at creating visualizations from data.
                            Your goal is to analyze the provided context and generate a JSON object for charts.
                            
                            Output Format:
                            Provide a JSON array of visualization objects.
                            Schema:
                            [
                                {
                                    "title": "Chart Title",
                                    "type": "bar", // or "pie"
                                    "data": [ {"name": "Category", "value": 10}, ... ]
                                }
                            ]
                            
                            IMPORTANT: Return ONLY the JSON. Do not include markdown formatting like ```json ... ```.
                            """,
                        )
                        
                        # Build the agent
                        viz_agent = self.builder.build_agent(viz_agent_config, {})
                        
                        # Prepare prompt with context
                        prompt = f"Context: {job.context}\n\nGenerate visualizations based on the data above."
                        
                        try:
                            response = viz_agent.run(prompt)
                            content = response.content
                            
                            # Clean up markdown code blocks if present
                            if "```json" in content:
                                content = content.split("```json")[1].split("```")[0].strip()
                            elif "```" in content:
                                content = content.split("```")[1].split("```")[0].strip()
                                
                            visualizations = json.loads(content)
                            
                            # Store in context
                            if "visualizations" not in job.context:
                                job.context["visualizations"] = []
                            
                            # Merge or append? The UI expects an array.
                            # If we want to accumulate, we extend.
                            if isinstance(visualizations, list):
                                job.context["visualizations"].extend(visualizations)
                            else:
                                job.context["visualizations"].append(visualizations)
                                
                            job.logs.append(f"Visualization generated: {len(visualizations)} charts")
                            print(f"DEBUG: Generated {len(visualizations)} visualizations")
                            
                        except Exception as e:
                            print(f"Visualization failed: {e}")
                            job.logs.append(f"Visualization failed: {str(e)}")
                    else:
                        job.logs.append(f"Skipping unimplemented tool call: {step.name}")
                
                # HIL Check: Pause after every step if enabled
                print(f"DEBUG: HIL Check - Step: {step.name}, Index: {job.current_step_index}, HIL Mode: {job.hil_mode}")
                if job.hil_mode:
                    job.status = "waiting_for_user"
                    job.logs.append(f"Step {step.name} completed. Pausing for review.")
                    self.registry.save_job(job)
                    print(f"DEBUG: Pausing. Saved job with Index: {job.current_step_index}")
                    return

                # Move to next step
                job.current_step_index += 1
                self.registry.save_job(job)
                print(f"DEBUG: Moving to next step. New Index: {job.current_step_index}")

            # If loop finishes, job is complete
            job.status = "completed"
            job.logs.append("Workflow completed successfully")
            self.registry.save_job(job)

        except Exception as e:
            job.status = "failed"
            job.logs.append(f"Execution failed: {str(e)}")
            self.registry.save_job(job)

    def _parse_step_output(self, response: Any) -> Any:
        # Import StepOutput locally to avoid circular imports if any
        from ..schema import StepOutput
        import json
        import re

        # 1. Handle if already StepOutput
        if isinstance(response, StepOutput):
            return response

        # 2. Extract content from RunResponse or other objects
        content_to_parse = response
        if hasattr(response, "content"):
            content_to_parse = response.content
        
        # If it's not a string (and not StepOutput), wrap it
        if not isinstance(content_to_parse, str):
            return StepOutput(
                thought_process="Unknown Output Type",
                content=str(content_to_parse),
                metrics={},
                visualizations=[],
                insights=[]
            )

        # 3. Parsing Pipeline for String Content
        raw_text = content_to_parse.strip()
        
        # A. Try to extract JSON from Code Blocks
        code_block_pattern = r"```(?:\w+)?\s+(.*?)```"
        match = re.search(code_block_pattern, raw_text, re.DOTALL)
        if match:
            json_candidate = match.group(1).strip()
            try:
                data = json.loads(json_candidate)
                return StepOutput(**data)
            except Exception:
                pass # Fallback to next method

        # B. Try to extract JSON object (find first { and last })
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            json_candidate = raw_text[start:end+1]
            try:
                data = json.loads(json_candidate)
                return StepOutput(**data)
            except Exception:
                # Attempt to repair truncated JSON
                try:
                    data = json.loads(json_candidate + "}")
                    return StepOutput(**data)
                except Exception:
                    try:
                        data = json.loads(json_candidate + "]}")
                        return StepOutput(**data)
                    except Exception:
                        pass # Fallback

        # C. Try Markdown Parsing (Fallback for "### StepOutput" format)
        try:
            # Regex to handle optional bolding (** or __), varying whitespace, and header levels (### or ####)
            # Matches: #### Thought_Process, ### **Thought Process**, ## Thought Process, etc.
            # We use #{1,6} to match any markdown header level.
            # We use [_\s]+ to match "Thought_Process" or "Thought Process"
            thought_pattern = r"#{1,6}\s*(?:\*\*|__)?\s*Thought[_\s]+Process\s*(?:\*\*|__)?\s*:?\s*(.*?)(?=#{1,6}\s*(?:\*\*|__)?\s*(?:Content|Insights|Metrics|Visualizations)|$)"
            content_pattern = r"#{1,6}\s*(?:\*\*|__)?\s*Content\s*(?:\*\*|__)?\s*:?\s*(.*?)(?=#{1,6}\s*(?:\*\*|__)?\s*(?:Thought[_\s]+Process|Insights|Metrics|Visualizations)|$)"
            insights_pattern = r"#{1,6}\s*(?:\*\*|__)?\s*Insights\s*(?:\*\*|__)?\s*:?\s*(.*?)(?=#{1,6}\s*(?:\*\*|__)?\s*(?:Thought[_\s]+Process|Content|Metrics|Visualizations)|$)"
            
            thought_match = re.search(thought_pattern, raw_text, re.DOTALL | re.IGNORECASE)
            content_match = re.search(content_pattern, raw_text, re.DOTALL | re.IGNORECASE)
            
            if thought_match and content_match:
                thought = thought_match.group(1).strip()
                content = content_match.group(1).strip()
                
                insights = []
                insights_match = re.search(insights_pattern, raw_text, re.DOTALL | re.IGNORECASE)
                if insights_match:
                    raw_insights = insights_match.group(1).strip()
                    insights = [line.strip("- *").strip() for line in raw_insights.split("\n") if line.strip().startswith(("-", "*"))]
                
                return StepOutput(
                    thought_process=thought,
                    content=content,
                    metrics={},
                    visualizations=[],
                    insights=insights
                )
        except Exception:
            pass

        # D. Final Fallback: Wrap Raw Text
        return StepOutput(
            thought_process="Raw Output (Parsing Failed)",
            content=raw_text,
            metrics={},
            visualizations=[],
            insights=[]
        )

    def _sanitize_visualizations(self, step_output: Any) -> Any:
        """
        Ensure visualizations are renderable objects (type + data) and move unsupported notes into insights.
        """
        try:
            viz = getattr(step_output, "visualizations", [])
            if not viz:
                return step_output
            supported_types = {"bar", "line", "pie", "area", "table"}
            cleaned = []
            notes = []
            for item in viz:
                if not isinstance(item, dict):
                    notes.append(f"Visualization skipped (not an object): {item}")
                    continue
                vtype = item.get("type")
                # Normalize aliases
                if vtype in ["bar_chart", "barChart"]:
                    vtype = "bar"
                    item["type"] = "bar"
                if vtype in ["line_chart", "lineChart"]:
                    vtype = "line"
                    item["type"] = "line"
                if vtype in ["area_chart", "areaChart"]:
                    vtype = "area"
                    item["type"] = "area"

                if vtype == "table":
                    cols = item.get("columns") or item.get("headers") or []
                    rows = item.get("rows") or item.get("values") or item.get("data") or []
                    if cols and rows:
                        cleaned.append({"type": "table", "title": item.get("title"), "columns": cols, "rows": rows})
                    else:
                        notes.append("Table visualization missing columns/rows; skipped.")
                    continue

                if vtype in supported_types:
                    cleaned.append(item)
                else:
                    notes.append(f"Visualization type '{vtype}' not supported; skipped.")

            step_output.visualizations = cleaned
            if notes:
                if not getattr(step_output, "insights", None):
                    step_output.insights = []
                if isinstance(step_output.insights, list):
                    step_output.insights.extend(notes)
            return step_output
        except Exception:
            return step_output

