#!/bin/sh
# Updates FamilyLog in its container: pull, build next to the running image,
# back up /data, restart, check - and put everything back if the new version
# does not start. The work is in tools/container.py (tested Python, ported
# from SLQ Companion).
#   bash update.sh            update (asks first)
#   bash update.sh --yes      update without asking
#   bash update.sh status | backups | rollback | compose <args>
exec python3 "$(dirname "$0")/tools/container.py" "$@"
