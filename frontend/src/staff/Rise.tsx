/** A title that rises in word by word. The words are spans; the full text stays one readable string for screen readers. */
export function Rise({ text }: { text: string }) {
  const words = text.split(/\s+/).filter(Boolean);
  return (
    <span class="rise" key={text}>
      <span class="sr-only">{text}</span>
      <span aria-hidden="true">
        {words.map((w, i) => (
          <span key={`${i}-${w}`}>
            {i > 0 ? ' ' : ''}
            <span class="rise-w" style={{ '--w': i }}>
              <i>{w}</i>
            </span>
          </span>
        ))}
      </span>
    </span>
  );
}
