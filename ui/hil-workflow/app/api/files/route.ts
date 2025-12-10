import { NextResponse } from 'next/server';
import { readdir, stat, writeFile } from 'fs/promises';
import { join, isAbsolute, resolve } from 'path';

export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const queryPath = searchParams.get('path') || '.';

    // Basic security: Prevent directory traversal outside of project for demo safety if needed
    // For this authorized local tool, we allow browsing relative to execution root.
    // We resolve the path relative to process.cwd()
    const absoluteRoot = process.cwd();
    const targetPath = resolve(absoluteRoot, queryPath);

    try {
        const files = await readdir(targetPath);
        const fileStats = await Promise.all(
            files.map(async (file) => {
                try {
                    const filePath = join(targetPath, file);
                    const stats = await stat(filePath);
                    return {
                        name: file,
                        path: join(queryPath, file).replace(/\\/g, '/'), // normalize to forward slashes for UI
                        is_dir: stats.isDirectory(),
                        size: stats.size
                    };
                } catch (e) {
                    return null;
                }
            })
        );

        const validFiles = fileStats.filter(Boolean);
        return NextResponse.json(validFiles);
    } catch (error) {
        console.error('File list error:', error);
        return NextResponse.json({ error: 'Failed to list files' }, { status: 500 });
    }
}

export async function POST(request: Request) {
    try {
        const formData = await request.formData();
        const file = formData.get('file') as File;
        const path = formData.get('path') as string || '.';

        if (!file) {
            return NextResponse.json({ error: 'No file provided' }, { status: 400 });
        }

        const bytes = await file.arrayBuffer();
        const buffer = Buffer.from(bytes);

        const targetPath = resolve(process.cwd(), path, file.name);

        await writeFile(targetPath, buffer);

        return NextResponse.json({ success: true, path: targetPath });
    } catch (error) {
        console.error('Upload error:', error);
        return NextResponse.json({ error: 'Upload failed' }, { status: 500 });
    }
}
