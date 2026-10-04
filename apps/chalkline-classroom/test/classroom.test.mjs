import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createClassroom } from '../server.mjs'
import { seedLesson, lessonHtml } from '../lesson.mjs'
import { Tutor } from '../tutor.mjs'
async function setup(t) {
  const dir = await mkdtemp(join(tmpdir(), 'chalkline-test-'))
  const app = createClassroom({ dataDir: dir, tutor: new Tutor() })
  const origin = await app.listen(0)
  const keys = app.store.access
  const call = async (path, key, data) => {
    const response = await fetch(origin + '/api/' + path, {
      method: data === undefined ? 'GET' : 'POST',
      headers: {
        Authorization: 'Bearer ' + key,
        ...(data === undefined ? {} : { 'Content-Type': 'application/json' })
      },
      ...(data === undefined ? {} : { body: JSON.stringify(data) })
    })
    const body = await response.text()
    return {
      status: response.status,
      body: response.headers.get('content-type')?.includes('json') ? JSON.parse(body) : body
    }
  }
  t.after(async () => {
    await app.close()
    await rm(dir, { recursive: true, force: true })
  })
  return { app, call, keys, dir, origin }
}
test('published work is immutable, student scoped, teacher visible and survives a new database connection', async t => {
  const { call, keys, dir } = await setup(t)
  const teacher = keys.teacher,
    maya = keys.students[0],
    eli = keys.students[1]
  assert.equal((await call('state', 'invalid')).status, 401)
  assert.equal((await call('publish', maya.token, {})).status, 403)
  assert.equal((await call('links', maya.token)).status, 403)
  assert.equal(
    (
      await call('publish', teacher, {
        revision: 1,
        students: [maya.id],
        due: '2026-10-10',
        mode: 'hints',
        reviewed: false
      })
    ).status,
    409
  )
  const pub = await call('publish', teacher, {
    revision: 1,
    students: [maya.id],
    due: '2026-10-10',
    mode: 'hints',
    reviewed: true
  })
  assert.equal(pub.status, 200)
  const id = pub.body.id
  assert.equal(
    (await call('lesson', teacher, { revision: 1, lesson: { ...seedLesson, title: 'A new draft' } })).status,
    200
  )
  assert.equal((await call('lesson', teacher, { revision: 1, lesson: seedLesson })).status, 409)
  const m = (await call('state', maya.token)).body
  assert.equal(m.assignments[0].title, seedLesson.title)
  assert.equal(m.draft, undefined)
  assert.equal(m.students, undefined)
  assert.equal(m.assignments[0].lesson.correctIndex, undefined)
  assert.equal(m.assignments[0].lesson.teacherNotes, undefined)
  assert.equal((await call('state', eli.token)).body.assignments.length, 0)
  assert.equal((await call('lesson-html?assignment=' + id, eli.token)).status, 404)
  assert.equal((await call('help', eli.token, { assignmentId: id, question: 'Help' })).status, 404)
  assert.equal(
    (await call('progress', eli.token, { assignmentId: id, answer: 0, reasoning: 'x', submit: true })).status,
    404
  )
  const help = await call('help', maya.token, { assignmentId: id, question: 'Why are sixths smaller?' })
  assert.equal(help.status, 200)
  assert.equal(help.body.engine, 'saved-hint')
  assert.equal(
    (
      await call('progress', maya.token, {
        assignmentId: id,
        answer: 0,
        reasoning: 'Same whole, fewer pieces.',
        submit: true
      })
    ).status,
    200
  )
  assert.equal(
    (await call('progress', maya.token, { assignmentId: id, answer: 1, reasoning: 'overwrite', submit: true })).status,
    409
  )
  assert.equal(
    (
      await call('feedback', teacher, {
        assignmentId: id,
        studentId: maya.id,
        feedback: 'Show the equal wholes in your drawing.'
      })
    ).status,
    200
  )
  const teacherState = (await call('state', teacher)).body
  assert.equal(teacherState.assignments[0].help[0].question, 'Why are sixths smaller?')
  assert.equal(teacherState.assignments[0].work[0].reasoning, 'Same whole, fewer pieces.')
  const { ClassroomStore } = await import('../store.mjs')
  const reopened = new ClassroomStore(dir)
  const saved = reopened.state(reopened.principal(maya.token))
  assert.equal(saved.assignments[0].work[0].feedback, 'Show the equal wholes in your drawing.')
  assert.equal(saved.assignments[0].help.length, 1)
  reopened.close()
})
test('HTTP boundary rejects other origins and exposes no private files; generated content is escaped', async t => {
  const { origin, call, keys } = await setup(t)
  assert.equal(
    (
      await fetch(origin + '/api/state', {
        headers: { Authorization: 'Bearer ' + keys.teacher, Origin: 'https://unrelated.example' }
      })
    ).status,
    403
  )
  assert.equal((await fetch(origin + '/data/access.json')).status, 404)
  assert.equal((await call('media-file?asset=../../access&file=transcript.txt', keys.teacher)).status, 404)
  const payload = '<img src=x onerror=alert(1)>'
  const html = lessonHtml({ ...seedLesson, title: payload, teacherNotes: 'PRIVATE_NOTES' })
  assert.ok(html.includes('&lt;img'))
  assert.ok(!html.includes(payload))
  assert.ok(!html.includes('PRIVATE_NOTES'))
  assert.ok(!html.includes('correctIndex'))
  assert.equal((await call('lesson', keys.teacher, { revision: 1, lesson: { ...seedLesson, scenes: [] } })).status, 400)
  const response = await fetch(origin + '/api/lesson', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + keys.teacher, 'Content-Type': 'text/plain' },
    body: '{}'
  })
  assert.equal(response.status, 415)
})
test('teacher-only help never invokes the model and private context never enters student model messages', async () => {
  let seen
  const tutor = new Tutor()
  tutor.complete = async messages => {
    seen = messages
    return 'Compare two equal wholes. What do you notice?'
  }
  const assignment = { mode: 'teacher', lesson: seedLesson }
  const directed = await tutor.help(assignment, 'Help')
  assert.equal(directed.engine, 'teacher-request')
  assert.equal(seen, undefined)
  const reply = await tutor.help({ ...assignment, mode: 'examples' }, 'What does denominator mean?')
  assert.equal(reply.engine, 'ai')
  assert.ok(!JSON.stringify(seen).includes('correctIndex'))
  assert.ok(!JSON.stringify(seen).includes(seedLesson.teacherNotes))
  assert.ok(seen[0].content.includes('different numbers'))
})
