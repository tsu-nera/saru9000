#!/bin/bash
# UserPromptSubmit hook: hand the prompt to core, show its reply, and stop Claude Code from answering.
# continue:false (not exit 2) so Claude Code takes the prompt and clears the input box.
client="$(dirname "$(realpath "$0")")/../console/client.py"
text=$(jq -r '.prompt')
reply=$(printf '%s\n' "$text" | "$client" 2>/dev/null | sed -e 's/^\(you> \)*//' -e '/^\[mode/d' -e '/^$/d')
jq -n --arg r "$reply" '{continue: false, stopReason: $r, suppressOutput: true}'
