"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getWorkflows, deleteWorkflow } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Plus, Play, FileText, Trash2 } from "lucide-react";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const { data: workflows, isLoading } = useQuery({
    queryKey: ["workflows"],
    queryFn: getWorkflows,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteWorkflow,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
    },
  });

  const handleDelete = (id: string) => {
    if (confirm("Are you sure you want to delete this workflow?")) {
      deleteMutation.mutate(id);
    }
  };

  return (
    <div className="container mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Agentic Workflows</h1>
          <p className="text-muted-foreground">Manage your workflows.</p>
        </div>
        <Link href="/builder">
          <Button>
            <Plus className="mr-2 h-4 w-4" /> Create Workflow
          </Button>
        </Link>
      </div>

      {isLoading ? (
        <div>Loading...</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {workflows?.map((wf) => (
            <Card key={wf.id} className="hover:shadow-lg transition-shadow">
              <CardHeader>
                <CardTitle>{wf.name}</CardTitle>
                <CardDescription>{wf.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    {wf.agents.length} Agents
                  </div>
                </div>
              </CardContent>
              <CardFooter className="flex justify-between">
                <div className="flex gap-2">
                  <Link href={`/builder?id=${wf.id}`}>
                    <Button variant="outline">Edit</Button>
                  </Link>
                  <Button variant="destructive" size="icon" onClick={() => wf.id && handleDelete(wf.id)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <Link href={`/execute?id=${wf.id}`}>
                  <Button>
                    <Play className="mr-2 h-4 w-4" /> Run
                  </Button>
                </Link>
              </CardFooter>
            </Card>
          ))}

          {workflows?.length === 0 && (
            <div className="col-span-full text-center py-12 border-2 border-dashed rounded-lg">
              <p className="text-muted-foreground mb-4">No workflows found.</p>
              <Link href="/builder">
                <Button>Create your first Workflow</Button>
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
