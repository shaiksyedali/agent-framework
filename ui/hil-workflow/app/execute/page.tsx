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
import { Visualizations } from "@/components/visualizations";
import { Chat } from "@/components/chat";
import { Loader2, AlertCircle, CheckCircle, Clock, Circle, ArrowRight } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { JobStatus, WorkflowConfig } from "@/lib/types";

// Import new workflow components
import { StatusHeader, StepIndicator, StepOutput, LiveLogs } from "@/components/workflow";

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
            const updatedJob = await getJobStatus(jobId);
            setJob(updatedJob);
        } catch (err: any) {
            setError(err.message || "Failed to resume workflow");
            console.error(err);
        }
    };

    // Loading states
    if (!workflowId && !jobId) return <div className="p-8 text-center text-slate-500">Invalid URL</div>;

    if (!jobId || !workflow) return (
        <div className="flex justify-center p-12 flex-col items-center gap-4">
            <div className="relative">
                <div className="w-16 h-16 rounded-full border-4 border-blue-100 border-t-blue-500 animate-spin" />
            </div>
            <div className="text-lg font-medium text-slate-700">Initializing Workflow...</div>
            <div className="text-sm text-slate-500">Preparing execution environment</div>
            {error && <div className="text-red-500 mt-4">{error}</div>}
        </div>
    );

    const totalSteps = workflow.steps?.length || 0;
    const currentStepIndex = job?.current_step_index || 0;

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
            <div className="container mx-auto p-6 lg:p-8 space-y-6 max-w-[1600px]">

                {/* Enhanced Status Header */}
                <Card className="glass border-0 shadow-lg">
                    <CardContent className="p-6">
                        <StatusHeader
                            workflowName={workflow.name}
                            jobId={jobId}
                            status={job?.status || "unknown"}
                            currentStepIndex={currentStepIndex}
                            totalSteps={totalSteps}
                        />
                    </CardContent>
                </Card>

                <div className="grid gap-6 lg:grid-cols-3">
                    {/* Left Column: Execution Timeline */}
                    <Card className="lg:col-span-2 flex flex-col shadow-lg border-0">
                        <CardHeader className="border-b bg-slate-50/50">
                            <CardTitle className="flex items-center gap-2">
                                <ArrowRight className="w-5 h-5 text-blue-500" />
                                Execution Timeline
                            </CardTitle>
                            <CardDescription>Step-by-step progress</CardDescription>
                        </CardHeader>
                        <CardContent className="flex-1 p-6">
                            <div className="space-y-0">
                                {workflow.steps?.map((step: any, index: number) => {
                                    const isCompleted = currentStepIndex > index;
                                    const isCurrent = currentStepIndex === index;
                                    const isPending = currentStepIndex < index;
                                    const isRunning = isCurrent && job?.status === "running";
                                    const isWaiting = isCurrent && job?.status === "waiting_for_user";

                                    const stepOutput = job?.step_outputs?.[step.name];
                                    const rawOutput = job?.context?.[step.output_key];
                                    const showOutput = isCompleted || isWaiting;

                                    return (
                                        <div
                                            key={step.id || index}
                                            className={`timeline-card ${isCompleted ? 'text-green-500' : isCurrent ? 'text-blue-500' : 'text-gray-300'}`}
                                        >
                                            {/* Step Indicator */}
                                            <div className="absolute left-0 top-0">
                                                <StepIndicator
                                                    status={isCompleted ? "completed" : isCurrent ? "current" : "pending"}
                                                    isRunning={isRunning}
                                                />
                                            </div>

                                            {/* Step Header */}
                                            <div className="mb-3">
                                                <div className="flex items-center gap-3">
                                                    <h3 className={`font-semibold text-lg ${isPending ? "text-slate-400" : "text-slate-800"}`}>
                                                        {step.name}
                                                    </h3>
                                                    {isRunning && (
                                                        <span className="flex items-center gap-1.5 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                                                            <Loader2 className="w-3 h-3 animate-spin" />
                                                            Executing
                                                        </span>
                                                    )}
                                                    {isWaiting && (
                                                        <span className="flex items-center gap-1.5 text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
                                                            <Clock className="w-3 h-3" />
                                                            Awaiting Review
                                                        </span>
                                                    )}
                                                </div>
                                                <p className="text-sm text-slate-500 mt-0.5">{step.type}</p>
                                            </div>

                                            {/* Step Output */}
                                            <StepOutput
                                                output={stepOutput}
                                                rawOutput={rawOutput}
                                                isVisible={showOutput}
                                            />

                                            {/* HIL Review Panel */}
                                            {isWaiting && (
                                                <div className="hil-review-panel mt-4">
                                                    <h4 className="font-semibold text-amber-900 flex items-center gap-2 mb-3">
                                                        <AlertCircle className="h-5 w-5" />
                                                        {job?.context?.is_last_step
                                                            ? "Final Step Review"
                                                            : "Review Required"
                                                        }
                                                    </h4>

                                                    <p className="text-sm text-amber-800 mb-4">
                                                        {job?.context?.is_last_step
                                                            ? "This is the final step. Approve to complete the workflow, or provide feedback to retry."
                                                            : "Review the output above. Approve to continue, or provide feedback to retry this step."
                                                        }
                                                    </p>

                                                    {error && (
                                                        <div className="p-3 bg-red-100 border border-red-200 text-red-900 rounded-lg text-sm mb-4">
                                                            {error}
                                                        </div>
                                                    )}

                                                    <div className="space-y-3">
                                                        <div>
                                                            <label className="text-sm font-medium text-slate-700 mb-1.5 block">
                                                                Feedback (optional for approval)
                                                            </label>
                                                            <textarea
                                                                value={hilInput}
                                                                onChange={(e) => setHilInput(e.target.value)}
                                                                placeholder="Enter feedback to modify or improve this step..."
                                                                className="w-full min-h-[80px] p-3 rounded-lg border border-amber-200 focus:border-amber-400 focus:ring-2 focus:ring-amber-200 bg-white resize-none"
                                                            />
                                                        </div>

                                                        <div className="flex gap-3">
                                                            <Button
                                                                onClick={() => handleResume(true)}
                                                                className="flex-1 bg-green-600 hover:bg-green-700 text-white shadow-md"
                                                            >
                                                                <CheckCircle className="w-4 h-4 mr-2" />
                                                                {job?.context?.is_last_step
                                                                    ? "Approve & Complete"
                                                                    : "Approve & Continue"
                                                                }
                                                            </Button>

                                                            <Button
                                                                onClick={() => handleResume(false)}
                                                                variant="outline"
                                                                className="flex-1 border-amber-300 text-amber-700 hover:bg-amber-50"
                                                                disabled={!hilInput.trim()}
                                                            >
                                                                🔄 {hilInput.trim() ? "Submit & Retry" : "Enter Feedback First"}
                                                            </Button>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}

                                {(!workflow.steps || workflow.steps.length === 0) && (
                                    <div className="text-slate-400 italic text-center py-8">
                                        No steps defined in this workflow.
                                    </div>
                                )}
                            </div>
                        </CardContent>
                    </Card>

                    {/* Right Column: Tabs for Logs, Visualizations, Chat */}
                    <div className="space-y-6">
                        <Tabs defaultValue="logs" className="w-full">
                            <TabsList className="grid w-full grid-cols-3 bg-slate-100 p-1 rounded-lg">
                                <TabsTrigger value="logs" className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm">
                                    Logs
                                </TabsTrigger>
                                <TabsTrigger value="visualizations" className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm">
                                    Charts
                                </TabsTrigger>
                                <TabsTrigger value="chat" className="rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm">
                                    Chat
                                </TabsTrigger>
                            </TabsList>

                            <TabsContent value="logs" className="mt-4">
                                <LiveLogs logs={job?.logs || []} className="h-[500px]" />
                            </TabsContent>

                            <TabsContent value="visualizations" className="mt-4">
                                <Card className="h-[500px] flex flex-col shadow-lg border-0">
                                    <CardHeader className="border-b bg-slate-50/50">
                                        <CardTitle className="text-base">Visualizations</CardTitle>
                                    </CardHeader>
                                    <CardContent className="flex-1 p-4 overflow-auto">
                                        {job?.context?.visualizations ? (
                                            <Visualizations data={job.context.visualizations} />
                                        ) : (
                                            <div className="flex items-center justify-center h-full text-slate-400">
                                                <div className="text-center">
                                                    <div className="text-4xl mb-2">📊</div>
                                                    <p>No visualizations yet</p>
                                                </div>
                                            </div>
                                        )}
                                    </CardContent>
                                </Card>
                            </TabsContent>

                            <TabsContent value="chat" className="mt-4">
                                {job?.status === "completed" ? (
                                    <Chat jobId={jobId} />
                                ) : (
                                    <Card className="h-[500px] flex items-center justify-center text-slate-400 shadow-lg border-0">
                                        <div className="text-center">
                                            <div className="text-4xl mb-2">💬</div>
                                            <p>Chat available after completion</p>
                                        </div>
                                    </Card>
                                )}
                            </TabsContent>
                        </Tabs>
                    </div>
                </div>
            </div>
        </div>
    );
}
