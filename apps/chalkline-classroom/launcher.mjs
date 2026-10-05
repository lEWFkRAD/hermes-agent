import { spawn } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'
import { resolve, join } from 'node:path'
const args = process.argv.slice(2)
const at = args.indexOf('--source')
const configured = at >= 0 ? args.splice(at, 2)[1] : process.env.CHALKLINE_CLASSROOM_ROOT
if (!configured) throw new Error('Set --source to the classroom directory in your onyx-chalkline checkout. See README.md.')
const source = resolve(configured), manifest = join(source, 'package.json')
if (!existsSync(manifest)) throw new Error('The selected classroom source has no package.json.')
const pkg = JSON.parse(readFileSync(manifest, 'utf8').replace(/^\uFEFF/, ''))
if (pkg.name !== 'chalkline-classroom' || pkg.chalklineApiVersion !== 2)
  throw new Error('This desktop requires the Chalkline classroom API v2 release from onyx-chalkline.')
const child = spawn(process.execPath, [join(source, 'server.mjs'), ...args], { cwd: source, stdio: 'inherit', windowsHide: true })
child.on('error', error => { console.error(error.message); process.exitCode = 1 })
child.on('exit', code => { process.exitCode = code ?? 1 })
process.once('SIGINT', () => child.kill('SIGINT'))
process.once('SIGTERM', () => child.kill('SIGTERM'))
