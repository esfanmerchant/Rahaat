import { Emblem, type EmblemTone } from './Emblem';

/** The Rahat mark: the Noor emblem (an eight-point star, a lamp and eight homes). Kept for existing call sites. */
export function RahatMark({ size = 80, class: className = '', tone = 'paper', animate = false }: {
  size?: number;
  class?: string;
  tone?: EmblemTone;
  animate?: boolean;
}) {
  return <Emblem size={size} class={className} tone={tone} animate={animate} />;
}
