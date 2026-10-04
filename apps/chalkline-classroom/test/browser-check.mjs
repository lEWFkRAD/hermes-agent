import { chromium, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { mkdtemp, rm, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createClassroom } from '../server.mjs'
import { Tutor } from '../tutor.mjs'
const dir = await mkdtemp(join(tmpdir(), 'chalkline-browser-')),
  app = createClassroom({ dataDir: dir, tutor: new Tutor() })
const origin = await app.listen(0)
await mkdir(new URL('../artifacts/', import.meta.url), { recursive: true })
const browser = await chromium.launch({ headless: true })
const errors = []
try {
  const teacher = await browser.newPage({ viewport: { width: 1440, height: 1050 } })
  teacher.on('pageerror', e => errors.push(e.message))
  await teacher.goto(origin + '/#access=' + app.store.access.teacher)
  await teacher.getByRole('heading', { name: 'Every question opens a door.' }).waitFor()
  await teacher.screenshot({
    path: fileURLToPath(new URL('../artifacts/teacher-classroom.png', import.meta.url))
  })
  await teacher.getByRole('button', { name: 'Lesson Studio', exact: true }).click()
  await teacher.getByLabel('Title', { exact: true }).fill('A garden shared fairly')
  await teacher.getByRole('button', { name: 'Save lesson', exact: true }).click()
  await expect(teacher.locator('#save-status')).toContainText('Saved version 2')
  await teacher.getByRole('button', { name: 'Preview saved lesson', exact: true }).click()
  const frame = teacher.frameLocator('iframe.preview')
  await frame.getByRole('slider').fill('8')
  await frame.getByRole('button', { name: 'Compare the pieces' }).click()
  await expect(frame.locator('#result')).toContainText('smaller than')
  await teacher.screenshot({
    path: fileURLToPath(new URL('../artifacts/teacher-studio.png', import.meta.url))
  })
  await teacher.getByLabel('I reviewed this saved lesson', { exact: false }).check()
  await teacher.getByRole('button', { name: 'Assign lesson', exact: true }).click()
  await teacher.getByRole('heading', { name: 'From lesson to learning.' }).waitFor()
  const maya = app.store.access.students[0]
  const student = await browser.newPage({ viewport: { width: 1366, height: 1000 } })
  student.on('pageerror', e => errors.push(e.message))
  await student.goto(origin + '/#access=' + maya.token)
  await student.getByRole('button', { name: 'Open lesson →', exact: true }).click()
  await student
    .getByLabel('How do you know?')
    .fill('Both wholes are the same size. Four equal parts are bigger than six.')
  await student.getByLabel('What would you like help with?').fill('Why is one sixth smaller?')
  await student.getByRole('button', { name: 'Help me understand', exact: true }).click()
  await expect(student.locator('#chatlog')).toContainText('Saved lesson hint')
  // Asking for help must not wipe the unsaved answer.
  await expect(student.getByLabel('How do you know?')).toHaveValue(
    'Both wholes are the same size. Four equal parts are bigger than six.'
  )
  await student.getByLabel('One fourth', { exact: true }).check()
  await student.getByRole('button', { name: 'Save my progress', exact: true }).click()
  await student.reload()
  await student.getByRole('button', { name: 'Open lesson →', exact: true }).click()
  await expect(student.getByLabel('How do you know?')).toHaveValue(
    'Both wholes are the same size. Four equal parts are bigger than six.'
  )
  await student.getByRole('button', { name: 'Turn in my work', exact: true }).click()
  await expect(student.getByText('Your work is turned in.', { exact: false }).first()).toBeVisible()
  await student.screenshot({
    path: fileURLToPath(new URL('../artifacts/student-lesson.png', import.meta.url))
  })
  await teacher.getByRole('button', { name: 'Refresh', exact: true }).click()
  await teacher.getByRole('button', { name: 'Review', exact: true }).click()
  await expect(
    teacher.getByText('Both wholes are the same size. Four equal parts are bigger than six.', { exact: false })
  ).toBeVisible()
  const feedback = teacher.locator('form[data-feedback="maya"]')
  await feedback.getByLabel('Your feedback').fill('Good comparison. Draw both wholes to show your reasoning.')
  await feedback.getByRole('button', { name: 'Share feedback', exact: true }).click()
  await teacher.getByRole('button', { name: 'Questions & support', exact: true }).click()
  await teacher.getByText('Maya B. — Why is one sixth smaller?', { exact: true }).click()
  await expect(teacher.getByText('AI help is unavailable right now.', { exact: false })).toBeVisible()
  await teacher.screenshot({
    path: fileURLToPath(new URL('../artifacts/teacher-insights.png', import.meta.url))
  })
  await teacher.getByRole('button', { name: 'Draft a follow-up lesson', exact: true }).click()
  await expect(teacher.getByLabel('Title', { exact: true })).toHaveValue(/Another look/)
  await student.setViewportSize({ width: 390, height: 844 })
  await student.getByRole('button', { name: '← My lessons', exact: true }).click()
  await expect(
    student.getByText('Good comparison. Draw both wholes to show your reasoning.', { exact: false })
  ).toBeVisible()
  await student.screenshot({
    path: fileURLToPath(new URL('../artifacts/student-mobile.png', import.meta.url))
  })
  if (await student.evaluate(() => document.documentElement.scrollWidth > innerWidth))
    throw new Error('Mobile layout overflows.')
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(
    'Browser checks passed: teacher authoring, sandbox interaction, publishing, separate student session, preserved input, saved/reloaded work, submission, teacher feedback, help insight, follow-up, mobile layout.'
  )
} finally {
  await browser.close()
  await app.close()
  await rm(dir, { recursive: true, force: true })
}
