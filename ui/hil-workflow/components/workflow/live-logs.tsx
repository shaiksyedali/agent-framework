"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Terminal, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface LiveLogsProps {
    logs: string[];
    className?: string;
}

export function LiveLogs({ logs, className }: LiveLogsProps) {
    const scrollRef = useRef<HTMLDivElement>(null);
    const [autoScroll, setAutoScroll] = useState(true);

    useEffect(() => {
        if (autoScroll && scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs, autoScroll]);

    const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
        const target = e.target as HTMLDivElement;
        const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 50;
        setAutoScroll(isAtBottom);
    };

    return (
        <Card className={cn("flex flex-col overflow-hidden", className)}>
            <CardHeader className="pb-3 flex-shrink-0">
                <CardTitle className="flex items-center gap-2 text-base">
                    <Terminal className="w-4 h-4" />
                    Live Logs
                </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 p-0 min-h-0">
                <div
                    ref={scrollRef}
                    onScroll={handleScroll}
                    className="terminal-log h-full overflow-auto"
                >
                    {logs && logs.length > 0 ? (
                        logs.map((log, i) => (
                            <div key={i} className="terminal-log-entry animate-fade-slide-in">
                                <span className="terminal-log-timestamp">
                                    [{new Date().toLocaleTimeString()}]
                                </span>
                                <span className="terminal-log-prefix">›</span>
                                {log}
                            </div>
                        ))
                    ) : (
                        <div className="text-slate-500 italic">Waiting for logs...</div>
                    )}
                </div>

                {/* Scroll to bottom indicator */}
                {!autoScroll && logs.length > 5 && (
                    <button
                        onClick={() => {
                            setAutoScroll(true);
                            if (scrollRef.current) {
                                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                            }
                        }}
                        className="absolute bottom-4 right-4 bg-slate-700 hover:bg-slate-600 text-white px-3 py-1.5 rounded-full text-xs flex items-center gap-1 shadow-lg"
                    >
                        <ChevronDown className="w-3 h-3" />
                        Latest
                    </button>
                )}
            </CardContent>
        </Card>
    );
}
