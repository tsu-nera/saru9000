// Row buffer behind the stage's log screen. Pure: no Babylon, no DOM.
// A logical line is one log entry; lines() wraps them to display rows.

// Full-width characters (CJK etc.) take two monospace columns.
function width(char) {
  return char.codePointAt(0) > 0xff ? 2 : 1;
}

function wrap(text, columns) {
  const rows = [];
  let row = "";
  let used = 0;
  for (const char of text) {
    const w = width(char);
    if (used + w > columns && row !== "") {
      rows.push(row);
      row = "";
      used = 0;
    }
    row += char;
    used += w;
  }
  rows.push(row);
  return rows;
}

export function createLogLines({ maxLines = 40, columns = 80 } = {}) {
  let logical = []; // [{ kind, text }]

  function add({ kind, text, append = false }) {
    const parts = String(text).split("\n");
    const last = logical.at(-1);
    if (append && last?.kind === kind) {
      last.text += parts.shift();
    }
    for (const part of parts) logical.push({ kind, text: part });
    // Every logical line takes at least one row, so older ones can never show.
    if (logical.length > maxLines) logical = logical.slice(-maxLines);
  }

  function lines() {
    const rows = logical.flatMap(({ kind, text }) => wrap(text, columns).map((row) => ({ kind, text: row })));
    return rows.slice(-maxLines);
  }

  return { add, lines };
}
