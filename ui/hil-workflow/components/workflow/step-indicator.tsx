"use client";

import { CheckCircle, Loader2, Clock, Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepIndicatorProps {
    status: "completed" | "current" | "pending";
    isRunning?: boolean;
    className?: string;
}

export function StepIndicator({ status, isRunning, className }: StepIndicatorProps) {
    const baseClasses = "step-indicator relative";

    if (status === "completed") {
        return (
            <div className={cn(baseClasses, "step-indicator-completed", className)}>
                <CheckCircle className="w-3 h-3 animate-check" />
            </div>
        );
    }

    if (status === "current") {
        return (
            <div className={cn(baseClasses, "step-indicator-current", isRunning && "animate-pulse-ring", className)}>
                {isRunning ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                    <Clock className="w-3 h-3" />
                )}
            </div>
        );
    }

    return (
        <div className={cn(baseClasses, "step-indicator-pending", className)}>
            <Circle className="w-3 h-3" />
        </div>
    );
}
