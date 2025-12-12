"use client";

import { useSearchParams } from "next/navigation";
import {
    getJobStatus,
    resumeJob,
    executeWorkflow,
    getWorkflow
} from "@/lib/apiClient";
import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Visualizations } from "@/components/visualizations";
import { Chat } from "@/components/chat";
import { Loader2, AlertCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { JobStatus, WorkflowConfig } from "@/lib/types";

export default function Execute() {
    const searchParams = useSearchParams();
    const workflowId = searchParams.get("id");
    const [jobId, setJobId] = useState<string | null>(null);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [workflow, setWorkflow] = useState<WorkflowConfig | null>(null);
    const [hilInput, setHilInput] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    // Start execution on mount if workflowId is present and no jobId
    const executionStarted = useRef(false);

    useEffect(() => {
        if (workflowId) {
            getWorkflow(workflowId).then(setWorkflow).catch(err => {
                console.error("Failed to load workflow", err);
                setError("Failed to load workflow definition");
            });
        }
    }, [workflowId]);

    useEffect(() => {
        if (workflowId && !jobId && !executionStarted.current && workflow) {
            // Check if we need to ask for input first? 
            // For now, assume "Start" or use workflow.user_intent
            executionStarted.current = true;
            setIsLoading(true);

            const startInput = workflow.user_intent || "Start execution";

            executeWorkflow({
                workflow_id: workflowId,
                input_data: { input: startInput }
            })
                .then(newJob => {
                    setJobId(newJob.id);
                    setJob(newJob);
                })
                .catch(err => {
                    console.error("Failed to start", err);
                    setError("Failed to start execution: " + err.message);
                    executionStarted.current = false;
                })
                .finally(() => setIsLoading(false));
        }
    }, [workflowId, jobId, workflow]);

    // Polling for job status
    useEffect(() => {
        if (jobId && job?.status !== 'completed' && job?.status !== 'failed') {
            const interval = setInterval(async () => {
                try {
                    const updatedJob = await getJobStatus(jobId);
                    setJob(updatedJob);

                    if (updatedJob.status === 'completed' || updatedJob.status === 'failed') {
                        clearInterval(interval);
                    }
                } catch (err) {
                    console.error("Failed to poll job status", err);
                }
            }, 1000);

            return () => clearInterval(interval);
        }
    }, [jobId, job?.status]);

    const handleResume = async (approved: boolean) => {
        if (!jobId) return;

        try {
            await resumeJob({
                job_id: jobId,
                approved: approved,
                user_input: hilInput
            });
            setHilInput("");
            setError(null);
            // Force immediate update
            const updatedJob = await getJobStatus(jobId);
            setJob(updatedJob);
        } catch (err: any) {
            setError(err.message || "Failed to resume workflow");
            console.error(err);
        }
    };

    if (!workflowId && !jobId) return <div>Invalid URL</div>;
    if (!jobId || !workflow) return (
        <div className="flex justify-center p-8 flex-col items-center gap-4">
            <Loader2 className="animate-spin h-8 w-8 text-blue-500" />
            <div>Initializing Workflow Execution...</div>
            {error && <div className="text-red-500">{error}</div>}
        </div>
    );

    return (
        <div className="container mx-auto p-8 space-y-8 max-w-[1400px]">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Executing Workflow: {workflow.name}</h1>
                    <p className="text-muted-foreground">Job ID: {jobId}</p>
                </div>
                <Badge variant={job?.status === "completed" ? "default" : job?.status === "failed" ? "destructive" : "secondary"}>
                    {job?.status?.toUpperCase() || 'UNKNOWN'}
                </Badge>
            </div>

            <div className="grid gap-8 md:grid-cols-3">
                {/* Left Column: Step Timeline */}
                <Card className="md:col-span-2 flex flex-col">
                    <CardHeader>
                        <CardTitle>Execution Timeline</CardTitle>
                        <CardDescription>Step-by-step progress</CardDescription>
                    </CardHeader>
                    <CardContent className="flex-1 p-6 space-y-8">
                        {workflow.steps?.map((step: any, index: number) => {
                            const isCompleted = (job?.current_step_index || 0) > index;
                            const isCurrent = (job?.current_step_index || 0) === index;
                            const isPending = (job?.current_step_index || 0) < index;

                            // Check for rich output first, fallback to context key
                            const stepOutput = job?.step_outputs?.[step.name];
                            const rawOutput = job?.context?.[step.output_key];
                            const lastLog = job?.logs && job.logs.length > 0 ? job.logs[job.logs.length - 1] : null;

                            return (
                                <div key={step.id || index} className={`relative pl-8 border-l-2 ${isCompleted ? "border-green-500" : isCurrent ? "border-blue-500" : "border-gray-200"}`}>
                                    <div className={`absolute -left-[9px] top-0 w-4 h-4 rounded-full ${isCompleted ? "bg-green-500" : isCurrent ? "bg-blue-500" : "bg-gray-200"}`} />

                                    <div className="mb-2">
                                        <h3 className={`font-semibold text-lg ${isPending ? "text-muted-foreground" : ""}`}>{step.name}</h3>
                                        <p className="text-sm text-muted-foreground">{step.type}</p>
                                    </div>

                                    {/* Output for completed steps or current step in review */}
                                    {(isCompleted || (isCurrent && job?.status === "waiting_for_user")) && (
                                        <div className="space-y-4 mt-2">

                                            {/* Rich Output Rendering */}
                                            {stepOutput ? (
                                                <>
                                                    {/* Metrics */}
                                                    {stepOutput.metrics && Object.keys(stepOutput.metrics).length > 0 && (
                                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                                                            {Object.entries(stepOutput.metrics).map(([key, value]) => (
                                                                <div key={key} className="bg-slate-50 p-2 rounded border border-slate-200">
                                                                    <div className="text-xs text-muted-foreground uppercase font-bold">{key}</div>
                                                                    <div className="text-lg font-mono">{String(value)}</div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}

                                                    {/* Thought Process (Collapsible) */}
                                                    {stepOutput.thought_process && (
                                                        <details className="group">
                                                            <summary className="cursor-pointer text-sm font-medium text-slate-500 hover:text-slate-700 flex items-center gap-1">
                                                                <span className="group-open:rotate-90 transition-transform">▶</span> Thought Process
                                                            </summary>
                                                            <div className="mt-2 p-3 bg-slate-50 rounded text-sm text-slate-600 whitespace-pre-wrap border-l-2 border-slate-300">
                                                                {stepOutput.thought_process}
                                                            </div>
                                                        </details>
                                                    )}

                                                    {/* Main Content */}
                                                    <div className="bg-muted/50 rounded-md p-4 prose prose-sm max-w-none dark:prose-invert">
                                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                            {stepOutput.content || ""}
                                                        </ReactMarkdown>
                                                    </div>

                                                    {/* Insights */}
                                                    {stepOutput.insights && stepOutput.insights.length > 0 && (
                                                        <div className="bg-blue-50 border border-blue-100 rounded-md p-4">
                                                            <h4 className="text-sm font-semibold text-blue-900 mb-2 flex items-center gap-2">
                                                                <span className="text-blue-500">💡</span> Key Insights
                                                            </h4>
                                                            <ul className="list-disc list-inside text-sm text-blue-800 space-y-1">
                                                                {stepOutput.insights.map((insight: string, i: number) => (
                                                                    <li key={i}>{insight}</li>
                                                                ))}
                                                            </ul>
                                                        </div>
                                                    )}

                                                    {/* Visualizations (Inline Preview) */}
                                                    {stepOutput.visualizations && stepOutput.visualizations.length > 0 && (
                                                        <div className="mt-2">
                                                            <p className="text-xs text-muted-foreground mb-1">Generated {stepOutput.visualizations.length} chart(s). See "Visualizations" tab for details.</p>
                                                        </div>
                                                    )}
                                                </>
                                            ) : (
                                                /* Fallback to Raw Output */
                                                <div className="bg-muted/50 rounded-md p-4 prose prose-sm max-w-none dark:prose-invert">
                                                    {rawOutput ? (
                                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                            {String(rawOutput)}
                                                        </ReactMarkdown>
                                                    ) : (
                                                        <span className="text-muted-foreground italic">No output generated for this step.</span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {/* Current Step Status */}
                                    {isCurrent && (
                                        <div className="mt-4">
                                            {job?.status === "running" && (
                                                <div className="flex items-center text-blue-500">
                                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Executing...
                                                </div>
                                            )}
                                            {job?.status === "waiting_for_user" && (
                                                <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
                                                    <h4 className="font-semibold text-yellow-800 flex items-center gap-2">
                                                        <AlertCircle className="h-4 w-4" />
                                                        {job?.context?.is_last_step
                                                            ? `Final Step Review: ${step.name}`
                                                            : `Review Step: ${step.name}`
                                                        }
                                                    </h4>

                                                    <div className="mt-2 mb-4 p-3 bg-white/50 rounded border border-yellow-100 text-sm font-medium text-yellow-900">
                                                        {job?.context?.is_last_step
                                                            ? "This is the final step. Approve to complete the workflow, or provide feedback to retry."
                                                            : "Review the output above. Approve to proceed, or provide feedback to retry this step."
                                                        }
                                                    </div>

                                                    <div className="space-y-4">
                                                        {error && (
                                                            <div className="p-3 bg-red-100 border border-red-200 text-red-900 rounded text-sm">
                                                                {error}
                                                            </div>
                                                        )}

                                                        <div>
                                                            <label className="text-sm font-semibold text-gray-700 mb-2 block">
                                                                Feedback (optional for approval, required for retry)
                                                            </label>
                                                            <textarea
                                                                value={hilInput}
                                                                onChange={(e) => setHilInput(e.target.value)}
                                                                placeholder="Enter feedback to retry this step with modifications..."
                                                                className="w-full min-h-[80px] p-3 rounded-md border border-gray-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-white"
                                                            />
                                                        </div>

                                                        <div className="flex gap-3 pt-2">
                                                            <Button
                                                                onClick={() => handleResume(true)}
                                                                className="flex-1 bg-green-600 hover:bg-green-700 text-white"
                                                            >
                                                                {job?.context?.is_last_step
                                                                    ? "✅ Approve & Complete Workflow"
                                                                    : "✅ Approve & Continue"
                                                                }
                                                            </Button>

                                                            <Button
                                                                onClick={() => handleResume(false)}
                                                                variant="outline"
                                                                className="flex-1 border-yellow-500 text-yellow-700 hover:bg-yellow-50"
                                                                disabled={!hilInput.trim()}
                                                            >
                                                                🔄 {hilInput.trim() ? "Submit Feedback & Retry" : "Enter Feedback to Retry"}
                                                            </Button>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                        {(!workflow.steps || workflow.steps.length === 0) && (
                            <div className="text-muted-foreground italic">No steps defined in workflow.</div>
                        )}
                    </CardContent>
                </Card>

                {/* Right Column: Tabs for Logs, Visualizations, Chat */}
                <div className="space-y-8">
                    <Tabs defaultValue="logs" className="w-full">
                        <TabsList className="grid w-full grid-cols-3">
                            <TabsTrigger value="logs">Live Logs</TabsTrigger>
                            <TabsTrigger value="visualizations">Visualizations</TabsTrigger>
                            <TabsTrigger value="chat">Chat</TabsTrigger>
                        </TabsList>

                        <TabsContent value="logs">
                            <Card className="h-[500px] flex flex-col">
                                <CardHeader><CardTitle>Live Logs</CardTitle></CardHeader>
                                <CardContent className="flex-1 p-0">
                                    <ScrollArea className="h-[400px] p-4">
                                        <div className="font-mono text-sm space-y-1">
                                            {job?.logs?.map((log, i) => (
                                                <div key={i} className="text-muted-foreground border-b border-border/50 pb-1 last:border-0">
                                                    <span className="text-xs opacity-50">[{new Date().toLocaleTimeString()}]</span> {log}
                                                </div>
                                            ))}
                                            {!job?.logs?.length && <div className="text-muted-foreground italic">No logs yet.</div>}
                                        </div>
                                    </ScrollArea>
                                </CardContent>
                            </Card>
                        </TabsContent>

                        <TabsContent value="visualizations">
                            <Card className="h-[500px] flex flex-col">
                                <CardHeader><CardTitle>Visualizations</CardTitle></CardHeader>
                                <CardContent className="flex-1 p-4">
                                    {job?.context?.visualizations ? (
                                        <Visualizations data={job.context.visualizations} />
                                    ) : (
                                        <div className="flex items-center justify-center h-full text-muted-foreground">
                                            No visualizations available
                                        </div>
                                    )}
                                </CardContent>
                            </Card>
                        </TabsContent>

                        <TabsContent value="chat">
                            {job?.status === "completed" ? (
                                <Chat jobId={jobId} />
                            ) : (
                                <Card className="h-[500px] flex items-center justify-center text-muted-foreground">
                                    Chat available after completion
                                </Card>
                            )}
                        </TabsContent>
                    </Tabs>
                </div>
            </div>
        </div>
    );
}
