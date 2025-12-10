"use client";

import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getJob, resumeJob, executeWorkflow, getWorkflow } from "@/lib/api";
import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Visualizations } from "@/components/visualizations";
import { Chat } from "@/components/chat";
import { Loader2, CheckCircle, AlertCircle, Clock } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function Execute() {
    const searchParams = useSearchParams();
    const workflowId = searchParams.get("id");
    const [jobId, setJobId] = useState<string | null>(null);
    const [hilInput, setHilInput] = useState("");
    const queryClient = useQueryClient();

    // Start execution on mount if workflowId is present and no jobId
    const executionStarted = useRef(false);

    useEffect(() => {
        if (workflowId && !jobId && !executionStarted.current) {
            executionStarted.current = true;
            executeWorkflow(workflowId, { input: "Start" }) // Default input
                .then(job => setJobId(job.id))
                .catch(err => {
                    console.error("Failed to start", err);
                    executionStarted.current = false;
                });
        }
    }, [workflowId, jobId]);

    const { data: job } = useQuery({
        queryKey: ["job", jobId],
        queryFn: () => getJob(jobId!),
        enabled: !!jobId,
        refetchInterval: (query) => {
            const data = query.state.data;
            return (data?.status === "completed" || data?.status === "failed") ? false : 1000;
        },
    });

    // Fetch workflow definition to render steps
    const { data: workflow } = useQuery({
        queryKey: ["workflow", workflowId],
        queryFn: () => getWorkflow(workflowId!),
        enabled: !!workflowId,
    });

    const [error, setError] = useState<string | null>(null);

    const resumeMutation = useMutation({
        mutationFn: () => resumeJob(jobId!, hilInput),
        onSuccess: () => {
            setHilInput("");
            setError(null);
            queryClient.invalidateQueries({ queryKey: ["job", jobId] });
        },
        onError: (err: any) => {
            setError(err.response?.data?.detail || err.message || "Failed to resume workflow");
        }
    });

    const parseQuestion = (text: string) => {
        const question = text.replace(/^QUESTION:\s*/i, "").split("Available options:")[0].trim();
        let options: string[] = [];
        const match = text.match(/Available options:\s*\[([^\]]*)\]/i);
        if (match && match[1]) {
            options = match[1].split(",").map(o => o.trim().replace(/^['"]|['"]$/g, "")).filter(Boolean).slice(0, 8);
        }
        return { question: question || text.trim(), options };
    };

    if (!workflowId && !jobId) return <div>Invalid URL</div>;
    if (!jobId || !workflow) return <div className="flex justify-center p-8"><Loader2 className="animate-spin" /> Starting Workflow...</div>;

    type RowRecord = Record<string, string | number | null | undefined>;
    const renderTable = (rows: RowRecord[] = [], label: string, note?: string) => {
        if (!rows || rows.length === 0) return null;
        const headers = Object.keys(rows[0] || {});
        return (
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold">{label}</h4>
                    {note && <span className="text-xs text-muted-foreground">{note}</span>}
                </div>
                <div className="overflow-auto border rounded-md">
                    <table className="min-w-full text-sm">
                        <thead className="bg-muted/50">
                            <tr>
                                {headers.map((h) => (
                                    <th key={h} className="px-2 py-1 text-left font-semibold border-b">{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, idx) => (
                                <tr key={idx} className="border-b last:border-0">
                                    {headers.map((h) => (
                                        <td key={h} className="px-2 py-1 whitespace-pre text-xs font-mono">
                                            {row?.[h] === null || row?.[h] === undefined ? "" : String(row[h])}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    return (
        <div className="container mx-auto p-8 space-y-8">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Executing Workflow: {workflow.name}</h1>
                    <p className="text-muted-foreground">Job ID: {jobId}</p>
                </div>
                <Badge variant={job?.status === "completed" ? "default" : job?.status === "failed" ? "destructive" : "secondary"}>
                    {job?.status?.toUpperCase()}
                </Badge>
            </div>

            <div className="grid gap-8 md:grid-cols-3">
                {/* Left Column: Step Timeline */}
                <Card className="md:col-span-2 flex flex-col">
                    <CardHeader>
                        <CardTitle>Execution Timeline</CardTitle>
                    </CardHeader>
                    <CardContent className="flex-1 p-6 space-y-8">
                        {workflow.steps?.map((step: any, index: number) => {
                            const isCompleted = (job?.current_step_index || 0) > index;
                            const isCurrent = (job?.current_step_index || 0) === index;
                            const isPending = (job?.current_step_index || 0) < index;

                            // Check for rich output first, fallback to context key
                            const rawStepOutput = job?.step_outputs?.[step.name] as any;
                            let stepOutput = rawStepOutput;
                            if (typeof rawStepOutput === "string") {
                                try {
                                    const parsed = JSON.parse(rawStepOutput);
                                    stepOutput = parsed;
                                } catch {
                                    // leave as string
                                }
                            }
                            const rawOutput = job?.context?.[step.output_key];
                            const lastLog = job?.logs?.[job.logs.length - 1];

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
                                                                    <div className="text-lg font-mono">{value}</div>
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
                                                    <div className="bg-muted/50 rounded-md p-4 prose prose-sm max-w-none dark:prose-invert whitespace-pre-wrap break-words">
                                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                            {stepOutput.content}
                                                        </ReactMarkdown>
                                                    </div>

                                                    {/* Aggregated preview (primary grid) */}
                                                    {renderTable(
                                                        stepOutput.aggregate_rows,
                                                        stepOutput.render_hints?.aggregate_view_label || "Aggregated results",
                                                        stepOutput.preview_note || `Rows: ${stepOutput.aggregate_rows?.length || 0}${stepOutput.metrics?.full_row_count ? ` of ${stepOutput.metrics.full_row_count}` : ""}`
                                                    )}

                                                    {/* Raw preview (secondary) */}
                                                    {renderTable(
                                                        stepOutput.raw_rows,
                                                        stepOutput.render_hints?.raw_view_label || "Raw sample (not aggregated)",
                                                        stepOutput.raw_rows && stepOutput.raw_rows.length > 0 ? `Rows: ${stepOutput.raw_rows.length}` : undefined
                                                    )}

                                                    {/* Download hint */}
                                                    {stepOutput.metrics?.full_data_available && (
                                                        <div className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded p-3">
                                                            <div className="text-xs text-muted-foreground">
                                                                {stepOutput.download_hint || "Full data retained server-side. Use download action to fetch full dataset."}
                                                            </div>
                                                            <Button variant="outline" size="sm" disabled>
                                                                Download full data
                                                            </Button>
                                                        </div>
                                                    )}

                                                    {/* Insights */}
                                                    {stepOutput.insights && stepOutput.insights.length > 0 && (
                                                        <div className="bg-blue-50 border border-blue-100 rounded-md p-4">
                                                            <h4 className="text-sm font-semibold text-blue-900 mb-2 flex items-center gap-2">
                                                                <span className="text-blue-500">💡</span> Key Insights
                                                            </h4>
                                                            <ul className="list-disc list-inside text-sm text-blue-800 space-y-1">
                                                                {stepOutput.insights.map((insight, i) => (
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
                                                <>
                                                    {String(rawOutput).trim().startsWith("QUESTION:") ? (
                                                        <div className="bg-yellow-100 border border-yellow-200 text-yellow-900 p-3 rounded space-y-2">
                                                            <div className="font-semibold">
                                                                {parseQuestion(String(rawOutput)).question}
                                                            </div>
                                                            {parseQuestion(String(rawOutput)).options.length > 0 && (
                                                                <div className="flex flex-wrap gap-2">
                                                                    {parseQuestion(String(rawOutput)).options.map((opt, idx) => (
                                                                        <Button
                                                                            key={idx}
                                                                            variant="secondary"
                                                                            size="sm"
                                                                            onClick={() => setHilInput(opt)}
                                                                        >
                                                                            {opt}
                                                                        </Button>
                                                                    ))}
                                                                </div>
                                                            )}
                                                        </div>
                                                    ) : (
                                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                            {String(rawOutput)}
                                                        </ReactMarkdown>
                                                    )}
                                                </>
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
                                                        <AlertCircle className="h-4 w-4" /> Review Step: {step.name}
                                                    </h4>

                                                    {/* Feedback Prompt from Logs */}
                                                    <div className="mt-2 mb-4 p-3 bg-white/50 rounded border border-yellow-100 text-sm font-medium text-yellow-900">
                                                        {lastLog || "Please review the steps and provide feedback."}
                                                    </div>

                                                    <div className="space-y-4">
                                                        {error && (
                                                            <div className="p-3 bg-red-100 border border-red-200 text-red-900 rounded text-sm">
                                                                {error}
                                                            </div>
                                                        )}
                                                        <Input
                                                            value={hilInput}
                                                            onChange={(e) => setHilInput(e.target.value)}
                                                            placeholder="Enter feedback to retry this step, or leave empty to proceed..."
                                                            className="bg-white"
                                                        />
                                                        <Button onClick={() => {
                                                            console.log("Submitting HIL Feedback:", hilInput);
                                                            resumeMutation.mutate();
                                                        }} disabled={resumeMutation.isPending}>
                                                            {resumeMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                                            {hilInput ? "Submit Feedback & Retry" : "Proceed to Next Step"}
                                                        </Button>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
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
