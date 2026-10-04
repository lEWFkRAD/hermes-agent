import { spawn } from 'node:child_process'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('.', import.meta.url))
function run(exe, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(exe, args, { cwd, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] })
    let log = ''
    child.stderr.on('data', d => {
      log = (log + d).slice(-2000)
    })
    const timeout = setTimeout(() => child.kill(), 120000)
    child.once('error', e => {
      clearTimeout(timeout)
      reject(e)
    })
    child.once('exit', code => {
      clearTimeout(timeout)
      if (code === 0) resolve()
      else reject(new Error('Media rendering failed: ' + log.slice(-400)))
    })
  })
}
function duration(wav) {
  let offset = 12,
    rate = 0,
    size = 0
  while (offset + 8 <= wav.length) {
    const tag = wav.toString('ascii', offset, offset + 4),
      len = wav.readUInt32LE(offset + 4)
    if (tag === 'fmt ') rate = wav.readUInt32LE(offset + 16)
    if (tag === 'data') size = len
    offset += 8 + len + (len % 2)
  }
  if (!rate || !size) throw new Error('Narration produced an invalid audio file.')
  return size / rate
}
function timestamp(seconds) {
  const ms = Math.round(seconds * 1000)
  return (
    [Math.floor(ms / 3600000), Math.floor(ms / 60000) % 60, Math.floor(ms / 1000) % 60]
      .map(n => String(n).padStart(2, '0'))
      .join(':') +
    '.' +
    String(ms % 1000).padStart(3, '0')
  )
}
export async function renderVideo(lesson, revision, dir, config) {
  if (process.platform !== 'win32') throw new Error('This prototype uses Windows narration.')
  const asset = 'lesson-' + revision
  const folder = join(dir, asset)
  await mkdir(folder, { recursive: true })
  let elapsed = 0
  const captions = ['WEBVTT', '']
  for (let i = 0; i < lesson.scenes.length; i++) {
    const scene = lesson.scenes[i]
    await writeFile(join(folder, 'speech.txt'), scene.narration)
    await writeFile(join(folder, 'title.txt'), scene.heading.replace(/(.{1,40})(?:\s|$)/g, '$1\n').trim())
    await writeFile(join(folder, 'label.txt'), 'One of ' + scene.denominator + ' equal parts')
    await run(
      config.powershell || 'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-File',
        join(root, 'scripts', 'narrate.ps1'),
        '-TextFile',
        join(folder, 'speech.txt'),
        '-OutputFile',
        join(folder, i + '.wav')
      ],
      folder
    )
    const seconds = duration(await readFile(join(folder, i + '.wav'))) + 1
    const width = 1056 / scene.denominator
    const boxes = Array.from(
      { length: scene.denominator },
      (_, n) =>
        'drawbox=x=' +
        Math.round(112 + n * width) +
        ':y=295:w=' +
        Math.floor(width - 4) +
        ':h=145:color=' +
        (n === 0 ? '0xe9b657' : '0xa7c8b7') +
        ':t=fill:enable=gte(t\\,' +
        n * 0.14 +
        ')'
    )
    const filter = [
      "drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':textfile=title.txt:expansion=none:fontcolor=0xf8f5eb:fontsize=42:line_spacing=12:x=112:y=100",
      ...boxes,
      "drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':textfile=label.txt:expansion=none:fontcolor=0xf8f5eb:fontsize=32:x=112:y=495",
      "drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='CHALKLINE  /  LEARN TOGETHER':fontcolor=0xa7c8b7:fontsize=20:x=112:y=620"
    ].join(',')
    await writeFile(join(folder, 'filter.txt'), filter)
    await run(
      config.ffmpeg || 'ffmpeg',
      [
        '-y',
        '-f',
        'lavfi',
        '-i',
        'color=c=0x173f38:s=1280x720:r=24',
        '-i',
        i + '.wav',
        '-vf',
        filter,
        '-af',
        'apad',
        '-t',
        String(seconds),
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-movflags',
        '+faststart',
        i + '.mp4'
      ],
      folder
    )
    captions.push(timestamp(elapsed) + ' --> ' + timestamp(elapsed + seconds), scene.narration, '')
    elapsed += seconds
  }
  await writeFile(join(folder, 'concat.txt'), lesson.scenes.map((_, i) => "file '" + i + ".mp4'").join('\n'))
  await run(
    config.ffmpeg || 'ffmpeg',
    [
      '-y',
      '-f',
      'concat',
      '-safe',
      '0',
      '-i',
      'concat.txt',
      '-c',
      'copy',
      '-movflags',
      '+faststart',
      'explanation.mp4'
    ],
    folder
  )
  await writeFile(join(folder, 'captions.vtt'), captions.join('\n'))
  await writeFile(join(folder, 'transcript.txt'), lesson.scenes.map(s => s.heading + '\n' + s.narration).join('\n\n'))
  return asset
}
