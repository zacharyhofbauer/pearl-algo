import { NextResponse } from 'next/server'
import { spawn } from 'child_process'
import path from 'path'

const PROJECT_ROOT = path.resolve(process.cwd(), '..')

function runTrades(limit: number, offset: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(PROJECT_ROOT, 'scripts', 'export_archive_ibkr.py')
    const proc = spawn('python3', [scriptPath, 'trades', '--limit', String(limit), '--offset', String(offset)], {
      cwd: PROJECT_ROOT,
    })
    let stdout = ''
    proc.stdout.on('data', (chunk) => { stdout += chunk.toString() })
    proc.on('close', (code) => {
      if (code === 0) resolve(stdout)
      else reject(new Error(`Script exited with code ${code}`))
    })
  })
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const limit = Math.min(5000, Math.max(1, parseInt(searchParams.get('limit') || '100', 10)))
  const offset = Math.max(0, parseInt(searchParams.get('offset') || '0', 10))

  try {
    const raw = await runTrades(limit, offset)
    const data = JSON.parse(raw)
    return NextResponse.json(data)
  } catch (err) {
    return NextResponse.json({ error: 'Failed to load trades' }, { status: 500 })
  }
}
