"use client";

import { useState } from "react";
import { chatWithJob } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send } from "lucide-react";

interface Message {
    role: 'user' | 'assistant';
    content: string;
}

export function Chat({ jobId }: { jobId: string }) {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMsg = { role: 'user' as const, content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput("");
        setIsLoading(true);

        try {
            const response = await chatWithJob({
                job_id: jobId,
                message: userMsg.content,
                context: {} // Optional context
            });
            // Adapt response which is { response: string; context: any }
            setMessages(prev => [...prev, { role: 'assistant', content: response.response }]);
        } catch (error) {
            console.error("Chat failed", error);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <Card className="h-[500px] flex flex-col">
            <CardHeader>
                <CardTitle>Chat with Agent</CardTitle>
            </CardHeader>
            <CardContent className="flex-1 p-0">
                <ScrollArea className="h-[350px] p-4">
                    {messages.map((msg, i) => (
                        <div key={i} className={`mb-4 flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`rounded-lg p-3 max-w-[80%] ${msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
                                {msg.content}
                            </div>
                        </div>
                    ))}
                    {isLoading && <div className="text-sm text-muted-foreground">Agent is typing...</div>}
                </ScrollArea>
            </CardContent>
            <CardFooter className="p-4 pt-0">
                <div className="flex w-full items-center space-x-2">
                    <Input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Ask a question..."
                        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                    />
                    <Button size="icon" onClick={handleSend} disabled={isLoading}>
                        <Send className="h-4 w-4" />
                    </Button>
                </div>
            </CardFooter>
        </Card>
    );
}
