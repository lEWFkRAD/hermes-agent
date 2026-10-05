# Shared classroom service

The maintained classroom implementation lives in [onyx-chalkline/classroom](https://github.com/lEWFkRAD/onyx-chalkline/tree/main/classroom). This directory is a launcher bridge, not a second copy of its authentication, database or tutoring code.

Clone that repository next to your Hermes checkout and select the source revision recorded in `source.lock.json`. Run the service on the teacher computer or your approved shared host, using its own private data directory. Follow its README and OPERATIONS guide for initial credentials, migration, private HTTPS and backups.

```sh
node launcher.mjs --source /path/to/onyx-chalkline/classroom --data /private/chalkline-data
```

On Windows:

```powershell
./Start-Classroom.ps1 -ClassroomRoot C:\path\onyx-chalkline\classroom -DataDirectory C:\private\chalkline-data -TeacherSession
```

The native Classroom page connects to `http://127.0.0.1:5195` and shows the same class, lesson, assignment and question records as the browser. Sign in inside the page or copy a current teacher session link from the browser. Session links expire; old v1 permanent access links do not authenticate to v2. Student browsers use the configured private HTTPS address.

If the shared service is on another teacher host, use its browser URL. The desktop's embedded address remains pinned to loopback in this release. Native integration never gives student clients access to Hermes tools.
