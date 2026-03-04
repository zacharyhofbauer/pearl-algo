#!/usr/bin/awk -f
# Colorize PearlAlgo/journalctl log stream. Reads stdin, prints with ANSI colors.
# Usage: journalctl -f -o cat -q -n 200 | awk -f colorize-logs.awk

BEGIN {
  R="\033[1;31m"   # bold red   - ERROR
  G="\033[1;32m"   # bold green - INFO
  Y="\033[1;33m"   # bold yellow - WARNING
  M="\033[1;35m"   # bold magenta - Exception/failed
  C="\033[0;36m"   # cyan - timestamp
  D="\033[0;2m"    # dim - DEBUG
  X="\033[0m"
}

{
  line = $0
  if (line ~ /\| *ERROR *\|/)   { print R line X; next }
  if (line ~ /\| *WARNING *\|/) { print Y line X; next }
  if (line ~ /\| *INFO *\|/)    { print G line X; next }
  if (line ~ /\| *DEBUG *\|/)   { print D line X; next }
  if (line ~ /Exception|Traceback|Error:|failed|Failure|CRITICAL/) { print M line X; next }
  if (line ~ /success|Success|OK\b|placed|filled/) { print G line X; next }
  if (match(line, /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}/)) {
    print C substr(line, 1, RLENGTH) X substr(line, RLENGTH+1)
    next
  }
  print line
}
