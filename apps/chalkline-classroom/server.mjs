import http from 'node:http'
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ClassroomStore } from './store.mjs'
import { Tutor } from './tutor.mjs'
import { lessonHtml } from './lesson.mjs'
import { renderVideo } from './media.mjs'
const root = fileURLToPath(new URL('.', import.meta.url))
const types = {
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.html': 'text/html',
  '.mp4': 'video/mp4',
  '.vtt': 'text/vtt',
  '.txt': 'text/plain'
}
const statusError = (message, status = 400) => Object.assign(new Error(message), { status })
export function createClassroom({
  dataDir = join(root, 'data'),
  config = {},
  tutor = new Tutor(config.ai),
  render = renderVideo
} = {}) {
  const store = new ClassroomStore(dataDir)
  const mediaDir = join(dataDir, 'media')
  mkdirSync(mediaDir, { recursive: true })
  // Interrupted jobs can be retried after a restart.
  store.db
    .prepare("UPDATE media SET status='error',detail='Rendering was interrupted. Try again.' WHERE status='rendering'")
    .run()
  const jobs = new Set(),
    cooldowns = new Map()
  function json(res, value, status = 200) {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(value))
  }
  async function body(req) {
    if (!String(req.headers['content-type']).startsWith('application/json')) throw statusError('JSON is required.', 415)
    let bytes = 0,
      parts = []
    for await (const chunk of req) {
      bytes += chunk.length
      if (bytes > 32768) throw statusError('Request too large.', 413)
      parts.push(chunk)
    }
    try {
      return JSON.parse(Buffer.concat(parts).toString('utf8'))
    } catch {
      throw statusError('Invalid JSON.')
    }
  }
  const teacher = p => {
    if (p.role !== 'teacher') throw statusError('Teacher access required.', 403)
  }
  const student = p => {
    if (p.role !== 'student') throw statusError('Student access required.', 403)
  }
  const server = http.createServer(async (req, res) => {
    res.setHeader('Cache-Control', 'no-store')
    res.setHeader('X-Content-Type-Options', 'nosniff')
    res.setHeader('Referrer-Policy', 'no-referrer')
    res.setHeader(
      'Content-Security-Policy',
      "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; frame-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
    )
    try {
      const localOrigin = 'http://' + req.headers.host
      if (!/^127\.0\.0\.1:\d+$/.test(req.headers.host || '')) throw statusError('Use the local classroom address.', 403)
      if (req.headers.origin && req.headers.origin !== localOrigin) throw statusError('Origin not allowed.', 403)
      const url = new URL(req.url, localOrigin),
        path = url.pathname
      if (req.method === 'GET' && path === '/health') {
        json(res, { service: 'chalkline-classroom', version: 1, mode: 'synthetic-local' })
        return
      }
      if (!path.startsWith('/api/')) {
        const routes = { '/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css' }
        if (req.method !== 'GET' || !routes[path]) throw statusError('Not found.', 404)
        const file = routes[path],
          ext = file.slice(file.lastIndexOf('.'))
        res.writeHead(200, { 'Content-Type': types[ext] + '; charset=utf-8' })
        res.end(readFileSync(join(root, 'public', file)))
        return
      }
      const p = store.principal(req.headers.authorization?.replace(/^Bearer /, ''))
      if (!p) throw statusError('Use your classroom access link to sign in.', 401)
      if (req.method === 'GET' && path === '/api/state') {
        json(res, store.state(p))
        return
      }
      if (req.method === 'GET' && path === '/api/links') {
        teacher(p)
        json(res, {
          students: store.access.students.map(s => ({
            id: s.id,
            name: s.name,
            url: localOrigin + '/#access=' + s.token
          }))
        })
        return
      }
      if (req.method === 'GET' && path === '/api/lesson-html') {
        let lesson
        if (url.searchParams.has('assignment')) lesson = store.assignment(url.searchParams.get('assignment'), p).lesson
        else {
          teacher(p)
          lesson = store.draft().lesson
        }
        res.writeHead(200, {
          'Content-Type': 'text/html; charset=utf-8',
          'Content-Disposition': 'attachment; filename="chalkline-lesson.html"'
        })
        res.end(lessonHtml(lesson))
        return
      }
      if (req.method === 'GET' && path === '/api/media-file') {
        const asset = url.searchParams.get('asset'),
          file = url.searchParams.get('file')
        if (!/^lesson-\d+$/.test(asset || '') || !['explanation.mp4', 'captions.vtt', 'transcript.txt'].includes(file))
          throw statusError('Not found.', 404)
        if (p.role !== 'teacher' && !store.state(p).assignments.some(a => a.media === asset))
          throw statusError('Not found.', 404)
        const target = join(mediaDir, asset, file)
        if (!existsSync(target)) throw statusError('Video is not ready.', 404)
        res.writeHead(200, { 'Content-Type': types[file.slice(file.lastIndexOf('.'))] })
        res.end(readFileSync(target))
        return
      }
      if (req.method !== 'POST') throw statusError('Not found.', 404)
      const data = await body(req)
      const actions = {
        '/api/lesson': () => {
          teacher(p)
          return store.save(data.lesson, data.revision)
        },
        '/api/publish': () => {
          teacher(p)
          return store.publish(data)
        },
        '/api/progress': () => {
          student(p)
          return store.saveWork(p, data)
        },
        '/api/feedback': () => {
          teacher(p)
          return store.feedback(data)
        },
        '/api/generate': async () => {
          teacher(p)
          if (typeof data.brief !== 'string' || !data.brief.trim() || data.brief.length > 1800)
            throw statusError('Describe the lesson in up to 1,800 characters.')
          try {
            return { lesson: await tutor.generate(data.brief) }
          } catch {
            throw statusError(
              'AI drafting is unavailable. You can edit the ready-made lesson and all narration below.',
              503
            )
          }
        },
        '/api/help': async () => {
          student(p)
          const assignment = store.assignment(data.assignmentId, p)
          if (typeof data.question !== 'string' || !data.question.trim() || data.question.length > 1200)
            throw statusError('Ask a question in up to 1,200 characters.')
          if (Date.now() - (cooldowns.get(p.id) || 0) < 1500)
            throw statusError('Give your helper a moment before asking again.', 429)
          cooldowns.set(p.id, Date.now())
          const history = store.db
            .prepare('SELECT question,reply FROM help WHERE assignment=? AND student=? ORDER BY created DESC LIMIT 3')
            .all(assignment.id, p.id)
            .reverse()
          const result = await tutor.help(assignment, data.question.trim(), history)
          return store.addHelp(p, assignment.id, data.question.trim(), result)
        },
        '/api/media': () => {
          teacher(p)
          const draft = store.draft()
          if (data.revision !== draft.revision)
            throw statusError('Save and reload the current lesson before making the video.', 409)
          if (jobs.size) throw statusError('A video is already rendering. Please wait.', 409)
          const existing = store.db.prepare('SELECT * FROM media WHERE revision=?').get(draft.revision)
          if (existing?.status === 'ready') return existing
          store.db
            .prepare("INSERT OR REPLACE INTO media VALUES(?,'rendering','Creating narration and animation…',NULL)")
            .run(draft.revision)
          jobs.add(draft.revision)
          render(draft.lesson, draft.revision, mediaDir, config.media || {})
            .then(asset => {
              store.db
                .prepare(
                  "UPDATE media SET status='ready',detail='Narrated video, captions and transcript ready.',asset=? WHERE revision=?"
                )
                .run(asset, draft.revision)
            })
            .catch(error => {
              console.error('Video rendering:', error.message)
              store.db
                .prepare(
                  "UPDATE media SET status='error',detail='Video rendering failed. Check the service log, then retry.' WHERE revision=?"
                )
                .run(draft.revision)
            })
            .finally(() => jobs.delete(draft.revision))
          return { status: 'rendering' }
        },
        '/api/followup': () => {
          teacher(p)
          const a = store.assignment(data.assignmentId, p)
          const questions = store.db
            .prepare('SELECT question FROM help WHERE assignment=? ORDER BY created DESC LIMIT 6')
            .all(a.id)
          if (!questions.length) throw statusError('There are no student questions for this assignment yet.')
          const lesson = {
            ...a.lesson,
            title: 'Another look: ' + a.lesson.title.slice(0, 90),
            introduction:
              'Try this together: compare two equal-sized wholes. Split one into two equal parts and one into eight. Describe what changes before returning to fourths and sixths.',
            teacherNotes:
              'Follow-up draft based on actual student questions. Review these questions and adapt the activity:\n' +
              questions
                .map(q => q.question)
                .join('\n')
                .slice(0, 1300)
          }
          return { lesson }
        }
      }
      if (!actions[path]) throw statusError('Not found.', 404)
      json(res, await actions[path]())
    } catch (error) {
      const status = error.status || 400
      json(
        res,
        {
          error:
            status >= 500 && status !== 503
              ? 'The classroom service could not finish that action. Please try again.'
              : error.message
        },
        status
      )
    }
  })
  return {
    server,
    store,
    jobs,
    listen: async (port = 5195) => {
      await new Promise((ok, fail) => {
        server.once('error', fail)
        server.listen(port, '127.0.0.1', ok)
      })
      return 'http://127.0.0.1:' + server.address().port
    },
    close: async () => {
      server.closeAllConnections()
      await new Promise(ok => server.close(ok))
      store.close()
    }
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2),
    value = (name, fallback) => {
      const n = args.indexOf(name)
      return n >= 0 ? args[n + 1] : fallback
    }
  const dataDir = resolve(value('--data', join(root, 'data')))
  const configFile = value('--config', join(dataDir, 'config.json'))
  const config = existsSync(configFile) ? JSON.parse(readFileSync(configFile, 'utf8')) : {}
  const app = createClassroom({ dataDir, config })
  const origin = await app.listen(Number(value('--port', '5195')))
  writeFileSync(
    join(dataDir, 'launch.json'),
    JSON.stringify({ origin, teacherUrl: origin + '/#access=' + app.store.access.teacher, pid: process.pid }, null, 2),
    { mode: 0o600 }
  )
  console.log('Chalkline classroom ready at ' + origin + ' (synthetic demo; access links saved privately).')
}
