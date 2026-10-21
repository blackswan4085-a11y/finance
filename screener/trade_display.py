"""Money formatting shared by all three trade reports, including offline HTML."""

MONEY_JS = r"""
function formatTradeMoney(v, currency){
  if(v===null||v===undefined||!Number.isFinite(Number(v))) return '-';
  const value=Number(v), a=Math.abs(value), sign=value<0?'-':'';
  if(a>=1e9) return sign+currency+(a/1e9).toFixed(2)+'B';
  if(a>=1e6) return sign+currency+(a/1e6).toFixed(2)+'M';
  if(a>=1e3) return sign+currency+(a/1e3).toFixed(1)+'K';
  return sign+currency+Math.round(a).toLocaleString('en-US');
}
function formatTradeUnitPrice(v, currency){
  if(v===null||v===undefined||!Number.isFinite(Number(v))) return '-';
  const value=Number(v), a=Math.abs(value), sign=value<0?'-':'';
  if(a>=1e9) return sign+currency+(a/1e9).toFixed(2)+'B';
  if(a>=1e6) return sign+currency+(a/1e6).toFixed(2)+'M';
  if(a>=1e3) return sign+currency+(a/1e3).toFixed(2)+'K';
  return sign+currency+a.toFixed(a>=1?2:4);
}
"""
