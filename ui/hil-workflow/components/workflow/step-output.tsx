"use client";

import { ChevronRight, Lightbulb, Brain } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface StepOutputProps {
    output: {
        content?: string;
        thought_process?: string;
        metrics?: Record<string, any>;
        insights?: string[];
        visualizations?: any[];
    } | null;
    rawOutput?: string;
    isVisible: boolean;
}

export function StepOutput({ output, rawOutput, isVisible }: StepOutputProps) {
    const [isThoughtOpen, setIsThoughtOpen] = useState(false);

    if (!isVisible) return null;

    // Rich output rendering
    if (output) {
        return (
            <div className="space-y-4 animate-fade-slide-in">
                {/* Metrics Grid */}
                {output.metrics && Object.keys(output.metrics).length > 0 && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {Object.entries(output.metrics).map(([key, value]) => (
                            <div key={key} className="metric-card">
                                <div className="text-xs text-slate-500 uppercase font-semibold tracking-wide">
                                    {key.replace(/_/g, " ")}
                                </div>
                                <div className="text-xl font-bold text-slate-800 mt-1">
                                    {typeof value === "number" ? value.toLocaleString() : String(value)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {/* Thought Process Collapsible */}
                {output.thought_process && (
                    <Collapsible open={isThoughtOpen} onOpenChange={setIsThoughtOpen}>
                        <div className="thought-process">
                            <CollapsibleTrigger className="thought-process-header w-full">
                                <Brain className="w-4 h-4" />
                                <span>Thought Process</span>
                                <ChevronRight className={cn(
                                    "w-4 h-4 ml-auto transition-transform",
                                    isThoughtOpen && "rotate-90"
                                )} />
                            </CollapsibleTrigger>
                            <CollapsibleContent>
                                <div className="thought-process-content">
                                    {output.thought_process}
                                </div>
                            </CollapsibleContent>
                        </div>
                    </Collapsible>
                )}

                {/* Main Content */}
                {output.content && (
                    <div className="step-output-card prose-modern">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {output.content}
                        </ReactMarkdown>
                    </div>
                )}

                {/* Insights */}
                {output.insights && output.insights.length > 0 && (
                    <div className="insights-callout">
                        <h4 className="text-sm font-semibold text-blue-900 mb-3 flex items-center gap-2">
                            <Lightbulb className="w-4 h-4 text-amber-500" />
                            Key Insights
                        </h4>
                        <ul className="space-y-2">
                            {output.insights.map((insight, i) => (
                                <li
                                    key={i}
                                    className="text-sm text-blue-800 flex items-start gap-2"
                                >
                                    <span className="text-blue-400 mt-1">•</span>
                                    {insight}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {/* Visualizations hint */}
                {output.visualizations && output.visualizations.length > 0 && (
                    <p className="text-xs text-slate-500">
                        📊 {output.visualizations.length} visualization(s) available in the Visualizations tab
                    </p>
                )}
            </div>
        );
    }

    // Fallback to raw output
    return (
        <div className="step-output-card prose-modern animate-fade-slide-in">
            {rawOutput ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {String(rawOutput)}
                </ReactMarkdown>
            ) : (
                <span className="text-slate-400 italic">No output generated for this step.</span>
            )}
        </div>
    );
}
