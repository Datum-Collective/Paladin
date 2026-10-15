/** The Paladin name with its mark. On the Windows app (html[data-platform="win32"]) the CSS shows the
 *  "P▲LADIN" wordmark instead, with the pixel-art eye standing in for the A. Both are static: no remote assets. */
export default function Brand({ big = false }) {
  return (
    <span className={big ? 'brand big' : 'brand'}>
      <span className="brand-mark" aria-hidden="true" />
      <span className="brand-name">Paladin</span>
      <span className="wordmark" aria-hidden="true">P<span className="wordmark-a" />LADIN</span>
    </span>
  )
}
