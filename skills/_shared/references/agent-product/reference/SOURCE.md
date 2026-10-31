# Source of these files

`coordination.py` and `test_coordination.py` are copied unchanged from the `agent-handbook/reference/`
folder of the AI Engineering Handbook 1.0 kit (version 1.0, evidence baseline 2026-10-10), which the owner
supplied for this repository. Only this file was added. The kit states no license of its own.

| File | Bytes | sha256 |
|---|---|---|
| `coordination.py` | 16016 | `166520dbca8692b085bba6662e5b74789d7706e65dbd76e8716da8b7cc4e6016` |
| `test_coordination.py` | 11153 | `477b74289140e5b850929d73108266a0df8fa1d9c8ebbe59298a2d27ad8dc157` |

Each value equals the kit's own `SHA256SUMS.txt` entry for `agent-handbook/reference/<file>`. The kit's `reference/README.md` is not copied: it is bilingual, and publishable files here carry no Chinese
text; its limits are quoted below. To check a copy: `sha256sum coordination.py test_coordination.py`.

## What the handbook says these files are

- A teaching implementation: "`reference/coordination.py` is a SQLite teaching implementation using only the
  Python standard library" (chapter 29). "The reference program is not a production runtime"
  (`AGENT_START.en.md`).
- Single host: "This is a single-host demonstration of short local SQLite transactions, leases, resource
  generations, revisions, intent ledgers, inbox/outbox, and budget reservation" (the kit's `reference/README.md`). "Do not share the
  WAL file over a network filesystem."
- Trusted inputs: "Caller identity, approval records, the current plan, and external receipts are trusted
  application inputs here. A production service must authenticate, authorize, read authoritative state, and
  verify receipts itself" (the kit's `reference/README.md`).
- Not agent tools: "`inspect` is a privileged test/debug SQL interface, never an agent-facing business tool";
  "`complete` assumes an independent verifier already approved acceptance and must not be exposed directly to
  arbitrary agents" (chapter 29).
- Omitted: "network authentication, resource ACLs, reliable credential revocation, a real approval service,
  provider idempotency, cross-database transactions, multi-host coordination, a complete/fair scheduler, an
  outbox dispatcher, production billing reconciliation, distributed-clock handling, or disaster recovery"
  (chapter 29).
- Test scope: "Passing thread-contention tests is not passing distributed network-failure tests" (the kit's `reference/README.md`).
  "Tests shipped with this handbook do not replace project tests" (`AGENT_START.en.md`).

## Run the tests

Copy `coordination.py` and `test_coordination.py` to a temporary folder and run `python3 -I -m unittest -v`
there, so no cache folder is left beside the installed files. Only the standard library is needed; the kit
recommends Python 3.10 or later.

Recorded run, 2026-10-16, Python 3.13.16 on Linux, from a temporary copy: `Ran 36 tests`, `OK`.
