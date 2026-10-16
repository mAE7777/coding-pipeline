# Hearth DB 4.2 release notes

Saved copy of the project's release page. Published 14 May 2026.

## Highlights
- Hearth DB 4.2 raises the maximum database size to 64 TiB.
- Online index rebuilds no longer block writes.
- The `hearth backup` command can now stream to standard output.

## Upgrading
4.2 reads every 4.x file format. Downgrading to 4.1 after a 4.2 write is not supported.
