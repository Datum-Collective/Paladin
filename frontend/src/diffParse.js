/** Parse `git diff` output into files > hunks > lines with old/new line numbers. */
export function parseDiff(text) {
  const files = []
  let file = null
  let hunk = null
  let o = 0
  let n = 0
  for (const raw of (text || '').split('\n')) {
    if (raw.startsWith('diff --git ')) {
      const m = raw.match(/ b\/(.+)$/)
      file = { path: m ? m[1] : raw.slice(11), add: 0, del: 0, hunks: [], isNew: false }
      files.push(file)
      hunk = null
    } else if (!file) {
      continue
    } else if (raw.startsWith('new file')) {
      file.isNew = true
    } else if (raw.startsWith('@@')) {
      const m = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$/)
      o = m ? parseInt(m[1], 10) : 0
      n = m ? parseInt(m[2], 10) : 0
      hunk = { header: m ? m[3] : '', lines: [] }
      file.hunks.push(hunk)
    } else if (hunk && raw.startsWith('+')) {
      hunk.lines.push({ t: '+', text: raw.slice(1), n: n++ }); file.add++
    } else if (hunk && raw.startsWith('-')) {
      hunk.lines.push({ t: '-', text: raw.slice(1), o: o++ }); file.del++
    } else if (hunk && raw.startsWith(' ')) {
      hunk.lines.push({ t: ' ', text: raw.slice(1), o: o++, n: n++ })
    }
  }
  return files
}

/** Mark the changed middle of each paired -/+ line so the eye lands on what actually differs. */
export function withInline(lines) {
  const out = lines.map((l) => ({ ...l }))
  let i = 0
  while (i < out.length) {
    if (out[i].t !== '-') { i++; continue }
    let d = i
    while (d < out.length && out[d].t === '-') d++
    let a = d
    while (a < out.length && out[a].t === '+') a++
    const dels = d - i
    const adds = a - d
    for (let k = 0; k < Math.min(dels, adds); k++) {
      const x = out[i + k]
      const y = out[d + k]
      let p = 0
      while (p < x.text.length && p < y.text.length && x.text[p] === y.text[p]) p++
      let s = 0
      while (s < x.text.length - p && s < y.text.length - p &&
             x.text[x.text.length - 1 - s] === y.text[y.text.length - 1 - s]) s++
      x.mark = [p, x.text.length - s]
      y.mark = [p, y.text.length - s]
    }
    i = a
  }
  return out
}

