import { NextResponse } from 'next/server'
import { spawn } from 'child_process'
import path from 'path'

/** Project root (parent of pearlalgo_web_app) */
const PROJECT_ROOT = path.resolve(process.cwd(), '..')

function runExport(mode: string, limit?: number, offset?: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(PROJECT_ROOT, 'scripts', 'export_archive_ibkr.py')
    const args = [scriptPath, mode]
    if (mode === 'trades') {
      if (limit != null) args.push('--limit', String(limit))
      if (offset != null) args.push('--offset', String(offset))
    }
    const proc = spawn('python3', args, {
      cwd: PROJECT_ROOT,
      env: { ...process.env },
    })
    let stdout = ''
    let stderr = ''
    proc.stdout.on('data', (chunk) => { stdout += chunk.toString() })
    proc.stderr.on('data', (chunk) => { stderr += chunk.toString() })
    proc.on('close', (code) => {
      if (code === 0) resolve(stdout)
      else reject(new Error(stderr || `Script exited with code ${code}`))
    })
  })
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const mode = searchParams.get('mode') || 'summary'
  const limit = searchParams.get('limit') ? parseInt(searchParams.get('limit')!, 10) : 100
  const offset = searchParams.get('offset') ? parseInt(searchParams.get('offset')!, 10) : 0

  if (!['summary', 'trades', 'daily', 'equity', 'stats'].includes(mode)) {
    return NextResponse.json({ error: 'Invalid mode' }, { status: 400 })
  }

  try {
    const raw = await runExport(mode, limit, offset)
    const data = JSON.parse(raw)
    return NextResponse.json(data)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
