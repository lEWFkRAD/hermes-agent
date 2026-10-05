# Chalkline teacher desktop and connected classroom

This branch contains the Chalkline adaptation of Hermes at upstream snapshot `16bc0b6b94be7435cb63ed30923fbc7edd53f4c5` (2026-10-03). It preserves upstream history and licenses. Chalkline uses its own app identity, profile and `chalkline://` links.

## One maintained classroom service

The service lives in [onyx-chalkline/classroom](https://github.com/lEWFkRAD/onyx-chalkline/tree/main/classroom). This native branch consumes that service instead of maintaining a second database, tutor or browser app. The compatible source revision is recorded in [source.lock.json](apps/chalkline-classroom/source.lock.json).

Clone both repositories and run the companion with Node.js 24.11+:

```sh
node apps/chalkline-classroom/launcher.mjs --source /path/to/onyx-chalkline/classroom --data /path/to/private-classroom-data
```

On Windows, the bridge `Start-Classroom.ps1` accepts `-ClassroomRoot` and `-DataDirectory`. Sign in using the initial credentials in the private data directory's `bootstrap.json`; do not publish that file. Full account, private HTTPS, AI, video and recovery instructions are in the [classroom guide](https://github.com/lEWFkRAD/onyx-chalkline/blob/main/classroom/README.md).

The classroom supports teacher-owned classes, individual student sign-ins, reviewed lesson snapshots, HTML activities, Windows narrated videos, assignments, AI questions, saved work, submissions and teacher feedback. Sessions expire and can be revoked. Students' unfinished answers survive an interrupted connection, and retries do not duplicate committed work. The current teaching format remains a synthetic Grade 3 unit-fractions demonstration.

## Build the native teacher app

Follow the upstream [desktop build requirements](apps/desktop/BUILDING.md) for the Python backend, root workspace dependencies, Electron and platform tooling. Install Node dependencies from the repository root. This branch selects the Chalkline product profile and desktop development port 5194; the companion uses 5195.

Start the companion separately, then run:

```sh
npm run dev --workspace apps/desktop
# Or build renderer and Electron assets:
npm run build --workspace apps/desktop
```

The Classroom tab opens the shared sign-in page at `http://127.0.0.1:5195`. Teachers can sign in there directly or paste an expiring teacher session link copied from their browser classroom. The native connector deliberately pins this loopback address. Learners on other devices open the configured private HTTPS browser address instead.

Keep a separate Hermes home/profile and desktop data directory when running alongside another Hermes installation. The classroom launcher does not start Hermes, install its dependencies or configure providers. Native identity is `com.onyxintelligence.chalkline`; the fork does not inherit the standard Hermes release feed. No prebuilt installer is published here.

## Verification and scope

The companion's deterministic HTTP, database migration, recovery and browser checks live with its source. This branch's classroom workflow checks the pinned source revision. Native component checks cover the restricted connection URL and product identity; build/type checks cover the renderer and Electron integration.

Use fictional learners for this private demonstration. District identity, broader lesson formats, retention/deletion, accessibility evaluation, operational monitoring and real-school approval remain later stages. Private device access is supported; it does not make this a production student-record system.
