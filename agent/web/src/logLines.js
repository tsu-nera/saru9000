// Line buffer of the log screen: pure text handling, no Babylon, so it is testable.

const FULL_WIDTH_FROM = 0x100;

// Columns a character takes on the screen: ASCII and Latin-1 one, the rest two.
function width(char) {
  return char.codePointAt(0) < FULL_WIDTH_FROM ? 1 : 2;
}

export function createLogLines({ maxLines = 200 } = {}) {
  const lines = [];

  // A "\n" in text ends the line; only the first part may continue the last line.
  function add({ kind, text, append = false }) {
    const [first, ...rest] = String(text).split("\n");
    const last = lines.at(-1);
    if (append && last && last.kind === kind) last.text += first;
    else lines.push({ kind, text: first });
    for (const part of rest) lines.push({ kind, text: part });
    if (lines.length > maxLines) lines.splice(0, lines.length - maxLines);
  }

  return { add, lines: () => lines.map((line) => ({ ...line })) };
}

// Cuts text into rows of at most `columns` columns (an empty text is one empty row).
export function wrap(text, columns) {
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

// The last `rows` wrapped rows, oldest first.
export function tail(lines, columns, rows) {
  const wrapped = lines.flatMap(({ kind, text }) => wrap(text, columns).map((row) => ({ kind, text: row })));
  return wrapped.slice(-rows);
}
