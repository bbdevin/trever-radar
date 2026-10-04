/**
 * 外資券商席位(docs/46 §7):融資×分點集中度比對時,外資席位的囤貨不算進「同期囤貨分點」——
 * 外資席位多為外資法人或其客戶的合計量,與融資(本國信用交易)不是同一群人。
 * 比 branchPctile.seatKind() 多認幾個不帶「X商」前綴的外資券商名稱;seatKind() 不動(標籤用途不同)。
 */
const FOREIGN_BROKER =
  /^(美商|港商|新加坡商|英商|瑞士商|法商|德商|日商|荷蘭商|香港商|澳商|加拿大商|韓商)|美林|摩根|花旗|高盛|瑞銀|野村|麥格理|瑞士信貸|德意志|大和|巴黎|匯豐|法銀|星展|法國興業/;

export function isForeignBroker(name: string): boolean {
  return FOREIGN_BROKER.test(name.replace(/^[(（][^)）]*[)）]/, "").trim());
}
