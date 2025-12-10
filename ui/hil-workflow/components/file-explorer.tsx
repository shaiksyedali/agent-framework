"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Folder, File, ArrowUp, Loader2, Plus } from "lucide-react";

interface FileExplorerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSelect: (path: string) => void;
}

interface FileItem {
    name: string;
    path: string;
    is_dir: boolean;
    size: number;
}

export function FileExplorer({ open, onOpenChange, onSelect }: FileExplorerProps) {
    const [currentPath, setCurrentPath] = useState(".");
    const [items, setItems] = useState<FileItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        if (open) {
            loadFiles(currentPath);
        }
    }, [open, currentPath]);

    const loadFiles = async (path: string) => {
        setLoading(true);
        setError("");
        try {
            const res = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error("Failed to list files");
            const data = await res.json();

            // Sort: Directories first, then files
            data.sort((a: FileItem, b: FileItem) => {
                if (a.is_dir === b.is_dir) return a.name.localeCompare(b.name);
                return a.is_dir ? -1 : 1;
            });
            setItems(data);
        } catch (err) {
            console.error(err);
            setError("Failed to load files");
        } finally {
            setLoading(false);
        }
    };

    const handleNavigate = (path: string) => {
        setCurrentPath(path);
    };

    const handleUp = () => {
        if (currentPath === "." || currentPath === "/") return;
        // Handle both Windows and Unix separators for simple navigation
        const separator = currentPath.includes("\\") ? "\\" : "/";
        const parts = currentPath.split(separator);
        parts.pop();
        const newPath = parts.join(separator) || ".";
        setCurrentPath(newPath);
    };

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files || e.target.files.length === 0) return;

        const file = e.target.files[0];
        setUploading(true);
        try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("path", currentPath);

            const res = await fetch("/api/files", {
                method: "POST",
                body: formData,
            });

            if (!res.ok) throw new Error("Upload failed");

            await loadFiles(currentPath); // Refresh list
        } catch (err) {
            console.error(err);
            setError("Failed to upload file");
        } finally {
            setUploading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl h-[80vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle>Select Database File</DialogTitle>
                </DialogHeader>

                <div className="flex items-center gap-2 mb-2 justify-between">
                    <div className="flex items-center gap-2 flex-1">
                        <Button variant="outline" size="icon" onClick={handleUp} disabled={currentPath === "."}>
                            <ArrowUp className="h-4 w-4" />
                        </Button>
                        <div className="flex-1 p-2 bg-muted rounded text-sm font-mono truncate border">
                            {currentPath}
                        </div>
                    </div>
                    <div className="relative">
                        <input
                            type="file"
                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                            onChange={handleUpload}
                            disabled={uploading}
                            accept=".db,.sqlite,.duckdb"
                        />
                        <Button variant="secondary" disabled={uploading} className="shadow-sm">
                            {uploading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
                            Upload DB
                        </Button>
                    </div>
                </div>

                <ScrollArea className="flex-1 border rounded-md p-2 h-full">
                    {loading ? (
                        <div className="flex justify-center p-8"><Loader2 className="animate-spin text-muted-foreground" /></div>
                    ) : error ? (
                        <div className="text-destructive p-4 text-center bg-destructive/10 rounded-md">{error}</div>
                    ) : (
                        <div className="space-y-1">
                            {items.map((item) => (
                                <div
                                    key={item.path}
                                    className="flex items-center gap-2 p-2 hover:bg-accent hover:text-accent-foreground rounded-md cursor-pointer transition-colors"
                                    onClick={() => {
                                        if (item.is_dir) {
                                            handleNavigate(item.path);
                                        } else {
                                            onSelect(item.path);
                                            onOpenChange(false);
                                        }
                                    }}
                                >
                                    {item.is_dir ? (
                                        <Folder className="h-4 w-4 text-primary fill-primary/20" />
                                    ) : (
                                        <File className="h-4 w-4 text-muted-foreground" />
                                    )}
                                    <span className="text-sm flex-1 truncate font-medium">{item.name}</span>
                                    {!item.is_dir && (
                                        <span className="text-xs text-muted-foreground/70 font-mono">
                                            {(item.size / 1024).toFixed(1)} KB
                                        </span>
                                    )}
                                </div>
                            ))}
                            {items.length === 0 && (
                                <div className="text-center text-muted-foreground p-8 flex flex-col items-center gap-2">
                                    <Folder className="h-8 w-8 opacity-20" />
                                    <span>Empty directory</span>
                                </div>
                            )}
                        </div>
                    )}
                </ScrollArea>
            </DialogContent>
        </Dialog>
    );
}
