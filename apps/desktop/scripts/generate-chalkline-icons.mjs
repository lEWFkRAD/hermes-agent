#!/usr/bin/env node

import { writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { deflateSync } from 'node:zlib'

const root = resolve(import.meta.dirname, '..', 'assets')

function crc32(buffer) {
  let crc = 0xffffffff
  for (const byte of buffer) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
  }
  return (crc ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const name = Buffer.from(type)
  const length = Buffer.alloc(4)
  const checksum = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])))
  return Buffer.concat([length, name, data, checksum])
}

function png(size) {
  const rgba = Buffer.alloc(size * size * 4)
  const scale = size / 256
  const set = (x, y, color) => rgba.set(color, (y * size + x) * 4)
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      const x = (px + 0.5) / scale
      const y = (py + 0.5) / scale
      let color = [245, 242, 234, 255]
      if (x >= 49 && x <= 207 && y >= 42 && y <= 178) color = [21, 63, 58, 255]
      if (y >= 73 && y <= 85 && x >= 79 && x <= 176) color = [245, 242, 234, 255]
      if (y >= 103 && y <= 115 && x >= 79 && x <= 159) color = [245, 242, 234, 255]
      if (y >= 133 && y <= 145 && x >= 79 && x <= 130) color = [245, 242, 234, 255]
      if (Math.hypot(x - 174, y - 138) <= 9) color = [229, 184, 82, 255]
      set(px, py, color)
    }
  }
  const rows = []
  for (let y = 0; y < size; y += 1) rows.push(Buffer.from([0]), rgba.subarray(y * size * 4, (y + 1) * size * 4))
  const header = Buffer.alloc(13)
  header.writeUInt32BE(size, 0)
  header.writeUInt32BE(size, 4)
  header[8] = 8
  header[9] = 6
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(Buffer.concat(rows))), chunk('IEND', Buffer.alloc(0))])
}

function ico(images) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(1, 2)
  header.writeUInt16LE(images.length, 4)
  let offset = 6 + images.length * 16
  const entries = images.map(({ size, data }) => {
    const entry = Buffer.alloc(16)
    entry[0] = size === 256 ? 0 : size
    entry[1] = size === 256 ? 0 : size
    entry.writeUInt16LE(1, 4)
    entry.writeUInt16LE(32, 6)
    entry.writeUInt32LE(data.length, 8)
    entry.writeUInt32LE(offset, 12)
    offset += data.length
    return entry
  })
  return Buffer.concat([header, ...entries, ...images.map(image => image.data)])
}

const image = png(256)
writeFileSync(join(root, 'chalkline.png'), image)
writeFileSync(join(root, 'chalkline.ico'), ico([16, 32, 48, 64, 128, 256].map(size => ({ size, data: png(size) }))))
console.log('[chalkline] generated native icon assets')
