export function TaiwanSources() {
  return <p className="px-4 py-3 text-xs text-muted-foreground">
    출처: 대만 금융감독관리위원회 증권선물국, 대만 증권거래소(TWSE) 및 장외거래센터(TPEx)의 월매출 공시.
    저장된 월매출은 과거 MOPS 공시와 최근 OpenAPI 공시를 포함하며 실시간이 아닙니다. 전년 대비 등은 공시 저장값입니다.{' '}
    <a className="underline" href="https://mops.twse.com.tw/" target="_blank" rel="noreferrer">MOPS 공시</a>{' · '}
    <a className="underline" href="https://data.gov.tw/dataset/18420" target="_blank" rel="noreferrer">상장 자료</a>{' · '}
    <a className="underline" href="https://data.gov.tw/dataset/56510" target="_blank" rel="noreferrer">장외 자료</a>{' · '}
    <a className="underline" href="https://data.gov.tw/license" target="_blank" rel="noreferrer">정부자료 개방 라이선스</a>
  </p>
}
