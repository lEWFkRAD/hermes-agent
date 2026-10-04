const root = document.querySelector('#app')
const E = value =>
  String(value ?? '').replace(
    /[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  )
let token =
  new URLSearchParams(location.hash.slice(1)).get('access') || sessionStorage.getItem('chalkline-access') || ''
if (location.hash) {
  history.replaceState(null, '', location.pathname)
}
if (token) sessionStorage.setItem('chalkline-access', token)
let state,
  tab = 'overview',
  selected = '',
  working = null,
  previewed = 0,
  dirty = false,
  mediaTimer,
  blobs = []
const notice = (message, error = false) => {
  const n = document.querySelector('#notice')
  n.textContent = message
  n.classList.add('visible')
  n.setAttribute('role', error ? 'alert' : 'status')
  clearTimeout(notice.timer)
  notice.timer = setTimeout(() => n.classList.remove('visible'), 6000)
}
async function api(path, data, raw = false) {
  const response = await fetch('/api/' + path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {
      Authorization: 'Bearer ' + token,
      ...(data === undefined ? {} : { 'Content-Type': 'application/json' })
    },
    ...(data === undefined ? {} : { body: JSON.stringify(data) })
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || 'Please try again.')
  }
  return raw ? response : response.json()
}
async function load() {
  state = await api('state')
}
function button(action, text, extra = '', secondary = false) {
  return (
    '<button type="button" data-action="' +
    action +
    '" ' +
    extra +
    ' class="' +
    (secondary ? 'secondary' : '') +
    '">' +
    text +
    '</button>'
  )
}
function login() {
  root.innerHTML =
    '<main class="login"><div class="brand"><span class="brandmark">c</span>chalkline</div><p class="eyebrow">A little help. A new understanding.</p><h1>Learning starts together.</h1><p>Open the classroom link your teacher shared, or enter your access code.</p><form id="login"><label>Classroom access code<input name="code" required autocomplete="off" type="password"></label><button>Open my workspace</button></form><p class="notice-inline">Local prototype · Use the four demo students. Real student onboarding is not enabled.</p></main>'
}
function shell(content) {
  const teacher = state.user.role === 'teacher'
  const nav = teacher
    ? [
        ['overview', 'Classroom'],
        ['studio', 'Lesson Studio'],
        ['assignments', 'Assignments'],
        ['insights', 'Questions & support']
      ]
    : []
  root.innerHTML =
    '<header><div class="brand"><span class="brandmark">c</span>chalkline <span class="pill">' +
    (teacher ? 'Teacher' : 'Student') +
    '</span></div><div class="identity"><span class="pill">Demo classroom</span><span>' +
    E(state.user.name) +
    '</span>' +
    button('logout', 'Sign out', '', 'true') +
    '</div></header>' +
    (teacher
      ? '<div class="layout"><nav aria-label="Teacher workspace">' +
        nav
          .map(
            ([id, label]) =>
              '<button type="button" data-tab="' +
              id +
              '" class="' +
              (tab === id ? 'active' : '') +
              '" ' +
              (tab === id ? 'aria-current="page"' : '') +
              '>' +
              label +
              '</button>'
          )
          .join('') +
        '<div class="note"><b>Grade 3 · Fractions</b><br>Four demo learners<br><br>Create. Explore.<br>Understand together.</div></nav><main>'
      : '<main class="student-main">') +
    content +
    '</main>' +
    (teacher ? '</div>' : '')
}
function head(kicker, title, description, action = '') {
  return (
    '<div class="pagehead"><div><p class="eyebrow">' +
    kicker +
    '</p><h1>' +
    title +
    '</h1><p>' +
    description +
    '</p></div>' +
    action +
    '</div>'
  )
}
function assignmentRows() {
  return state.assignments.length
    ? state.assignments
        .map(
          a =>
            '<div class="row"><div><h3>' +
            E(a.title) +
            '</h3><small>Version ' +
            a.revision +
            ' · Due ' +
            E(a.due) +
            ' · ' +
            a.students.length +
            ' learners</small></div><div class="actions"><span class="pill">' +
            a.work.filter(w => w.submitted).length +
            ' submitted</span>' +
            button('inspect', 'Review', 'data-id="' + a.id + '"', true) +
            '</div></div>'
        )
        .join('')
    : '<div class="empty">Your first lesson is ready to make your own.<br>Open Lesson Studio, preview it, then assign it.</div>'
}
function overview() {
  const questions = state.assignments.reduce((n, a) => n + a.help.length, 0),
    submitted = state.assignments.reduce((n, a) => n + a.work.filter(w => w.submitted).length, 0)
  return (
    '<section class="hero"><div><p class="eyebrow">Your connected classroom</p><h1>Every question opens a door.</h1><p>Create an explanation, give students room to explore, and see where a little more help could make a difference.</p>' +
    button('studio', 'Make a lesson →') +
    '</div><div class="art" aria-hidden="true"><span></span><span></span><span></span><span></span></div></section>' +
    '<div class="stats"><div class="stat"><b>' +
    state.assignments.length +
    '</b><small>Published assignments</small></div><div class="stat"><b>' +
    submitted +
    '</b><small>Submitted pieces of work</small></div><div class="stat"><b>' +
    questions +
    '</b><small>Questions shared with you</small></div></div><section class="panel"><div class="pagehead"><h2>Learning in motion</h2>' +
    button('refresh', 'Refresh', '', 'true') +
    '</div>' +
    assignmentRows() +
    '</section><section class="panel"><p class="eyebrow">Try both sides</p><h2>Meet your demo learners</h2><p class="muted">Open a student in a separate tab, work through an assignment, then return here to see their questions and work.</p>' +
    studentLinks() +
    '<div class="divider">' +
    button('desktop-link', 'Copy private desktop access link', '', 'true') +
    '<p><small>Paste this into the native app’s Classroom tab to connect the same teacher workspace.</small></p><div id="desktop-link-result"></div></div></section>'
  )
}
function studentLinks() {
  return (
    state.students
      .map(
        s =>
          '<div class="row"><div><h3>' +
          E(s.name) +
          '</h3><small>Demo learner · Grade 3</small></div>' +
          button('student-link', 'Get student link', 'data-id="' + s.id + '"', true) +
          '</div>'
      )
      .join('') + '<div id="student-link-result" aria-live="polite"></div>'
  )
}
function field(name, label, value, multiline = false, type = 'text') {
  return (
    '<label>' +
    label +
    (multiline
      ? '<textarea name="' + name + '" required>' + E(value) + '</textarea>'
      : '<input name="' + name + '" type="' + type + '" value="' + E(value) + '" required>') +
    '</label>'
  )
}
function studio() {
  const l = working || state.draft.lesson,
    r = state.draft.revision,
    m = state.media.find(m => m.revision === r)
  return (
    head(
      'Lesson Studio',
      'Make understanding visible.',
      'Shape the explanation, preview it as a learner, then send a reviewed version to your class.',
      '<span class="pill" id="save-status">' + (dirty ? 'Unsaved changes' : 'Saved version ' + r) + '</span>'
    ) +
    '<div class="grid"><div><section class="panel"><p class="eyebrow">Start with an idea</p><h2>A familiar world. A new concept.</h2><form id="generate"><label>How should we explain unit fractions?<textarea name="brief" placeholder="Use a soccer field to explain why one fourth is bigger than one sixth." maxlength="1800"></textarea></label><div class="actions"><button>Draft with AI</button><small>Or edit the ready-made lesson below.</small></div></form></section>' +
    '<form id="lesson-form"><section class="panel"><h2>The lesson</h2>' +
    field('title', 'Title', l.title) +
    field('objective', 'Learning objective', l.objective, true) +
    '<div class="split">' +
    field('audience', 'Audience', l.audience) +
    field('theme', 'Theme', l.theme) +
    '</div>' +
    field('introduction', 'Opening explanation', l.introduction, true) +
    '</section><section class="panel"><p class="eyebrow">Short explanatory video</p><h2>Three scenes. One clear idea.</h2><p class="muted">Edit the script and the number of equal parts shown. Chalkline makes a narrated animation with captions.</p>' +
    l.scenes
      .map(
        (s, i) =>
          '<div class="scene"><div class="scene-number">SCENE 0' +
          (i + 1) +
          '</div><div class="split">' +
          field('heading' + i, 'Heading', s.heading) +
          field('parts' + i, 'Equal parts', s.denominator, false, 'number') +
          '</div>' +
          field('narration' + i, 'Narration', s.narration, true) +
          '</div>'
      )
      .join('') +
    '</section><section class="panel"><h2>Check understanding</h2>' +
    field('question', 'Question', l.question) +
    l.options.map((o, i) => field('option' + i, 'Choice ' + (i + 1), o)).join('') +
    '<label>Answer key · teacher only<select name="correctIndex">' +
    l.options
      .map(
        (_, i) =>
          '<option value="' + i + '" ' + (i === l.correctIndex ? 'selected' : '') + '>Choice ' + (i + 1) + '</option>'
      )
      .join('') +
    '</select></label>' +
    field('teacherNotes', 'Your private teaching notes', l.teacherNotes, true) +
    '<button>Save lesson</button></section></form></div>' +
    '<aside><section class="panel"><p class="eyebrow">Student preview</p><h2>Try the exploration.</h2><p class="muted">Preview uses saved version ' +
    r +
    '. Save your edits before reviewing.</p>' +
    button('preview', 'Preview saved lesson', '', 'true') +
    '<div id="preview-host"></div><div class="actions divider">' +
    button('export-html', 'Download HTML', '', 'true') +
    '</div></section>' +
    '<section class="panel"><p class="eyebrow">Narrated explanation</p><h2>Watch it come together.</h2><div id="media-status"><p>' +
    E(m?.detail || 'Save your script, then render the video on this computer.') +
    '</p></div><div class="actions">' +
    button('render', 'Make video', m?.status === 'rendering' ? 'disabled' : '') +
    '</div><div id="video-host"></div></section>' +
    '<section class="panel"><p class="eyebrow">Publish a reviewed version</p><h2>Who is this for?</h2><form id="publish">' +
    state.students
      .map(
        s =>
          '<label class="check"><input type="checkbox" name="students" value="' +
          s.id +
          '" checked>' +
          E(s.name) +
          '</label>'
      )
      .join('') +
    field('due', 'Due date', new Date(Date.now() + 86400000 * 3).toISOString().slice(0, 10), false, 'date') +
    '<label>Help available<select name="mode"><option value="hints">Hints and explanations</option><option value="examples">Hints and similar worked examples</option><option value="teacher">Ask the teacher only</option></select></label><label class="check"><input name="reviewed" type="checkbox" required>I reviewed this saved lesson, its answer key, and any video included.</label><p><small>Preview the saved lesson first. Published versions stay unchanged when you edit your next draft.</small></p><button>Assign lesson</button></form></section></aside></div>'
  )
}
function insights() {
  const events = state.assignments.flatMap(a => a.help.map(h => ({ ...h, title: a.title })))
  const topics = [...new Set(events.map(h => h.topic))]
  return (
    head(
      'Questions & support',
      'Listen for the next lesson.',
      'These groups come from words in students’ questions. Open the original exchanges before deciding what to reteach.',
      button('refresh', 'Refresh', '', 'true')
    ) +
    (!events.length
      ? '<section class="panel empty">Student questions will appear here after they ask for help in an assigned lesson.</section>'
      : topics
          .map(topic => {
            const list = events.filter(h => h.topic === topic)
            return (
              '<section class="panel"><div class="pagehead"><div><p class="eyebrow">' +
              new Set(list.map(h => h.student)).size +
              ' learners · ' +
              list.length +
              ' questions</p><h2>' +
              E(topic) +
              '</h2></div></div>' +
              list
                .map(
                  h =>
                    '<details><summary>' +
                    E(state.students.find(s => s.id === h.student)?.name || h.student) +
                    ' — ' +
                    E(h.question) +
                    '</summary><p class="muted">' +
                    E(h.title) +
                    ' · ' +
                    new Date(h.created).toLocaleString() +
                    '</p><div class="question"><p><b>Student</b></p><p>' +
                    E(h.question) +
                    '</p><p><b>' +
                    engineLabel(h.engine) +
                    '</b></p><p>' +
                    E(h.reply) +
                    '</p></div>' +
                    button('followup', 'Draft a follow-up lesson', 'data-id="' + h.assignment + '"', true) +
                    '</details>'
                )
                .join('') +
              '</section>'
            )
          })
          .join('')) +
    '<p class="notice-inline">Help-seeking is part of learning. Question counts are not grades, diagnoses, or ability scores.</p>'
  )
}
function assignments() {
  const a = state.assignments.find(a => a.id === selected)
  return (
    head(
      'Assignments',
      'From lesson to learning.',
      'See saved work, student reasoning, and the help they requested.',
      button('refresh', 'Refresh', '', 'true')
    ) +
    '<section class="panel">' +
    assignmentRows() +
    '</section>' +
    (a
      ? '<section class="panel"><p class="eyebrow">Version ' +
        a.revision +
        ' · ' +
        E(a.mode) +
        '</p><h2>' +
        E(a.title) +
        '</h2><p><b>Published answer key:</b> ' +
        E(a.lesson.options[a.answerKey]) +
        '</p><details><summary>Private teaching notes</summary><p>' +
        E(a.teacherNotes) +
        '</p></details>' +
        a.students
          .map(id => {
            const s = state.students.find(s => s.id === id),
              w = a.work.find(w => w.student === id),
              help = a.help.filter(h => h.student === id)
            return (
              '<details open><summary>' +
              E(s.name) +
              ' · ' +
              (w?.submitted ? 'Submitted' : w ? 'Draft saved' : 'Not started') +
              '</summary><p><b>Answer:</b> ' +
              E(w?.answer !== null && w?.answer !== undefined ? a.lesson.options[w.answer] : 'No answer yet') +
              '</p><p><b>Thinking:</b> ' +
              E(w?.reasoning || 'No explanation yet') +
              '</p><small>' +
              help.length +
              ' help questions</small>' +
              help
                .map(
                  h =>
                    '<div class="question"><b>' +
                    E(h.question) +
                    '</b><p>' +
                    E(h.reply) +
                    '</p><small>' +
                    engineLabel(h.engine) +
                    '</small></div>'
                )
                .join('') +
              (w
                ? '<form data-feedback="' +
                  id +
                  '" data-assignment="' +
                  a.id +
                  '"><label>Your feedback<textarea name="feedback" maxlength="3000">' +
                  E(w.feedback) +
                  '</textarea></label><button>Share feedback</button></form>'
                : '') +
              '</details>'
            )
          })
          .join('') +
        '</section>'
      : '')
  )
}
function engineLabel(engine) {
  return (
    {
      ai: 'AI explanation',
      'saved-hint': 'Saved lesson hint · AI unavailable',
      'teacher-request': 'Question for your teacher'
    }[engine] || 'Lesson help'
  )
}
function studentHome() {
  return (
    head(
      'Your learning space',
      'Hi, ' + E(state.user.name.split(' ')[0]) + '.',
      'A question is a good place to start. Choose a lesson and take it one step at a time.'
    ) +
    '<p class="notice-inline">Your teacher can see your work and the questions you ask for help with in these lessons.</p>' +
    (state.assignments.length
      ? state.assignments
          .map(
            a =>
              '<section class="panel divider"><p class="eyebrow">Due ' +
              E(a.due) +
              ' · ' +
              E(a.lesson.audience) +
              '</p><h2>' +
              E(a.title) +
              '</h2><p>' +
              E(a.lesson.objective) +
              '</p><div class="actions">' +
              button('learn', a.work[0]?.submitted ? 'See your work' : 'Open lesson →', 'data-id="' + a.id + '"') +
              '<span class="pill">' +
              (a.work[0]?.submitted ? 'Submitted' : a.work.length ? 'In progress' : 'Ready for you') +
              '</span></div>' +
              (a.work[0]?.feedback
                ? '<p class="notice-inline"><b>From your teacher:</b> ' + E(a.work[0].feedback) + '</p>'
                : '') +
              '</section>'
          )
          .join('')
      : '<section class="panel empty">Your teacher hasn’t assigned a lesson yet.<br>Come back when they share your first activity.</section>') +
    button('refresh', 'Check for new lessons', '', 'true')
  )
}
function studentLesson() {
  const a = state.assignments.find(a => a.id === selected)
  if (!a) {
    selected = ''
    return studentHome()
  }
  const w = a.work[0],
    submitted = !!w?.submitted
  return (
    '<div class="actions">' +
    button('student-home', '← My lessons', '', 'true') +
    '<span class="pill">Due ' +
    E(a.due) +
    '</span></div>' +
    head(E(a.lesson.audience), E(a.title), E(a.lesson.objective)) +
    '<div class="grid"><div><section class="panel"><p class="eyebrow">01 · Watch & wonder</p><h2>A new way to see it.</h2>' +
    (a.media ? '<div id="video-host"></div>' : '<p>' + E(a.lesson.introduction) + '</p>') +
    '<details><summary>Read the explanation</summary>' +
    a.lesson.scenes.map(s => '<h3 class="divider">' + E(s.heading) + '</h3><p>' + E(s.narration) + '</p>').join('') +
    '</details></section>' +
    '<section class="panel"><p class="eyebrow">02 · Try it yourself</p><h2>Move the pieces. Notice what changes.</h2><div id="preview-host"></div></section>' +
    '<section class="panel"><p class="eyebrow">03 · Show your thinking</p><h2>' +
    E(a.lesson.question) +
    '</h2><form id="work"><fieldset ' +
    (submitted ? 'disabled' : '') +
    '><legend class="muted">Choose an answer</legend>' +
    a.lesson.options
      .map(
        (o, i) =>
          '<label class="choice"><input type="radio" name="answer" value="' +
          i +
          '" ' +
          (w?.answer === i ? 'checked' : '') +
          '>' +
          E(o) +
          '</label>'
      )
      .join('') +
    '<label>How do you know?<textarea name="reasoning" maxlength="3000" placeholder="I noticed that…">' +
    E(w?.reasoning || '') +
    '</textarea></label></fieldset>' +
    (!submitted
      ? '<div class="actions"><button name="intent" value="save" class="secondary">Save my progress</button><button name="intent" value="submit">Turn in my work</button></div>'
      : '<p class="notice-inline">Your work is turned in. Your teacher can see your explanation.</p>') +
    '<small id="work-status">Your work is saved when you choose Save or Turn in.</small></form>' +
    (w?.feedback ? '<p class="notice-inline"><b>From your teacher:</b> ' + E(w.feedback) + '</p>' : '') +
    '</section></div>' +
    '<aside class="sticky"><section class="panel"><p class="eyebrow">A little help along the way</p><h2>Let’s think it through.</h2><p class="notice-inline">Your teacher can read the questions and replies here. You can ask for help as often as you need.</p><div class="chatlog" id="chatlog">' +
    a.help
      .map(
        h =>
          '<div class="bubble student">' +
          E(h.question) +
          '</div><div class="bubble"><small>' +
          engineLabel(h.engine) +
          '</small><br>' +
          E(h.reply) +
          '</div>'
      )
      .join('') +
    '</div><form id="help"><label>What would you like help with?<textarea name="question" maxlength="1200" required placeholder="Why do more parts make smaller pieces?"></textarea></label><button>' +
    (a.mode === 'teacher' ? 'Ask my teacher' : 'Help me understand') +
    '</button><p><small>Help may take a moment. A saved lesson hint is available if AI cannot connect.</small></p></form></section></aside></div>'
  )
}
async function showPreview(assignment) {
  const host = document.querySelector('#preview-host')
  if (!host) return
  const html = await (
    await api('lesson-html' + (assignment ? '?assignment=' + assignment : ''), undefined, true)
  ).text()
  const frame = document.createElement('iframe')
  frame.className = 'preview'
  frame.title = 'Interactive equal-parts lesson'
  frame.setAttribute('sandbox', 'allow-scripts')
  frame.srcdoc = html
  host.replaceChildren(frame)
}
async function video(asset) {
  const host = document.querySelector('#video-host')
  if (!host) return
  const source = await (await api('media-file?asset=' + asset + '&file=explanation.mp4', undefined, true)).blob()
  const captions = await (await api('media-file?asset=' + asset + '&file=captions.vtt', undefined, true)).blob()
  const src = URL.createObjectURL(source),
    vtt = URL.createObjectURL(captions)
  blobs.push(src, vtt)
  host.innerHTML =
    '<video controls preload="metadata"><source src="' +
    src +
    '" type="video/mp4"><track kind="captions" label="English" srclang="en" src="' +
    vtt +
    '" default></video><div class="actions">' +
    (state.user.role === 'teacher'
      ? button('download-video', 'Download MP4', 'data-asset="' + asset + '"', true) +
        button('download-captions', 'Captions', 'data-asset="' + asset + '"', true)
      : '') +
    '</div>'
}
async function render() {
  clearTimeout(mediaTimer)
  for (const b of blobs) URL.revokeObjectURL(b)
  blobs = []
  shell(
    state.user.role === 'teacher'
      ? ({ overview, studio, assignments, insights }[tab] || overview)()
      : selected
        ? studentLesson()
        : studentHome()
  )
  if (state.user.role === 'student' && selected) {
    await showPreview(selected)
    const a = state.assignments.find(a => a.id === selected)
    if (a?.media) await video(a.media)
  }
  if (state.user.role === 'teacher' && tab === 'studio') {
    const m = state.media.find(m => m.revision === state.draft.revision)
    if (m?.status === 'ready') await video(m.asset)
    if (m?.status === 'rendering') pollMedia()
  }
}
function pollMedia() {
  mediaTimer = setTimeout(async () => {
    if (tab !== 'studio') return
    try {
      const fresh = await api('state')
      state.media = fresh.media
      const m = state.media.find(m => m.revision === state.draft.revision)
      const status = document.querySelector('#media-status')
      if (status) status.textContent = m?.detail || ''
      if (m?.status === 'rendering') pollMedia()
      else {
        document.querySelector('[data-action="render"]')?.removeAttribute('disabled')
        if (m?.status === 'ready') await video(m.asset)
      }
    } catch (e) {
      notice(e.message, true)
    }
  }, 2000)
}
function collectLesson() {
  const f = new FormData(document.querySelector('#lesson-form'))
  return {
    title: f.get('title'),
    objective: f.get('objective'),
    audience: f.get('audience'),
    theme: f.get('theme'),
    introduction: f.get('introduction'),
    scenes: [0, 1, 2].map(i => ({
      heading: f.get('heading' + i),
      narration: f.get('narration' + i),
      denominator: Number(f.get('parts' + i))
    })),
    question: f.get('question'),
    options: [0, 1, 2].map(i => f.get('option' + i)),
    correctIndex: Number(f.get('correctIndex')),
    teacherNotes: f.get('teacherNotes')
  }
}
async function download(path, name) {
  const response = await api(path, undefined, true),
    blob = await response.blob(),
    url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function markDirty() {
  dirty = true
  previewed = 0
  const s = document.querySelector('#save-status')
  if (s) s.textContent = 'Unsaved changes'
  const reviewed = document.querySelector('[name="reviewed"]')
  if (reviewed) reviewed.checked = false
}
root.addEventListener('input', e => {
  if (e.target.closest('#lesson-form')) {
    working = collectLesson()
    markDirty()
  }
})
root.addEventListener('click', async e => {
  const button = e.target.closest('button')
  if (!button) return
  const action = button.dataset.action,
    nav = button.dataset.tab
  if (!action && !nav) return
  try {
    if (nav) {
      tab = nav
      await render()
      return
    }
    button.disabled = true
    const actions = {
      'desktop-link': async () => {
        const link = location.origin + '/#access=' + token
        try {
          await navigator.clipboard.writeText(link)
          notice('Private teacher link copied. Paste it into the native Classroom tab.')
        } catch {
          document.querySelector('#desktop-link-result').innerHTML =
            '<label>Private teacher link<input readonly value="' + E(link) + '"></label>'
        }
      },
      logout: () => {
        token = ''
        sessionStorage.removeItem('chalkline-access')
        clearTimeout(mediaTimer)
        login()
      },
      refresh: async () => {
        await load()
        await render()
        notice('Classroom updated.')
      },
      studio: async () => {
        tab = 'studio'
        await render()
      },
      inspect: async () => {
        selected = button.dataset.id
        tab = 'assignments'
        await render()
      },
      learn: async () => {
        selected = button.dataset.id
        await render()
      },
      'student-home': async () => {
        selected = ''
        await load()
        await render()
      },
      preview: async () => {
        if (dirty) throw new Error('Save your edits before previewing this version.')
        await showPreview()
        previewed = state.draft.revision
        notice('Preview ready. Review the activity and script before assigning.')
      },
      'export-html': () => {
        if (dirty) throw new Error('Save your changes before exporting.')
        return download('lesson-html', 'chalkline-lesson.html')
      },
      render: async () => {
        if (dirty) throw new Error('Save your changes before making the video.')
        await api('media', { revision: state.draft.revision })
        await load()
        await render()
      },
      'download-video': () =>
        download('media-file?asset=' + button.dataset.asset + '&file=explanation.mp4', 'chalkline-explanation.mp4'),
      'download-captions': () =>
        download('media-file?asset=' + button.dataset.asset + '&file=captions.vtt', 'chalkline-captions.vtt'),
      'student-link': async () => {
        const links = await api('links'),
          s = links.students.find(s => s.id === button.dataset.id)
        const host = document.querySelector('#student-link-result')
        host.innerHTML =
          '<p class="notice-inline">This link opens only ' +
          E(s.name) +
          '’s demo workspace on this computer.</p><p><a href="' +
          E(s.url) +
          '" target="_blank" rel="noopener noreferrer">Open ' +
          E(s.name) +
          '’s student workspace ↗</a></p><div class="linkbox">' +
          E(s.url) +
          '</div>'
      },
      followup: async () => {
        const result = await api('followup', { assignmentId: button.dataset.id })
        working = result.lesson
        dirty = true
        previewed = 0
        tab = 'studio'
        await render()
        notice('Follow-up draft created. Review and save before assigning.')
      }
    }
    if (actions[action]) await actions[action]()
  } catch (error) {
    notice(error.message, true)
  } finally {
    button.disabled = false
  }
})
root.addEventListener('submit', async e => {
  e.preventDefault()
  const form = e.target,
    submitter = e.submitter
  const data = new FormData(form)
  if (submitter) submitter.disabled = true
  try {
    if (form.id === 'login') {
      token = String(data.get('code'))
        .trim()
        .replace(/^.*#access=/, '')
      await load()
      sessionStorage.setItem('chalkline-access', token)
      await render()
      return
    }
    if (form.id === 'lesson-form') {
      const result = await api('lesson', { lesson: collectLesson(), revision: state.draft.revision })
      state.draft = result
      working = null
      dirty = false
      previewed = 0
      await render()
      notice('Lesson saved. Preview the new version before assigning.')
    }
    if (form.id === 'generate') {
      const result = await api('generate', { brief: data.get('brief') })
      working = result.lesson
      dirty = true
      previewed = 0
      await render()
      notice('AI draft ready. Check the explanation and answer key, then save.')
    }
    if (form.id === 'publish') {
      if (dirty || previewed !== state.draft.revision)
        throw new Error('Preview the current saved lesson before assigning it.')
      const media = state.media.find(m => m.revision === state.draft.revision)
      if (media?.status === 'rendering') throw new Error('Wait for the video to finish so it can be included.')
      await api('publish', {
        revision: state.draft.revision,
        students: data.getAll('students'),
        due: data.get('due'),
        mode: data.get('mode'),
        reviewed: data.get('reviewed') === 'on'
      })
      await load()
      tab = 'assignments'
      await render()
      notice('Assigned. Students can open this reviewed version now.')
    }
    if (form.id === 'work') {
      const answer = data.get('answer')
      await api('progress', {
        assignmentId: selected,
        answer: answer === null ? null : Number(answer),
        reasoning: data.get('reasoning'),
        submit: submitter?.value === 'submit'
      })
      await load()
      await render()
      notice(submitter?.value === 'submit' ? 'Your work is turned in.' : 'Your progress is saved.')
    }
    if (form.id === 'help') {
      const question = data.get('question'),
        assignmentId = selected,
        requestToken = token
      const result = await api('help', { assignmentId, question })
      if (token !== requestToken) return
      const a = state.assignments.find(a => a.id === assignmentId)
      if (a && !a.help.some(h => h.id === result.id)) a.help.push(result)
      const log = document.querySelector('#chatlog')
      if (selected !== assignmentId || !log) {
        notice('Your help reply is saved with the lesson.')
        return
      }
      log.insertAdjacentHTML(
        'beforeend',
        '<div class="bubble student">' +
          E(question) +
          '</div><div class="bubble"><small>' +
          engineLabel(result.engine) +
          '</small><br>' +
          E(result.reply) +
          '</div>'
      )
      form.reset()
      log.scrollTop = log.scrollHeight
    }
    if (form.dataset.feedback) {
      await api('feedback', {
        assignmentId: form.dataset.assignment,
        studentId: form.dataset.feedback,
        feedback: data.get('feedback')
      })
      await load()
      notice('Feedback shared with the student.')
    }
  } catch (error) {
    notice(error.message, true)
  } finally {
    if (submitter) submitter.disabled = false
  }
})
if (token) {
  load()
    .then(render)
    .catch(error => {
      login()
      notice(error.message, true)
    })
} else login()
