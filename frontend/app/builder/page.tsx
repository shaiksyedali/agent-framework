"use client";

import { useState, useEffect } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { createWorkflow, createPlan, getWorkflow } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Plus, Trash, FolderOpen } from "lucide-react";
import { FileExplorer } from "@/components/file-explorer";

// Schema
const nullableArray = (schema: z.ZodTypeAny) =>
    z.preprocess((val) => (val === null ? [] : val), z.array(schema).optional().default([]));

const workflowSchema = z.object({
    id: z.string().optional(),
    name: z.string().min(1, "Name is required"),
    description: z.string().min(1, "Description is required"),
    user_intent: z.string().min(1, "Intent is required"),
    agents: nullableArray(z.object({
        id: z.string().optional(),
        name: z.string(),
        role: z.string(),
        instructions: z.string(),
        model_provider: z.string().optional(),
        model_name: z.string(),
        tools: nullableArray(z.string()),
        // Legacy MCP servers field, kept for compatibility but not used in UI
        mcp_servers: nullableArray(z.object({
            name: z.string(),
            command: z.string(),
            args: z.array(z.string()).optional(),
            env: z.record(z.string()).optional(),
            url: z.string().optional(),
        })),
        data_sources: nullableArray(z.string()),
    })),
    teams: nullableArray(z.object({
        id: z.string().optional(),
        name: z.string(),
        leader_agent_id: z.string().optional().nullable(),
        member_agent_ids: z.array(z.string()),
        instructions: z.string().optional(),
        model_provider: z.string().optional(),
        model_name: z.string().optional(),
    })),
    data_sources: nullableArray(z.object({
        id: z.string().optional(),
        name: z.string(),
        type: z.string(),
        connection_string: z.string().nullable().optional(),
        path: z.string().nullable().optional(),
        url: z.string().nullable().optional(),
    })),
    steps: nullableArray(z.object({
        id: z.string().optional(),
        name: z.string(),
        type: z.string(),
        agent_id: z.string().nullable().optional(),
        team_id: z.string().nullable().optional(),
        input_template: z.string(),
        output_key: z.string(),
    })),
});

export default function Builder() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const id = searchParams.get("id");

    const [isPlanning, setIsPlanning] = useState(false);
    const [fileExplorerOpen, setFileExplorerOpen] = useState(false);
    const [fileExplorerIndex, setFileExplorerIndex] = useState<number | null>(null);

    const { data: existingWorkflow, isLoading } = useQuery({
        queryKey: ["workflow", id],
        queryFn: () => id ? getWorkflow(id) : Promise.resolve(null),
        enabled: !!id,
    });

    const form = useForm<z.infer<typeof workflowSchema>>({
        resolver: zodResolver(workflowSchema) as any,
        defaultValues: {
            id: undefined,
            name: "",
            description: "",
            user_intent: "",
            agents: [],
            teams: [],
            data_sources: [],
            steps: [],
        },
    });

    useEffect(() => {
        if (existingWorkflow) {
            console.log("Loading existing workflow:", existingWorkflow);
            form.reset({
                id: existingWorkflow.id,
                name: existingWorkflow.name,
                description: existingWorkflow.description,
                user_intent: existingWorkflow.user_intent || "",
                agents: (existingWorkflow.agents || []).map((agent: any) => ({
                    ...agent,
                    tools: agent.tools || [],
                    mcp_servers: agent.mcp_servers || [],
                    data_sources: agent.data_sources || [],
                })),
                teams: existingWorkflow.teams || [],
                data_sources: existingWorkflow.data_sources || [],
                steps: existingWorkflow.steps || [],
            });
        }
    }, [existingWorkflow, form]);

    const { fields: agentFields, append: appendAgent, remove: removeAgent } = useFieldArray({
        control: form.control,
        name: "agents",
    });

    const { fields: dsFields, append: appendDs, remove: removeDs } = useFieldArray({
        control: form.control,
        name: "data_sources",
    });

    const { fields: stepFields, append: appendStep, remove: removeStep } = useFieldArray({
        control: form.control,
        name: "steps",
    });

    const { fields: teamFields, append: appendTeam, remove: removeTeam } = useFieldArray({
        control: form.control,
        name: "teams",
    });

    const handleAutoPlan = async () => {
        let intent = form.getValues("user_intent");
        if (!intent) return;

        // Append existing data sources to the intent so the planner knows about them
        const currentDataSources = form.getValues("data_sources");
        if (currentDataSources && currentDataSources.length > 0) {
            const filePaths = currentDataSources
                .filter(ds => ds.path)
                .map(ds => `@[${ds.path}]`)
                .join(", ");
            if (filePaths) {
                intent += `\n\nUse the following files: ${filePaths}`;
            }
        }

        setIsPlanning(true);
        try {
            const plan = await createPlan(intent);
            form.reset(plan);
        } catch (error) {
            console.error("Planning failed", error);
        } finally {
            setIsPlanning(false);
        }
    };

    const onSubmit = async (values: z.infer<typeof workflowSchema>) => {
        console.log("Submitting form:", values);
        try {
            await createWorkflow(values);
            console.log("Workflow saved successfully");
            router.push("/");
        } catch (error) {
            console.error("Failed to save", error);
        }
    };

    const onError = (errors: any) => {
        console.error("Form validation errors:", JSON.stringify(errors, null, 2));
    };

    const openFileExplorer = (index: number) => {
        setFileExplorerIndex(index);
        setFileExplorerOpen(true);
    };

    const handleFileSelect = (path: string) => {
        if (fileExplorerIndex !== null) {
            form.setValue(`data_sources.${fileExplorerIndex}.path` as any, path);
        }
    };

    return (
        <div className="container mx-auto p-8 max-w-4xl">
            <div className="flex justify-between items-center mb-8">
                <h1 className="text-3xl font-bold">Workflow Builder</h1>
                <Button onClick={handleAutoPlan} disabled={isPlanning || !form.watch("user_intent")}>
                    {isPlanning && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Auto-Plan with AI
                </Button>
            </div>

            <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit, onError)} className="space-y-8">
                    {/* Hidden ID field to ensure it's passed on submit */}
                    <FormField control={form.control} name={"id" as any} render={({ field }) => (
                        <input type="hidden" {...field} value={field.value ? String(field.value) : ""} />
                    )} />

                    <Card>
                        <CardHeader><CardTitle>Basic Info</CardTitle></CardHeader>
                        <CardContent className="space-y-4">
                            <FormField control={form.control} name="name" render={({ field }) => (
                                <FormItem><FormLabel>Name</FormLabel><FormControl><Input {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="description" render={({ field }) => (
                                <FormItem><FormLabel>Description</FormLabel><FormControl><Textarea {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="user_intent" render={({ field }) => (
                                <FormItem><FormLabel>User Intent (Prompt)</FormLabel><FormControl><Textarea {...field} placeholder="Describe what you want to do..." /></FormControl><FormMessage /></FormItem>
                            )} />
                        </CardContent>
                    </Card>

                    <Tabs defaultValue="agents">
                        <TabsList>
                            <TabsTrigger value="agents">Agents ({agentFields.length})</TabsTrigger>
                            <TabsTrigger value="teams">Teams ({teamFields.length})</TabsTrigger>
                            <TabsTrigger value="data">Data Sources ({dsFields.length})</TabsTrigger>
                            <TabsTrigger value="steps">Steps ({stepFields.length})</TabsTrigger>
                        </TabsList>

                        <TabsContent value="agents" className="space-y-4">
                            {agentFields.map((field, index) => (
                                <Card key={field.id}>
                                    <CardContent className="pt-6 space-y-4 relative">
                                        <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => removeAgent(index)}><Trash className="h-4 w-4" /></Button>
                                        <div className="grid grid-cols-2 gap-4">
                                            <FormField control={form.control} name={`agents.${index}.name`} render={({ field }) => (
                                                <FormItem><FormLabel>Name</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                            )} />
                                            <FormField control={form.control} name={`agents.${index}.role`} render={({ field }) => (
                                                <FormItem><FormLabel>Role</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                            )} />
                                        </div>
                                        <FormField control={form.control} name={`agents.${index}.instructions`} render={({ field }) => (
                                            <FormItem><FormLabel>Instructions</FormLabel><FormControl><Textarea {...field} /></FormControl></FormItem>
                                        )} />
                                        <FormField control={form.control} name={`agents.${index}.tools`} render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>Tools (comma separated)</FormLabel>
                                                <FormControl>
                                                    <Input
                                                        {...field}
                                                        value={field.value?.join(", ") || ""}
                                                        onChange={(e) => field.onChange(e.target.value.split(",").map(s => s.trim()).filter(Boolean))}
                                                        placeholder="duckduckgo, yfinance"
                                                    />
                                                </FormControl>
                                            </FormItem>
                                        )} />

                                        {/* Data Source Selection for Agent */}
                                        <FormField control={form.control} name={`agents.${index}.data_sources`} render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>Data Sources</FormLabel>
                                                <FormControl>
                                                    <div className="space-y-2 border p-2 rounded-md">
                                                        {dsFields.map((ds, dsIndex) => (
                                                            <div key={ds.id} className="flex items-center gap-2">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={field.value?.includes(ds.id || "")}
                                                                    onChange={(e) => {
                                                                        const current = field.value || [];
                                                                        if (e.target.checked) {
                                                                            field.onChange([...current, ds.id]);
                                                                        } else {
                                                                            field.onChange(current.filter(id => id !== ds.id));
                                                                        }
                                                                    }}
                                                                />
                                                                <span>{form.watch(`data_sources.${dsIndex}.name`) || "Unnamed Data Source"}</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </FormControl>
                                            </FormItem>
                                        )} />

                                    </CardContent>
                                </Card>
                            ))}
                            <Button type="button" variant="outline" onClick={() => appendAgent({ id: crypto.randomUUID(), name: "New Agent", role: "Assistant", instructions: "", model_name: "gpt-4o", tools: [], mcp_servers: [], data_sources: [] })}>
                                <Plus className="mr-2 h-4 w-4" /> Add Agent
                            </Button>
                        </TabsContent>

                        <TabsContent value="teams" className="space-y-4">
                            {teamFields.map((field, index) => (
                                <Card key={field.id}>
                                    <CardContent className="pt-6 space-y-4 relative">
                                        <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => removeTeam(index)}><Trash className="h-4 w-4" /></Button>
                                        <FormField control={form.control} name={`teams.${index}.name`} render={({ field }) => (
                                            <FormItem><FormLabel>Team Name</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                        )} />
                                        <FormField control={form.control} name={`teams.${index}.instructions`} render={({ field }) => (
                                            <FormItem><FormLabel>Instructions</FormLabel><FormControl><Textarea {...field} /></FormControl></FormItem>
                                        )} />
                                        <FormField control={form.control} name={`teams.${index}.member_agent_ids`} render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>Member Agents (IDs)</FormLabel>
                                                <FormControl>
                                                    <div className="space-y-2 border p-2 rounded-md">
                                                        {agentFields.map((agent, agentIndex) => {
                                                            return (
                                                                <div key={agent.id} className="flex items-center gap-2">
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={field.value?.includes(agent.id || "")}
                                                                        onChange={(e) => {
                                                                            const current = field.value || [];
                                                                            if (e.target.checked) {
                                                                                field.onChange([...current, agent.id]);
                                                                            } else {
                                                                                field.onChange(current.filter(id => id !== agent.id));
                                                                            }
                                                                        }}
                                                                    />
                                                                    <span>{form.watch(`agents.${agentIndex}.name`) || "Unnamed Agent"}</span>
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                </FormControl>
                                            </FormItem>
                                        )} />
                                    </CardContent>
                                </Card>
                            ))}
                            <Button type="button" variant="outline" onClick={() => appendTeam({ id: crypto.randomUUID(), name: "New Team", member_agent_ids: [], instructions: "", model_name: "gpt-4o" })}>
                                <Plus className="mr-2 h-4 w-4" /> Add Team
                            </Button>
                        </TabsContent>

                        <TabsContent value="data" className="space-y-4">
                            {dsFields.map((field, index) => (
                                <Card key={field.id}>
                                    <CardContent className="pt-6 space-y-4 relative">
                                        <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => removeDs(index)}><Trash className="h-4 w-4" /></Button>
                                        <div className="grid grid-cols-2 gap-4">
                                            <FormField control={form.control} name={`data_sources.${index}.name`} render={({ field }) => (
                                                <FormItem><FormLabel>Name</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                            )} />
                                            <FormField control={form.control} name={`data_sources.${index}.type`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>Type</FormLabel>
                                                    <Select onValueChange={field.onChange} value={field.value}>
                                                        <FormControl>
                                                            <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                                                        </FormControl>
                                                        <SelectContent>
                                                            <SelectItem value="file">File</SelectItem>
                                                            <SelectItem value="database">Database</SelectItem>
                                                            <SelectItem value="mcp_server">MCP Server</SelectItem>
                                                        </SelectContent>
                                                    </Select>
                                                </FormItem>
                                            )} />
                                        </div>

                                        {/* Conditional Fields based on Type */}
                                        {form.watch(`data_sources.${index}.type`) === "database" && (
                                            <div className="space-y-4">
                                                <FormField control={form.control} name={`data_sources.${index}.connection_string`} render={({ field }) => (
                                                    <FormItem><FormLabel>Connection String (DB)</FormLabel><FormControl><Input {...field} value={field.value || ""} placeholder="postgresql://user:pass@localhost:5432/db" /></FormControl></FormItem>
                                                )} />
                                                <div className="text-xs text-muted-foreground font-medium text-center uppercase tracking-wider">- OR -</div>
                                                <FormField control={form.control} name={`data_sources.${index}.path`} render={({ field }) => (
                                                    <FormItem>
                                                        <FormLabel>Local Database File (SQLite/DuckDB)</FormLabel>
                                                        <div className="flex gap-2">
                                                            <FormControl><Input {...field} value={field.value || ""} placeholder="/path/to/local.db" /></FormControl>
                                                            <Button type="button" variant="outline" size="icon" onClick={() => openFileExplorer(index)}>
                                                                <FolderOpen className="h-4 w-4" />
                                                            </Button>
                                                        </div>
                                                    </FormItem>
                                                )} />
                                            </div>
                                        )}

                                        {form.watch(`data_sources.${index}.type`) === "file" && (
                                            <FormField control={form.control} name={`data_sources.${index}.path`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>File Path</FormLabel>
                                                    <div className="flex gap-2">
                                                        <FormControl><Input {...field} value={field.value || ""} /></FormControl>
                                                        <Button type="button" variant="outline" size="icon" onClick={() => openFileExplorer(index)}>
                                                            <FolderOpen className="h-4 w-4" />
                                                        </Button>
                                                    </div>
                                                </FormItem>
                                            )} />
                                        )}

                                        {form.watch(`data_sources.${index}.type`) === "mcp_server" && (
                                            <FormField control={form.control} name={`data_sources.${index}.url`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>MCP Server URL (HTTP/SSE)</FormLabel>
                                                    <FormControl><Input {...field} placeholder="http://localhost:8000/sse" value={field.value || ""} /></FormControl>
                                                </FormItem>
                                            )} />
                                        )}

                                    </CardContent>
                                </Card>
                            ))}
                            <Button type="button" variant="outline" onClick={() => appendDs({ name: "New Data", type: "file", connection_string: "", path: "", url: "" })}>
                                <Plus className="mr-2 h-4 w-4" /> Add Data Source
                            </Button>
                        </TabsContent>

                        <TabsContent value="steps" className="space-y-4">
                            {stepFields.map((field, index) => (
                                <Card key={field.id}>
                                    <CardContent className="pt-6 space-y-4 relative">
                                        <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => removeStep(index)}><Trash className="h-4 w-4" /></Button>
                                        <div className="grid grid-cols-2 gap-4">
                                            <FormField control={form.control} name={`steps.${index}.name`} render={({ field }) => (
                                                <FormItem><FormLabel>Step Name</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                            )} />
                                            <FormField control={form.control} name={`steps.${index}.type`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>Type</FormLabel>
                                                    <Select onValueChange={field.onChange} value={field.value}>
                                                        <FormControl>
                                                            <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                                                        </FormControl>
                                                        <SelectContent>
                                                            <SelectItem value="agent_call">Agent Call</SelectItem>
                                                            <SelectItem value="team_call">Team Call</SelectItem>
                                                            <SelectItem value="user_confirmation">User Confirmation</SelectItem>
                                                            <SelectItem value="tool_call">Tool Call</SelectItem>
                                                        </SelectContent>
                                                    </Select>
                                                </FormItem>
                                            )} />
                                        </div>

                                        {/* Conditional Agent/Team Selection */}
                                        {form.watch(`steps.${index}.type`) === "agent_call" && (
                                            <FormField control={form.control} name={`steps.${index}.agent_id`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>Agent</FormLabel>
                                                    <Select onValueChange={field.onChange} value={field.value || undefined}>
                                                        <FormControl>
                                                            <SelectTrigger><SelectValue placeholder="Select agent" /></SelectTrigger>
                                                        </FormControl>
                                                        <SelectContent>
                                                            {agentFields.map((agent, i) => (
                                                                <SelectItem key={agent.id} value={agent.id || `agent-${i}`}>
                                                                    {form.watch(`agents.${i}.name`) || "Unnamed Agent"}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                </FormItem>
                                            )} />
                                        )}

                                        {form.watch(`steps.${index}.type`) === "team_call" && (
                                            <FormField control={form.control} name={`steps.${index}.team_id`} render={({ field }) => (
                                                <FormItem>
                                                    <FormLabel>Team</FormLabel>
                                                    <Select onValueChange={field.onChange} value={field.value || undefined}>
                                                        <FormControl>
                                                            <SelectTrigger><SelectValue placeholder="Select team" /></SelectTrigger>
                                                        </FormControl>
                                                        <SelectContent>
                                                            {teamFields.map((team, i) => (
                                                                <SelectItem key={team.id} value={team.id || `team-${i}`}>
                                                                    {form.watch(`teams.${i}.name`) || "Unnamed Team"}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                </FormItem>
                                            )} />
                                        )}

                                        <FormField control={form.control} name={`steps.${index}.input_template`} render={({ field }) => (
                                            <FormItem><FormLabel>Input Template</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                        )} />
                                        <FormField control={form.control} name={`steps.${index}.output_key`} render={({ field }) => (
                                            <FormItem><FormLabel>Output Key</FormLabel><FormControl><Input {...field} /></FormControl></FormItem>
                                        )} />
                                    </CardContent>
                                </Card>
                            ))}
                            <Button type="button" variant="outline" onClick={() => appendStep({ id: crypto.randomUUID(), name: "New Step", type: "agent_call", input_template: "{input}", output_key: "result" })}>
                                <Plus className="mr-2 h-4 w-4" /> Add Step
                            </Button>
                        </TabsContent>
                    </Tabs>

                    <div className="flex justify-end gap-4">
                        <Button type="button" variant="outline" onClick={() => router.push("/")}>Cancel</Button>
                        <Button type="submit">Save Workflow</Button>
                    </div>
                </form>
            </Form>

            <FileExplorer
                open={fileExplorerOpen}
                onOpenChange={setFileExplorerOpen}
                onSelect={handleFileSelect}
            />
        </div>
    );
}
