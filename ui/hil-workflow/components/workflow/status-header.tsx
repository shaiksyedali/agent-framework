"use client";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Loader2, CheckCircle, XCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusHeaderProps {
    workflowName: string;
    jobId: string;
    status: string;
    currentStepIndex: number;
    totalSteps: number;
}

function getStatusIcon(status: string) {
    switch (status) {
        case "completed":
            return <CheckCircle className="w-4 h-4" />;
        case "failed":
            return <XCircle className="w-4 h-4" />;
        case "running":
            return <Loader2 className="w-4 h-4 animate-spin" />;
        case "waiting_for_user":
            return <Clock className="w-4 h-4" />;
        default:
            return null;
    }
}

function getStatusBadgeClass(status: string) {
    switch (status) {
        case "completed":
            return "status-badge-completed";
        case "failed":
            return "status-badge-failed";
        case "running":
            return "status-badge-running";
        case "waiting_for_user":
            return "status-badge-waiting";
        default:
            return "";
    }
}

export function StatusHeader({
    workflowName,
    jobId,
    status,
    currentStepIndex,
    totalSteps
}: StatusHeaderProps) {
    const progress = totalSteps > 0 ? Math.round((currentStepIndex / totalSteps) * 100) : 0;
    const completedProgress = status === "completed" ? 100 : progress;

    return (
        <div className="space-y-4">
            {/* Header Row */}
            <div className="flex justify-between items-start gap-4">
                <div className="flex-1 min-w-0">
                    <h1 className="text-2xl font-bold text-slate-900 truncate">
                        {workflowName}
                    </h1>
                    <p className="text-sm text-slate-500 font-mono mt-1">
                        Job: {jobId.slice(0, 8)}...
                    </p>
                </div>

                <Badge
                    className={cn(
                        "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-full",
                        getStatusBadgeClass(status)
                    )}
                >
                    {getStatusIcon(status)}
                    {status?.replace(/_/g, " ").toUpperCase()}
                </Badge>
            </div>

            {/* Progress Bar */}
            <div className="space-y-2">
                <div className="flex justify-between items-center text-sm">
                    <span className="text-slate-600">
                        Step {Math.min(currentStepIndex + 1, totalSteps)} of {totalSteps}
                    </span>
                    <span className="font-medium text-slate-700">{completedProgress}%</span>
                </div>
                <div className="relative h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                        className="absolute inset-y-0 left-0 progress-gradient rounded-full transition-all duration-500"
                        style={{ width: `${completedProgress}%` }}
                    />
                </div>
            </div>
        </div>
    );
}
