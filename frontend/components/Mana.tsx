import { BK_ICON_RU, bkIconUrl } from "@/lib/berserk";

/** Символы маны и стоимости ({W}, {2/U}, {T}) — официальные SVG Scryfall.
 *  Значки «Берсерка» в тексте - строчными словами ({tap}, {ova}) - картинки ProBerserk через наш сервер. */
const SYM = /\{([^}]+)\}/g;

function symbolUrl(s: string): string {
  return `/api/img/symbol/${s.replace(/\//g, "").toUpperCase()}.svg`;   // через наш сервер: см. lib/img.ts
}

export default function Mana({ text, size = 16 }: { text?: string | null; size?: number }) {
  if (!text) return null;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  SYM.lastIndex = 0;
  while ((m = SYM.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const bk = /^[a-z]{2,}$/.test(m[1]);
    parts.push(bk ? (
      <img key={m.index} src={bkIconUrl(m[1])} alt={BK_ICON_RU[m[1]] || m[1]} title={BK_ICON_RU[m[1]] || m[1]}
        height={size + 2} style={{ verticalAlign: "-0.25em", margin: "0 1px" }} />
    ) : (
      <img key={m.index} src={symbolUrl(m[1])} alt={`{${m[1]}}`} title={`{${m[1]}}`} width={size} height={size}
        style={{ verticalAlign: "-0.15em", margin: "0 1px" }} />,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}
