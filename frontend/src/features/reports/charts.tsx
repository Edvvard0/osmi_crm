import clsx from "clsx";

/**
 * Лёгкие SVG-графики без внешних библиотек. Подписи осей — обычный HTML (не масштабируются вместе с рисунком),
 * значения подставляются только как текст. Серии различаются штрихом/плотностью, а не только цветом.
 */

export interface ChartSeries { key: string; title: string; values: number[] }

const W = 600;
const H = 180;
const PAD = 6;

const DASH = ["", "6 4", "2 3", "10 3 2 3"];
const OPACITY = [1, 0.55, 0.35, 0.22];

function bounds(series: ChartSeries[]): { min: number; max: number } {
  let min = 0;
  let max = 0;
  for (const s of series) for (const v of s.values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (max === min) max = min + 1;
  return { min, max };
}

interface Props {
  categories: string[];
  series: ChartSeries[];
  /** Форматирование значения для подсказок и подписей оси. */
  format: (v: number) => string;
  label: string;
  className?: string;
}

function Legend({ series }: { series: ChartSeries[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
      {series.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="18" y2="4" className="stroke-accent" strokeWidth="2" strokeDasharray={DASH[i % DASH.length]} strokeOpacity={OPACITY[i % OPACITY.length]} />
          </svg>
          {s.title}
        </li>
      ))}
    </ul>
  );
}

function Axis({ min, max, format, categories }: { min: number; max: number; format: (v: number) => string; categories: string[] }) {
  // Одна категория рисуется по центру (точка/столбец) — и подпись ставим под ней, а не у левого края.
  if (categories.length === 1) {
    return (
      <div className="mt-1 text-center text-xs text-muted">
        <span>{categories[0]}</span> · {format(min)} … {format(max)}
      </div>
    );
  }
  return (
    <div className="mt-1 flex items-start justify-between gap-2 text-xs text-muted">
      <span>{categories[0] ?? ""}</span>
      <span className="text-center">
        {format(min)} … {format(max)}
      </span>
      <span>{categories.length > 1 ? categories[categories.length - 1] : ""}</span>
    </div>
  );
}

export function LineChart({ categories, series, format, label, className }: Props) {
  const { min, max } = bounds(series);
  const n = categories.length;
  const x = (i: number) => (n <= 1 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (n - 1));
  const y = (v: number) => H - PAD - ((v - min) * (H - 2 * PAD)) / (max - min);
  const colW = n > 0 ? W / n : W;
  return (
    <figure className={clsx("w-full", className)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} className="h-44 w-full overflow-visible">
        <line x1="0" y1={y(0)} x2={W} y2={y(0)} className="stroke-border" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {series.map((s, si) => (
          <polyline
            key={s.key}
            fill="none"
            className="stroke-accent"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeDasharray={DASH[si % DASH.length]}
            strokeOpacity={OPACITY[si % OPACITY.length]}
            vectorEffect="non-scaling-stroke"
            points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
        ))}
        {n === 1 &&
          series.map((s) => <circle key={s.key} cx={x(0)} cy={y(s.values[0] ?? 0)} r="3" className="fill-accent" />)}
        {categories.map((c, i) => (
          <rect key={`${c}-${i}`} x={x(i) - colW / 2} y="0" width={colW} height={H} fill="transparent">
            <title>{`${c}: ${series.map((s) => `${s.title} ${format(s.values[i] ?? 0)}`).join("; ")}`}</title>
          </rect>
        ))}
      </svg>
      <Axis min={min} max={max} format={format} categories={categories} />
      <Legend series={series} />
    </figure>
  );
}

export function BarChart({ categories, series, format, label, className }: Props) {
  const { min, max } = bounds(series);
  const n = Math.max(categories.length, 1);
  const k = Math.max(series.length, 1);
  const slot = W / n;
  // Ширина столбца ограничена: при одной-двух категориях иначе получается сплошная плашка на весь график.
  const barW = Math.max(Math.min((slot * 0.7) / k, 40), 1);
  const groupPad = (slot - barW * k) / 2;
  const y = (v: number) => H - PAD - ((v - min) * (H - 2 * PAD)) / (max - min);
  const zero = y(0);
  return (
    <figure className={clsx("w-full", className)}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} className="h-44 w-full overflow-visible">
        <line x1="0" y1={zero} x2={W} y2={zero} className="stroke-border" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {categories.map((c, i) => (
          <g key={`${c}-${i}`}>
            <title>{`${c}: ${series.map((s) => `${s.title} ${format(s.values[i] ?? 0)}`).join("; ")}`}</title>
            {series.map((s, si) => {
              const v = s.values[i] ?? 0;
              const top = Math.min(y(v), zero);
              return (
                <rect
                  key={s.key}
                  x={i * slot + groupPad + si * barW}
                  y={top}
                  width={barW}
                  height={Math.max(Math.abs(y(v) - zero), v === 0 ? 0 : 1)}
                  className="fill-accent"
                  fillOpacity={OPACITY[si % OPACITY.length]}
                />
              );
            })}
          </g>
        ))}
      </svg>
      <Axis min={min} max={max} format={format} categories={categories.length > 8 ? [categories[0] ?? "", categories[categories.length - 1] ?? ""] : categories} />
      <Legend series={series} />
    </figure>
  );
}
