# Chalkline connected classroom prototype

A local teacher/student companion for the Chalkline Hermes desktop fork. Uses Node's built-in HTTP server and SQLite; no new npm dependencies.

## Run

From this directory on Windows, run `./Start-Classroom.ps1`. Node.js 22.16 or newer must be on PATH. It starts the service on http://127.0.0.1:5195 and opens the private teacher link. Use **Classroom → Get student link** to open a demo student in another browser tab. The native app's **Connected classroom** view embeds the same service; sign in there with the teacher access code from the local private access file if needed.

Service command: `node server.mjs --data <private directory> --config <private config.json> --port 5195`.

## Portable setup

The core service has **no third-party runtime dependencies** and runs on Windows, Linux and macOS with Node.js 22.16+ (Node 24 recommended):

```sh
node server.mjs
```

Read `data/launch.json` locally and open its `teacherUrl` in your browser. Treat that file, `data/access.json`, the SQLite database and all local configuration as private. The URL contains a reusable demo credential. Keep one browser tab per role. The service binds only to `127.0.0.1`; student links work on this computer only.

On Windows, `./Start-Classroom.ps1` starts the same service hidden and opens the teacher view. It accepts `-DataDirectory`, `-ConfigPath`, `-Port` and `-NoBrowser`. It does not install Node or configure any model provider. To stop a launcher-started service, verify the process identified by your local `data/launch.json` and stop that Node process. A foreground service stops with Ctrl+C.

Optional AI: copy `config.example.json` to `data/config.json`, set your approved provider and model, and restart. Set `CHALKLINE_AI_KEY` in the service environment only if the provider requires a secret. Without a provider, the lesson editor, assignments and saved hints work; AI drafting reports that it is unavailable. No endpoint is enabled by default.

Optional narrated video: Windows with System.Speech and FFmpeg (including libx264, AAC, drawtext and drawbox support) on PATH. Override executable paths in the private config if needed. Linux/macOS support lesson, assignment and help workflows; this narration implementation is Windows-only.

Development checks, from this directory (`--workspaces=false` also supports use inside the Hermes monorepo):

```sh
npm ci --workspaces=false
npm test --workspaces=false
npx --workspaces=false playwright install chromium
npm run test:browser --workspaces=false
# Windows only, with FFmpeg available:
npm run test:media --workspaces=false
```

Browser checks use temporary synthetic state and save screenshots to ignored `artifacts/`. Media checks generate a real MP4, captions and transcript there. They do not call a paid model. Live AI quality and school deployment are outside CI.

## First classroom cycle

1. Lesson Studio: edit the fraction explanation, three narration scenes, quiz and private notes. Save.
2. Make video. This uses Windows System.Speech narration plus FFmpeg to create a 720p MP4, WebVTT captions and transcript.
3. Preview the saved HTML exploration and review the video/answer key. Select demo students, due date and help level, check review and assign.
4. Open a student's private link. Explore the fraction bars, watch the video, ask for help, save or submit work.
5. Return to Assignments and Questions & support. Refresh to see exact questions/replies, reasoning, submission state and feedback. Draft a follow-up from an actual exchange.

Published assignment content is a snapshot; future edits cannot change it. Video is included only if ready at publication. Regenerated content requires a new reviewed assignment.

## Scope and boundaries

This is a **single-teacher, synthetic, loopback-only prototype**, not a school deployment. Four named demo learners, no real roster import. HTML visuals currently support unit fractions with equal-sized wholes; AI can adapt the theme/script within that format, not generate arbitrary subject simulations.

Student capability links are reusable demo credentials. Tokens live in a private local access.json and in the signed-in tab's sessionStorage; URLs place them in the fragment, which is cleared after sign-in. Student tokens cannot read teacher notes, answer keys, other students' work, or teacher APIs. Use one tab per role. Authentication is enforced by the server. No student path reaches Hermes shell, filesystem, tool or agent execution.

Generated lesson content is escaped inside a controlled template and runs in a sandboxed iframe without same-origin authority or network access. The app does not accept arbitrary executable HTML from a model. Teacher-approved text and source context remain important: tutoring instructions cannot guarantee that a model never reveals an answer.

Optional AI configuration is server-only:
```json
{"ai":{"baseUrl":"https://model.example.com/v1","model":"approved-model"},"media":{"ffmpeg":"C:/path/ffmpeg.exe","powershell":"C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"}}
```
An optional secret is read from `CHALKLINE_AI_KEY`. Model requests are serialized in this service, contain only the assigned lesson and this student's last three exchanges, and have no tools. AI failure yields a clearly labeled saved lesson hint; teacher-only help never invokes the model. Draft generation fails visibly and preserves the editable lesson.

Question grouping uses keyword rules and unique-student counts, not inferred diagnoses or automatic grades. Work only saves when the student selects Save or Turn in. Submitted work is locked in this prototype; teachers can send feedback.

Before real pupils or access from another device: district-approved identity/consent and retention design, HTTPS, per-school/class authorization, backups/encryption, deployment operations, model/pedagogical evaluation and accessibility review. No production rollout is implied by this local prototype.

## Verification

`node --test test/*.test.mjs` exercises actual HTTP authorization, assignment immutability, draft conflict handling, durable work/help/feedback, content escaping, and restricted tutor context. `node test/browser-check.mjs` exercises real browser teacher/student flows after installing this package's development dependencies. Browser artifacts go under ignored artifacts/.

## Verified on 2026-10-03

- Three actual-HTTP/backend tests passed: role and assignment isolation, immutable published versions, optimistic draft conflict detection, durable work/help/feedback, private-data exclusion, origin/content checks, and restricted tutor context.
- Real browser flow passed: teacher edit/preview/publish, live sandboxed fraction slider, student help preserving unfinished work, save/reload/submit, teacher feedback, source question review, follow-up draft and 390px mobile layout. Screenshots are in ignored artifacts/.
- Live local service rendered and delivered a 1280x720 H.264/AAC narrated MP4 with an English caption track (about 37 seconds). Playback succeeded in separate teacher and student browser sessions. Rendering uses direct -vf arguments, compatible with the bundled FFmpeg 9; it does not use the removed filter_script option.
- A real configured model returned a student explanation. AI authoring also returned a valid soccer-field lesson draft. Early connection timeout exercised the explicitly labeled saved-hint behavior; no silent simulated AI response is used.
- The native access component test, renderer TypeScript check and scoped Chalkline lint passed. Native visual inspection is separate from these browser checks.

The default runtime state is the ignored `data/` directory. No Windows startup task, fleet route or public deployment is created.
