import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { renderVideo } from '../media.mjs'
import { seedLesson } from '../lesson.mjs'
const dir = fileURLToPath(new URL('../artifacts/media/', import.meta.url))
await mkdir(dir, { recursive: true })
const asset = await renderVideo(seedLesson, 1, dir, {
  ffmpeg: process.env.CHALKLINE_FFMPEG || 'ffmpeg',
  powershell: process.env.CHALKLINE_POWERSHELL || 'powershell.exe'
})
console.log('Rendered real narrated video, captions and transcript:', asset)
