export const seedLesson = {
  title: 'One whole. Many ways to share.',
  objective: 'Compare unit fractions using equal-sized wholes and explain why the size of each part changes.',
  audience: 'Grade 3 · Fractions',
  theme: 'Sharing a garden',
  introduction:
    'Two friends have garden beds of the same size. One bed is split into four equal parts and the other into six. Which friend has the larger piece?',
  scenes: [
    {
      heading: 'Start with the same whole',
      narration:
        'Imagine two garden beds of exactly the same size. To compare fractions fairly, we start with the same whole.',
      denominator: 1
    },
    {
      heading: 'Share into equal parts',
      narration:
        'Split one bed into four equal parts. Each part is one fourth. Split the other into six equal parts. Each part is one sixth.',
      denominator: 4
    },
    {
      heading: 'More parts, smaller pieces',
      narration:
        'The whole stayed the same size. Sharing it into more equal parts made each part smaller. One fourth is larger than one sixth. Try changing the number of parts yourself.',
      denominator: 6
    }
  ],
  question: 'For two wholes of the same size, which is larger?',
  options: ['One fourth', 'One sixth', 'They are equal'],
  correctIndex: 0,
  teacherNotes:
    'Ask students to explain what stayed the same. Look for reasoning about piece size rather than the larger numeral.'
}
export function validateLesson(value) {
  const string = (v, max, name) => {
    if (typeof v !== 'string' || !v.trim() || v.length > max) throw new Error('Check ' + name + '.')
    return v.trim()
  }
  if (
    !value ||
    !Array.isArray(value.scenes) ||
    value.scenes.length !== 3 ||
    !Array.isArray(value.options) ||
    value.options.length !== 3 ||
    !Number.isInteger(value.correctIndex) ||
    value.correctIndex < 0 ||
    value.correctIndex > 2
  )
    throw new Error('A lesson needs three scenes, three choices and an answer key.')
  return {
    title: string(value.title, 120, 'title'),
    objective: string(value.objective, 700, 'objective'),
    audience: string(value.audience, 100, 'audience'),
    theme: string(value.theme, 100, 'theme'),
    introduction: string(value.introduction, 1400, 'introduction'),
    scenes: value.scenes.map(s => {
      if (!Number.isInteger(s.denominator) || s.denominator < 1 || s.denominator > 12)
        throw new Error('Parts must be between 1 and 12.')
      return {
        heading: string(s.heading, 100, 'scene heading'),
        narration: string(s.narration, 1400, 'narration'),
        denominator: s.denominator
      }
    }),
    question: string(value.question, 600, 'question'),
    options: value.options.map(s => string(s, 200, 'answer choice')),
    correctIndex: value.correctIndex,
    teacherNotes: string(value.teacherNotes, 1800, 'teacher notes')
  }
}
export function publicLesson(lesson) {
  const student = { ...lesson }
  delete student.correctIndex
  delete student.teacherNotes
  return student
}
export function escapeHtml(text) {
  return String(text).replace(
    /[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  )
}
export function lessonHtml(lesson) {
  const safe = publicLesson(lesson)
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src data:; form-action 'none'; base-uri 'none'">
<title>${escapeHtml(safe.title)}</title><style>
*{box-sizing:border-box}body{margin:0;padding:28px;background:#f5f2e9;color:#173f38;font:17px/1.6 system-ui}h1{font:36px Georgia,serif;line-height:1.15;margin:8px 0 18px}
small{letter-spacing:.1em;text-transform:uppercase}p{max-width:60ch}label{display:block;margin:20px 0}input{width:min(100%,400px);display:block;margin:15px 0;accent-color:#215e4a}
.bar{display:flex;width:100%;height:80px;background:#fff;border:2px solid #215e4a;margin:12px 0}.part{flex:1;border-right:2px solid #215e4a}.part:last-child{border:0}.part:first-child{background:#edbd5d}.fixed .part:first-child{background:#9ccab6}
button{font:inherit;background:#215e4a;color:white;border:0;padding:10px 18px;border-radius:8px;cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid #ca6642;outline-offset:4px}
#result{min-height:3em} @media(max-width:500px){body{padding:18px}h1{font-size:28px}}
</style></head><body><small>${escapeHtml(safe.audience)} · Explore</small><h1>${escapeHtml(safe.title)}</h1><p>${escapeHtml(safe.introduction)}</p>
<label for="parts">How many equal parts? <strong id="count">6</strong><input id="parts" type="range" min="2" max="12" value="6"></label>
<p id="fraction">One sixth</p><div id="bar" class="bar" aria-label="One of six equal parts shaded"></div><p>Compare with one fourth of the same whole:</p><div class="bar fixed" aria-label="One of four equal parts shaded"><span class="part"></span><span class="part"></span><span class="part"></span><span class="part"></span></div>
<button id="compare">Compare the pieces</button><p id="result" role="status">Move the slider. What changes? What stays the same?</p>
<script>
const input=document.getElementById('parts'),bar=document.getElementById('bar');
function draw(){const n=Number(input.value);document.getElementById('count').textContent=n;document.getElementById('fraction').textContent='1 / '+n;bar.replaceChildren(...Array.from({length:n},()=>{const p=document.createElement('span');p.className='part';return p}));bar.setAttribute('aria-label','One of '+n+' equal parts shaded');document.getElementById('result').textContent='Predict: is your shaded piece larger, smaller or the same size?'}
input.addEventListener('input',draw);document.getElementById('compare').addEventListener('click',()=>{const n=Number(input.value);document.getElementById('result').textContent='1 / '+n+' is '+(n>4?'smaller than':n<4?'larger than':'the same size as')+' 1 / 4. Both wholes stayed the same size.'});draw();
</script></body></html>`
}
