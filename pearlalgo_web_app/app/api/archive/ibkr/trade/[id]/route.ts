import { NextResponse } from 'next/server'
import { spawn } from 'child_process'
import path from 'path'
import fs from 'fs'

function findProjectRoot(): string {
  let dir = process.cwd()
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, 'scripts', 'export_archive_ibkr.py'))) return dir
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return path.resolve(process.cwd(), '..')
}

const PROJECT_ROOT = findProjectRoot()

function runSingleTrade(tradeId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(PROJECT_ROOT, 'scripts', 'export_archive_ibkr.py')
    const proc = spawn('python3', [scriptPath, 'trade', tradeId], { cwd: PROJECT_ROOT })
    let stdout = ''
    proc.stdout.on('data', (chunk) => { stdout += chunk.toString() })
    proc.on('close', (code) => {
      if (code === 0) resolve(stdout)
      else reject(new Error(`Not found`))
    })
  })
}

export async function GET(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const id = params?.id
  if (!id) {
    return NextResponse.json({ error: 'Missing trade ID' }, { status: 400 })
  }
  try {
    const raw = await runSingleTrade(id)
    const data = JSON.parse(raw)
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ error: 'Trade not found' }, { status: 404 })
  }
}
