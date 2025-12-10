"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042'];

export function Visualizations({ data }: { data: any[] }) {
    if (!data || data.length === 0) return null;

    return (
        <div className="grid gap-4 md:grid-cols-2">
            {data.map((viz, index) => (
                <Card key={index} className="col-span-1">
                    <CardHeader>
                        <CardTitle>{viz.title}</CardTitle>
                    </CardHeader>
                    <CardContent className="h-[300px]">
                        <ResponsiveContainer width="100%" height="100%">
                            {viz.type === 'bar' ? (
                                <BarChart data={viz.data}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis dataKey="name" />
                                    <YAxis />
                                    <Tooltip />
                                    <Legend />
                                    <Bar dataKey="value" fill="#8884d8" />
                                </BarChart>
                            ) : viz.type === 'pie' ? (
                                <PieChart>
                                    <Pie
                                        data={viz.data}
                                        cx="50%"
                                        cy="50%"
                                        labelLine={false}
                                        outerRadius={80}
                                        fill="#8884d8"
                                        dataKey="value"
                                    >
                                        {viz.data.map((entry: any, index: number) => (
                                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                        ))}
                                    </Pie>
                                    <Tooltip />
                                    <Legend />
                                </PieChart>
                            ) : (
                                <div>Unsupported chart type: {viz.type}</div>
                            )}
                        </ResponsiveContainer>
                    </CardContent>
                </Card>
            ))}
        </div>
    );
}
