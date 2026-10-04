import { DatabaseSync } from 'node:sqlite'
import { randomBytes, createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { seedLesson, publicLesson, validateLesson } from './lesson.mjs'
export const hash = value => createHash('sha256').update(value).digest('hex')
export class ClassroomStore {
  constructor(dir) {
    mkdirSync(dir, { recursive: true })
    const accessPath = join(dir, 'access.json')
    if (!existsSync(accessPath)) {
      const token = () => randomBytes(32).toString('base64url')
      writeFileSync(
        accessPath,
        JSON.stringify(
          {
            teacher: token(),
            students: [
              { id: 'maya', name: 'Maya B.', token: token() },
              { id: 'eli', name: 'Eli R.', token: token() },
              { id: 'luis', name: 'Luis S.', token: token() },
              { id: 'ava', name: 'Ava H.', token: token() }
            ]
          },
          null,
          2
        ),
        { mode: 0o600, flag: 'wx' }
      )
    }
    this.access = JSON.parse(readFileSync(accessPath, 'utf8'))
    this.db = new DatabaseSync(join(dir, 'classroom.sqlite'))
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS draft(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, body TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, revision INTEGER NOT NULL, due TEXT NOT NULL, mode TEXT NOT NULL, created TEXT NOT NULL, media TEXT);
      CREATE TABLE IF NOT EXISTS memberships(assignment TEXT NOT NULL REFERENCES assignments(id), student TEXT NOT NULL, PRIMARY KEY(assignment,student));
      CREATE TABLE IF NOT EXISTS work(assignment TEXT NOT NULL, student TEXT NOT NULL, answer INTEGER, reasoning TEXT NOT NULL DEFAULT '', submitted TEXT, feedback TEXT NOT NULL DEFAULT '', PRIMARY KEY(assignment,student), FOREIGN KEY(assignment,student) REFERENCES memberships(assignment,student));
      CREATE TABLE IF NOT EXISTS help(id TEXT PRIMARY KEY, assignment TEXT NOT NULL, student TEXT NOT NULL, question TEXT NOT NULL, reply TEXT NOT NULL, engine TEXT NOT NULL, topic TEXT NOT NULL, created TEXT NOT NULL, FOREIGN KEY(assignment,student) REFERENCES memberships(assignment,student));
      CREATE TABLE IF NOT EXISTS media(revision INTEGER PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL, asset TEXT);
    `)
    this.db.prepare('INSERT OR IGNORE INTO draft VALUES(1,1,?)').run(JSON.stringify(seedLesson))
  }
  principal(token) {
    if (!token) return null
    const digest = hash(token)
    if (digest === hash(this.access.teacher)) return { role: 'teacher', id: 'teacher', name: 'Jamie' }
    const s = this.access.students.find(s => hash(s.token) === digest)
    return s ? { role: 'student', id: s.id, name: s.name } : null
  }
  draft() {
    const row = this.db.prepare('SELECT * FROM draft WHERE id=1').get()
    return { revision: row.revision, lesson: JSON.parse(row.body) }
  }
  save(lesson, revision) {
    const body = JSON.stringify(validateLesson(lesson))
    const result = this.db
      .prepare('UPDATE draft SET body=?,revision=revision+1 WHERE id=1 AND revision=?')
      .run(body, revision)
    if (!result.changes)
      throw Object.assign(new Error('This draft changed in another window. Reload before saving.'), { status: 409 })
    return this.draft()
  }
  publish({ revision, students, due, mode, reviewed }) {
    const draft = this.draft()
    if (reviewed !== true || draft.revision !== revision)
      throw Object.assign(new Error('Preview and approve the current saved version first.'), { status: 409 })
    if (!Array.isArray(students) || !students.length || students.some(s => !this.access.students.some(p => p.id === s)))
      throw new Error('Choose valid demo students.')
    if (!['hints', 'examples', 'teacher'].includes(mode)) throw new Error('Choose an assistance level.')
    if (
      typeof due !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(due) ||
      Number.isNaN(Date.parse(due)) ||
      new Date(due).toISOString().slice(0, 10) !== due
    )
      throw new Error('Choose a due date.')
    const id = randomUUID()
    const media =
      this.db.prepare("SELECT asset FROM media WHERE revision=? AND status='ready'").get(revision)?.asset || null
    this.db.exec('BEGIN IMMEDIATE')
    try {
      this.db
        .prepare('INSERT INTO assignments VALUES(?,?,?,?,?,?,?,?)')
        .run(id, draft.lesson.title, JSON.stringify(draft.lesson), revision, due, mode, new Date().toISOString(), media)
      const add = this.db.prepare('INSERT INTO memberships VALUES(?,?)')
      for (const s of new Set(students)) add.run(id, s)
      this.db.exec('COMMIT')
    } catch (e) {
      this.db.exec('ROLLBACK')
      throw e
    }
    return { id }
  }
  assignment(id, principal) {
    const row = this.db.prepare('SELECT * FROM assignments WHERE id=?').get(id)
    if (
      !row ||
      (principal.role !== 'teacher' &&
        !this.db.prepare('SELECT 1 FROM memberships WHERE assignment=? AND student=?').get(id, principal.id))
    )
      throw Object.assign(new Error('Assignment not found.'), { status: 404 })
    return { ...row, lesson: JSON.parse(row.body) }
  }
  state(p) {
    const list = this.db
      .prepare(
        p.role === 'teacher'
          ? 'SELECT * FROM assignments ORDER BY created DESC'
          : 'SELECT a.* FROM assignments a JOIN memberships m ON a.id=m.assignment WHERE m.student=? ORDER BY a.created DESC'
      )
      .all(...(p.role === 'teacher' ? [] : [p.id]))
    const assignments = list.map(a => ({
      id: a.id,
      title: a.title,
      revision: a.revision,
      due: a.due,
      mode: a.mode,
      created: a.created,
      media: a.media,
      lesson: publicLesson(JSON.parse(a.body)),
      work: this.db
        .prepare('SELECT * FROM work WHERE assignment=?' + (p.role === 'teacher' ? '' : ' AND student=?'))
        .all(...(p.role === 'teacher' ? [a.id] : [a.id, p.id])),
      help: this.db
        .prepare(
          'SELECT * FROM help WHERE assignment=?' + (p.role === 'teacher' ? '' : ' AND student=?') + ' ORDER BY created'
        )
        .all(...(p.role === 'teacher' ? [a.id] : [a.id, p.id])),
      answerKey: p.role === 'teacher' ? JSON.parse(a.body).correctIndex : undefined,
      teacherNotes: p.role === 'teacher' ? JSON.parse(a.body).teacherNotes : undefined,
      students:
        p.role === 'teacher'
          ? this.db
              .prepare('SELECT student FROM memberships WHERE assignment=?')
              .all(a.id)
              .map(s => s.student)
          : undefined
    }))
    return {
      user: p,
      assignments,
      ...(p.role === 'teacher'
        ? {
            draft: this.draft(),
            students: this.access.students.map(({ id, name }) => ({ id, name })),
            media: this.db.prepare('SELECT * FROM media ORDER BY revision DESC LIMIT 8').all()
          }
        : {})
    }
  }
  saveWork(p, { assignmentId, answer, reasoning, submit }) {
    this.assignment(assignmentId, p)
    if (answer !== null && (!Number.isInteger(answer) || answer < 0 || answer > 2))
      throw new Error('Choose one answer.')
    if (typeof reasoning !== 'string' || reasoning.length > 3000)
      throw new Error('Keep your explanation under 3,000 characters.')
    if (submit && (answer === null || !reasoning.trim()))
      throw new Error('Choose an answer and explain your thinking before submitting.')
    const old = this.db.prepare('SELECT submitted FROM work WHERE assignment=? AND student=?').get(assignmentId, p.id)
    if (old?.submitted)
      throw Object.assign(new Error('Already submitted. Your teacher can review this work.'), { status: 409 })
    this.db
      .prepare(
        `INSERT INTO work(assignment,student,answer,reasoning,submitted) VALUES(?,?,?,?,?)
      ON CONFLICT(assignment,student) DO UPDATE SET answer=excluded.answer,reasoning=excluded.reasoning,submitted=excluded.submitted`
      )
      .run(assignmentId, p.id, answer, reasoning, submit ? new Date().toISOString() : null)
    return { saved: true }
  }
  addHelp(p, assignment, question, result) {
    const row = { id: randomUUID(), assignment, student: p.id, question, ...result, created: new Date().toISOString() }
    this.db
      .prepare('INSERT INTO help VALUES(?,?,?,?,?,?,?,?)')
      .run(row.id, assignment, p.id, question, row.reply, row.engine, row.topic, row.created)
    return row
  }
  feedback({ assignmentId, studentId, feedback }) {
    if (typeof feedback !== 'string' || feedback.length > 3000) throw new Error('Keep feedback under 3,000 characters.')
    const result = this.db
      .prepare('UPDATE work SET feedback=? WHERE assignment=? AND student=?')
      .run(feedback, assignmentId, studentId)
    if (!result.changes) throw Object.assign(new Error('There is no saved work for this student yet.'), { status: 404 })
    return { saved: true }
  }
  close() {
    this.db.close()
  }
}
