import { changeTokens, type ChangeTokenKind } from "@/lib/changeTokens";

/** 把含漲跌 % 與價格的句子上色:紅漲綠跌(台股慣例)、價格用主色藍粗體(使用者 2026-10-03:
 *  「粗體以外還要其他顏色」),與紅綠分得開。符號與文字照留,顏色不是唯一訊號。
 *  `prices={false}`:只上漲跌色、不標價格——給理由 pill 這類句子用,裡面的小數多半是
 *  倍數或億(「為20日均值3.2倍」),不是股價。 */
const CLASS: Record<ChangeTokenKind, string> = {
  text: "",
  up: "font-semibold text-up",
  down: "font-semibold text-down",
  flat: "font-semibold text-foreground",
  price: "num font-bold text-primary",
};

export default function ChangeText({ text, prices = true }: { text: string; prices?: boolean }) {
  return (
    <>
      {changeTokens(text).map((t, i) =>
        t.kind === "text" || (t.kind === "price" && !prices) ? (
          <span key={i}>{t.text}</span>
        ) : (
          <span key={i} className={CLASS[t.kind]}>{t.text}</span>
        ),
      )}
    </>
  );
}
