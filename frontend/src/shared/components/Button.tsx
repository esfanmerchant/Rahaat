import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ComponentChildren } from 'preact';
import { Pictogram, type PictogramName } from './Pictogram';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger' | 'neutral';
/**
 * hero: the start button (96px). lg: citizen primary and answers (64px).
 * md: citizen secondary (48px, the minimum citizen tap target). sm: staff only (32px).
 */
export type ButtonSize = 'hero' | 'lg' | 'md' | 'sm';

const BASE =
  'inline-flex items-center justify-center text-center font-semibold select-none border-2 ' +
  'transition-colors duration-100 disabled:cursor-not-allowed aria-disabled:cursor-not-allowed';

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-primary text-white border-primary hover:bg-primary-strong hover:border-primary-strong active:bg-primary-strong ' +
    'disabled:bg-surface disabled:text-ink-subtle disabled:border-line',
  secondary:
    'bg-paper text-primary-strong border-primary hover:bg-primary-soft active:bg-primary-soft ' +
    'disabled:text-ink-subtle disabled:border-line disabled:bg-paper',
  quiet: 'bg-transparent text-ink border-transparent hover:bg-surface active:bg-surface disabled:text-ink-subtle',
  danger:
    'bg-danger text-white border-danger hover:bg-paper hover:text-danger active:bg-danger-soft active:text-danger ' +
    'disabled:bg-surface disabled:text-ink-subtle disabled:border-line',
  neutral:
    'bg-paper text-ink border-line-strong hover:bg-sunken active:bg-surface disabled:text-ink-subtle disabled:border-line',
};

const SIZES: Record<ButtonSize, { box: string; icon: number }> = {
  hero: { box: 'min-h-tap-xl px-6 py-3 gap-4 text-2xl rounded-lg', icon: 56 },
  lg: { box: 'min-h-tap-lg px-5 py-2 gap-3 text-xl rounded-lg', icon: 40 },
  md: { box: 'min-h-tap px-4 py-1.5 gap-2 text-lg rounded-md', icon: 28 },
  sm: { box: 'min-h-8 px-3 py-1 gap-1.5 text-sm rounded-sm border', icon: 18 },
};

interface CommonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Pictogram before the label (at the start side, so it flips in RTL). */
  icon?: PictogramName;
  /** Full width. */
  block?: boolean;
  class?: string;
  children?: ComponentChildren;
}

export function buttonClass({
  variant = 'primary',
  size = 'lg',
  block = false,
  extra = '',
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  extra?: string;
}): string {
  return `${BASE} ${VARIANTS[variant]} ${SIZES[size].box} ${block ? 'w-full' : ''} ${extra}`;
}

type ButtonProps = CommonProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'size' | 'class' | 'icon'> & {
    /** Shows a spinner and blocks repeat taps while a request runs. */
    busy?: boolean;
  };

export function Button({
  variant,
  size = 'lg',
  icon,
  block,
  busy = false,
  class: extra,
  children,
  type = 'button',
  disabled,
  ...rest
}: ButtonProps) {
  const iconSize = SIZES[size].icon;
  return (
    <button
      type={type}
      class={buttonClass({ variant, size, block, extra })}
      disabled={disabled === true || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <Spinner size={iconSize} /> : icon ? <Pictogram name={icon} size={iconSize} /> : null}
      {children}
    </button>
  );
}

type LinkButtonProps = CommonProps & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'size' | 'class' | 'icon'> & {
  href: string;
};

/** A link that looks like a button. In-app hrefs are routed by preact-iso without a reload. */
export function LinkButton({ variant, size = 'lg', icon, block, class: extra, children, ...rest }: LinkButtonProps) {
  return (
    <a class={buttonClass({ variant, size, block, extra: `no-underline ${extra ?? ''}` })} {...rest}>
      {icon ? <Pictogram name={icon} size={SIZES[size].icon} /> : null}
      {children}
    </a>
  );
}
