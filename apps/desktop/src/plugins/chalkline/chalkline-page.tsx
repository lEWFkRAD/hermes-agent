import { host } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ConnectedClassroom } from './connected-classroom'

type View = 'classroom' | 'today' | 'plan' | 'evidence' | 'students' | 'integrations'
type Signal = 'rebuild' | 'connect' | 'extend'

interface EvidenceNote {
  id: number
  note: string
  student: string
}

const signalGroups = [
  { id: 'rebuild' as const, count: 5, label: 'Denominator meaning', students: 'Maya, Eli, Noah +2', detail: 'Treats larger denominators as larger pieces.', tone: 'coral' },
  { id: 'connect' as const, count: 4, label: 'Model → notation', students: 'Luis, Harper, Jada +1', detail: 'Builds the model correctly; reverses notation.', tone: 'gold' },
  { id: 'extend' as const, count: 9, label: 'Ready to extend', students: 'Ava, Caleb, Sofia +6', detail: 'Compares unit fractions and explains equal-size parts.', tone: 'sage' }
]

const students = [
  ['MB', 'Maya B.', 'Needs a concrete model before notation', 'Developing'],
  ['ER', 'Eli R.', 'Confuses piece size and piece count', 'Developing'],
  ['LS', 'Luis S.', 'Correct model; notation reversal', 'Approaching'],
  ['AH', 'Ava H.', 'Explains comparison with precision', 'Secure'],
  ['CJ', 'Caleb J.', 'Ready for non-unit fractions', 'Secure'],
  ['SN', 'Sofia N.', 'Uses benchmarks independently', 'Secure']
]

const integrations = [
  ['Canvas', 'LMS', 'District setup', 'Teacher-reviewed assignment packages and course context.'],
  ['Infinite Campus', 'SIS', 'CSV ready', 'Roster import and gradebook-ready evidence export.'],
  ['Clever', 'Roster & SSO', 'District setup', 'Scoped district roster and launch integration.'],
  ['ClassLink', 'Roster & SSO', 'District setup', 'OneRoster class sync through district authorization.'],
  ['OneRoster / CSV', 'Portable', 'Ready now', 'Local file handoff with no vendor credential required.']
]

function csvCell(value: string | number): string {
  const text = String(value)

  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function download(name: string, content: string, type = 'text/csv'): void {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}

export function ChalklinePage() {
  const [view, setView] = useState<View>('classroom')
  const [selected, setSelected] = useState<Signal>('rebuild')
  const [notes, setNotes] = useState<EvidenceNote[]>([])
  const [note, setNote] = useState('')
  const [student, setStudent] = useState('Whole class')
  const [roster, setRoster] = useState('Sample roster · 24 students')
  const [toast, setToast] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const group = useMemo(() => signalGroups.find(item => item.id === selected) ?? signalGroups[0], [selected])

  useEffect(() => {
    const stored = window.localStorage.getItem('chalkline.notes')

    if (stored) {
      try { setNotes(JSON.parse(stored) as EvidenceNote[]) } catch { window.localStorage.removeItem('chalkline.notes') }
    }
  }, [])

  useEffect(() => {
    window.localStorage.setItem('chalkline.notes', JSON.stringify(notes))
  }, [notes])

  useEffect(() => {
    if (!toast) {return}
    const timer = window.setTimeout(() => setToast(''), 2600)

    return () => window.clearTimeout(timer)
  }, [toast])

  function saveNote(): void {
    if (!note.trim()) {
      setToast('Add an observation first.')

      return
    }

    setNotes(current => [{ id: Date.now(), note: note.trim(), student }, ...current])
    setNote('')
    setToast('Evidence saved locally.')
  }

  function exportEvidence(): void {
    const headers = ['student_group', 'standard', 'signal', 'status', 'recommended_next_step']
    const rows = signalGroups.map(item => [item.students, '3.NF.A.1', item.label, item.id === 'extend' ? 'secure' : 'review', item.detail])
    download('chalkline-evidence.csv', [headers, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n'))
    setToast('Evidence CSV prepared.')
  }

  function exportLesson(): void {
    download('chalkline-lesson.json', JSON.stringify({ title: 'Fractions are equal parts', standard: '3.NF.A.1', releaseState: 'teacher_reviewed', groups: signalGroups }, null, 2), 'application/json')
    setToast('Teacher-reviewed lesson package prepared.')
  }

  async function importRoster(file: File | undefined): Promise<void> {
    if (!file) {return}
    const lines = (await file.text()).split(/\r?\n/).filter(line => line.trim())
    const count = Math.max(0, lines.length - 1)
    setRoster(`${file.name} · ${count} students`)
    setToast(`${count} roster rows mapped locally.`)
  }

  return (
    <main className="chalkline" data-view={view}>
      <header className="chalkline__header">
        <div>
          <p className="chalkline__eyebrow">{new Intl.DateTimeFormat(undefined, { dateStyle: 'long' }).format(new Date())} · Demo classroom</p>
          <h1>{view === 'today' ? 'Good morning, Jamie.' : view[0].toUpperCase() + view.slice(1)}</h1>
        </div>
        <div className="chalkline__privacy"><i /> Private workspace · synthetic data</div>
      </header>

      <nav aria-label="Chalkline workspace" className="chalkline__tabs">
        {(['classroom', 'today', 'plan', 'evidence', 'students', 'integrations'] as View[]).map(item => (
          <button aria-current={view === item ? 'page' : undefined} key={item} onClick={() => setView(item)} type="button">{item}</button>
        ))}
        <button className="chalkline__agent" onClick={() => host.navigate('/')} type="button">Ask teacher agent ↗</button>
      </nav>

      {view === 'classroom' && <ConnectedClassroom />}

      {view === 'today' && <section className="chalkline__content">
        <article className="chalkline__brief">
          <div><p className="chalkline__eyebrow">Your teaching brief</p><h2>Yesterday left you a clear next move.</h2><p>Nine students are ready to extend. Nine need one of two focused fraction routines before the class moves on.</p><button onClick={() => setView('plan')} type="button">Build tomorrow’s lesson →</button></div>
          <div className="chalkline__orbit"><strong>18</strong><span>exit tickets</span>{signalGroups.map(item => <button className={`tone-${item.tone}`} key={item.id} onClick={() => { setSelected(item.id); setView('evidence') }} type="button"><b>{item.count}</b>{item.id}</button>)}</div>
        </article>
        <div className="chalkline__grid">
          <article className="chalkline__panel"><p className="chalkline__eyebrow">Evidence signals</p><h3>What the work is saying</h3>{signalGroups.map(item => <button className="chalkline__signal" key={item.id} onClick={() => { setSelected(item.id); setView('evidence') }} type="button"><b className={`tone-${item.tone}`}>{item.count}</b><span><strong>{item.label}</strong><small>{item.detail}</small></span><i>↗</i></button>)}</article>
          <article className="chalkline__panel"><p className="chalkline__eyebrow">Capture evidence</p><h3>Something you noticed</h3><select aria-label="Student" onChange={event => setStudent(event.target.value)} value={student}><option>Whole class</option>{students.map(item => <option key={item[1]}>{item[1]}</option>)}</select><textarea aria-label="Evidence note" onChange={event => setNote(event.target.value)} placeholder="e.g. Eli explained the model aloud…" value={note} /><button onClick={saveNote} type="button">Save locally</button><small>{notes.length} local observation{notes.length === 1 ? '' : 's'}</small></article>
        </div>
      </section>}

      {view === 'plan' && <section className="chalkline__content"><article className="chalkline__document"><p className="chalkline__eyebrow">Teacher-reviewed draft</p><h2>Fractions are equal parts</h2><p className="chalkline__lead">Explain a unit fraction as one equal part of a whole and connect a visual model to notation.</p><div className="chalkline__pathways">{signalGroups.map((item, index) => <div key={item.id}><span>0{index + 1}</span><h3>{item.id}</h3><p>{item.count} students · {item.detail}</p></div>)}</div><footer><span>Nothing is sent to an LMS without teacher review.</span><button onClick={exportLesson} type="button">Export lesson package</button></footer></article></section>}

      {view === 'evidence' && <section className="chalkline__content chalkline__evidence"><aside>{signalGroups.map(item => <button aria-current={selected === item.id ? 'true' : undefined} key={item.id} onClick={() => setSelected(item.id)} type="button"><b className={`tone-${item.tone}`}>{item.count}</b><span>{item.label}<small>{item.students}</small></span></button>)}</aside><article className="chalkline__document"><p className="chalkline__eyebrow">Source-linked signal · 3.NF.A.1</p><h2>{group.label}</h2><p className="chalkline__lead">{group.detail}</p><div className="chalkline__quote">“The bottom number tells how many pieces we have.”<small>Exit ticket 07 · synthetic sample</small></div><h3>Recommended next move</h3><p>Use a fold-and-compare conference, then ask students to label the same whole in two representations.</p><footer><span>Teacher judgment remains authoritative.</span><button onClick={exportEvidence} type="button">Export evidence CSV</button></footer></article></section>}

      {view === 'students' && <section className="chalkline__content"><article className="chalkline__panel"><div className="chalkline__panelhead"><div><p className="chalkline__eyebrow">Roster · local handoff</p><h2>Math · Period 2</h2><small>{roster}</small></div><button onClick={() => fileInput.current?.click()} type="button">Import roster CSV</button><input accept=".csv,text/csv" className="chalkline__file" onChange={event => void importRoster(event.target.files?.[0])} ref={fileInput} type="file" /></div><div className="chalkline__studentlist">{students.map(item => <div key={item[1]}><b>{item[0]}</b><strong>{item[1]}</strong><span>{item[2]}</span><em>{item[3]}</em></div>)}</div></article></section>}

      {view === 'integrations' && <section className="chalkline__content"><article className="chalkline__integrationHero"><p className="chalkline__eyebrow">NWGA starter pack</p><h2>Meet teachers where their work already lives.</h2><p>Read broadly. Write narrowly. Release deliberately.</p></article><div className="chalkline__integrationGrid">{integrations.map(item => <article key={item[0]}><b>{item[0]}</b><small>{item[1]} · {item[2]}</small><p>{item[3]}</p><button onClick={() => setToast(item[2] === 'Ready now' || item[2] === 'CSV ready' ? 'Portable connector is ready.' : 'District authorization is required.')} type="button">Connector details</button></article>)}</div></section>}

      {toast && <div className="chalkline__toast" role="status">✓ {toast}</div>}
    </main>
  )
}
