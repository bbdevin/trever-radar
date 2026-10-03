import { changeTokens, type ChangeTokenKind } from "@/lib/changeTokens";

/** 把含漲跌 % 與價格的句子上色:紅漲綠跌(台股慣例)、價格用主色藍粗體(使用者 2026-10-03:
 *  「粗體以外還要其他顏色」),與紅綠分得開。符號與文字照留,顏色不是唯一訊號。 */
const CLASS: Record<ChangeTokenKind, string> = {
  text: "",
  up: "font-semibold text-up",
  down: "font-semibold text-down",
  flat: "font-semibold text-foreground",
  price: "num font-bold text-primary",
};

export default function ChangeText({ text }: { text: string }) {
  return (
    <>
      {changeTokens(text).map((t, i) =>
        t.kind === "text" ? <span key={i}>{t.text}</span> : <span key={i} className={CLASS[t.kind]}>{t.text}</span>,
      )}
    </>
  );
}
