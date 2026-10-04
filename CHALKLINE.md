# Chalkline teacher desktop and connected classroom

This branch contains the Chalkline adaptation of Hermes at upstream snapshot `16bc0b6b94be7435cb63ed30923fbc7edd53f4c5` (2026-10-03). It preserves upstream history and licenses. It is a product branch, not a request to replace the general-purpose Hermes application.

## Run the classroom independently

```sh
cd apps/chalkline-classroom
node server.mjs
```

Node.js 22.16+ is required; Node 24 is recommended. Open the private teacher URL in the generated `data/launch.json`, or use `./Start-Classroom.ps1` on Windows. No model is configured by default. Full instructions and tests: [classroom guide](apps/chalkline-classroom/README.md).

Teacher authoring, reviewed assignment snapshots, student lessons and help, saved work, submissions, feedback and question review persist in local SQLite. Narrated MP4 generation currently needs Windows System.Speech and FFmpeg. This is a single-computer synthetic prototype, with four demo learners and Grade 3 unit-fraction visuals.

## Build the native teacher app

Follow the upstream [desktop build requirements](apps/desktop/BUILDING.md) for the Python backend, root workspace dependencies, Electron and platform tooling. Install Node dependencies from the repository root as described there. This branch's desktop scripts select the Chalkline product profile and port 5194; the classroom service uses 5195.

Start the classroom separately, then run the desktop development command from the root:

```sh
npm run dev --workspace apps/desktop
```

For a renderer/Electron production build:

```sh
npm run build --workspace apps/desktop
```

The Classroom tab accepts the private desktop access link copied from the teacher browser view. It connects only to `http://127.0.0.1:5195`. The classroom launcher does not start Hermes, install its dependencies or configure providers. Keep a separate Hermes profile/home and desktop data directory when running alongside an existing Hermes installation; use the documented upstream environment configuration for your platform.

Native identity is `com.onyxintelligence.chalkline`, product name Chalkline and protocol `chalkline://`. The fork does not inherit the standard Hermes release feed. No installer binary or machine-specific launcher is published here.

## Verification and limits

Before publication, the source product passed 52 focused desktop startup/identity tests, renderer/Electron type checks, lint, production build and Windows unpacked packaging. The connected access component test and the full teacher/student browser cycle also passed. Real model drafting/tutoring and Windows video playback/captions were tested locally with synthetic data. See the classroom guide for scope and reproducible checks; CI covers deterministic HTTP and browser behavior without a live model.

Desktop screenshots were not verified in that local run; browser screenshots were. There is no school deployment, real roster integration or cross-device login in this version.

[Standalone public Chalkline repository](https://github.com/lEWFkRAD/onyx-chalkline) includes the same classroom companion and the earlier evidence workspace.
