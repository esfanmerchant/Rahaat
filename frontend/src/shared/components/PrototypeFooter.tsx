/** Exact wording required in every footer (CLAUDE.md). Do not edit casually. */
export const PROTOTYPE_LABEL_EN =
  'Prototype. Not an official service. All identity, payment and data services are simulated.';
export const PROTOTYPE_LABEL_UR =
  'یہ آزمائشی نمونہ ہے، سرکاری سروس نہیں۔ شناخت، ادائیگی اور ڈیٹا کی سب سروسز فرضی ہیں۔';

interface PrototypeFooterProps {
  density?: 'citizen' | 'staff';
}

/** Shown in both languages regardless of the UI language. */
export function PrototypeFooter({ density = 'citizen' }: PrototypeFooterProps) {
  const box =
    density === 'citizen'
      ? 'px-4 py-4 text-sm flex flex-col gap-1'
      : 'px-3 py-1.5 text-xs flex flex-wrap gap-x-6 gap-y-0.5 justify-center';
  return (
    <footer class={`border-t border-line bg-surface text-center text-ink-muted ${box}`}>
      <p lang="en" dir="ltr">
        {PROTOTYPE_LABEL_EN}
      </p>
      <p lang="ur" dir="rtl">
        {PROTOTYPE_LABEL_UR}
      </p>
    </footer>
  );
}
