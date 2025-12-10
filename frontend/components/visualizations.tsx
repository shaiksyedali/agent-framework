"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042'];

type TableViz = {
    type: 'table';
    title?: string;
    columns: string[];
    rows: Array<Record<string, unknown> | unknown[]>;
};

type ChartViz = {
    type: 'bar' | 'pie' | 'line' | 'area';
    title?: string;
    data: {
        labels?: Array<string | number>;
        datasets: Array<{ label?: string; data: Array<number | string> }>;
    };
};

type Viz = TableViz | ChartViz;

export function Visualizations({ data }: { data: Viz[] }) {
    if (!data || data.length === 0) return null;

    return (
        <div className="grid gap-4 md:grid-cols-2">
            {data.map((viz, index) => (
                    <Card key={index} className="col-span-1">
                        <CardHeader>
                            <CardTitle>{viz.title || `Chart ${index + 1}`}</CardTitle>
                        </CardHeader>
                        <CardContent className={viz.type === 'table' ? "" : "h-[300px]"}>
                            {viz.type === 'bar' ? (
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={(viz.data.labels || []).map((label, idx) => {
                                        const base: Record<string, unknown> = { name: label };
                                        viz.data.datasets?.forEach((ds, i) => {
                                            base[ds.label || `value_${i}`] = ds.data?.[idx];
                                        });
                                        return base;
                                    })}>
                                        <CartesianGrid strokeDasharray="3 3" />
                                        <XAxis dataKey="name" />
                                        <YAxis />
                                        <Tooltip />
                                        <Legend />
                                        {viz.data.datasets?.map((ds, i: number) => (
                                            <Bar key={ds.label || i} dataKey={ds.label || `value_${i}`} fill={COLORS[i % COLORS.length]} />
                                        ))}
                                    </BarChart>
                                </ResponsiveContainer>
                            ) : viz.type === 'pie' ? (
                                <ResponsiveContainer width="100%" height="100%">
                                    <PieChart>
                                        <Pie
                                            data={(viz.data.labels || []).map((label, idx) => ({
                                                name: label,
                                                value: viz.data.datasets?.[0]?.data?.[idx],
                                            }))}
                                            cx="50%"
                                            cy="50%"
                                            labelLine={false}
                                            outerRadius={80}
                                            fill="#8884d8"
                                            dataKey="value"
                                        >
                                        {(viz.data.datasets?.[0]?.data || []).map((_, index: number) => (
                                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                        ))}
                                    </Pie>
                                    <Tooltip />
                                    <Legend />
                                </PieChart>
                            </ResponsiveContainer>
                        ) : viz.type === 'line' ? (
                            <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={(viz.data.labels || []).map((label, idx) => {
                                        const base: Record<string, unknown> = { name: label };
                                        viz.data.datasets?.forEach((ds, i) => {
                                            base[ds.label || `value_${i}`] = ds.data?.[idx];
                                        });
                                        return base;
                                    })}>
                                        <CartesianGrid strokeDasharray="3 3" />
                                        <XAxis dataKey="name" />
                                        <YAxis />
                                        <Tooltip />
                                        <Legend />
                                        {viz.data.datasets?.map((ds, i: number) => (
                                            <Bar key={ds.label || i} dataKey={ds.label || `value_${i}`} fill={COLORS[i % COLORS.length]} />
                                        ))}
                                    </BarChart>
                            </ResponsiveContainer>
                            ) : viz.type === 'table' ? (
                                <div className="overflow-auto border rounded-md">
                                    <table className="min-w-full text-sm">
                                        <thead className="bg-muted/50">
                                            <tr>
                                                {(viz.columns || []).map((c: string) => (
                                                    <th key={c} className="px-2 py-1 text-left font-semibold border-b">{c}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {(viz.rows || []).map((row: Record<string, unknown> | unknown[], ridx: number) => (
                                                <tr key={ridx} className="border-b last:border-0">
                                                    {(viz.columns || []).map((c: string) => (
                                                        <td key={c} className="px-2 py-1 whitespace-pre text-xs font-mono">
                                                            {Array.isArray(row) ? String((row as unknown[])[viz.columns.indexOf(c)] ?? "") : String((row as Record<string, unknown>)?.[c] ?? "")}
                                                        </td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div>Unsupported chart type: {viz.type}</div>
                            )}
                        </CardContent>
                    </Card>
            ))}
        </div>
    );
}
