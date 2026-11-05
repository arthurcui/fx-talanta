// Independent exact-rational numerical oracle. No terminal, broker or network APIs.
import { readFileSync } from 'node:fs';

const gcd = (a,b) => { a=a<0n?-a:a; while(b) [a,b]=[b,a%b]; return a; };
function rat(n,d=1n) {
  if (d===0n) throw Error('zero denominator');
  if(d<0n) { n=-n; d=-d; }
  const g=gcd(n,d); return [n/g,d/g];
}
const add=(a,b)=>rat(a[0]*b[1]+b[0]*a[1],a[1]*b[1]);
const mul=(a,b)=>rat(a[0]*b[0],a[1]*b[1]);
const neg=a=>[-a[0],a[1]];
const sub=(a,b)=>add(a,neg(b));
const cmp=(a,b)=>{const d=a[0]*b[1]-b[0]*a[1];return d<0n?-1:d>0n?1:0;};
const abs=a=>a[0]<0n?neg(a):a;
const max=values=>values.reduce((a,b)=>cmp(a,b)>0?a:b);
const min=values=>values.reduce((a,b)=>cmp(a,b)<0?a:b);
function parse(s) {
  if(!/^-?\d+(\.\d+)?$/.test(s)) throw Error('finite plain decimal required');
  const places=(s.split('.')[1]??'').length;
  return rat(BigInt(s.replace('.','')),10n**BigInt(places));
}
// Closed weighted sum, not the production recursive Decimal implementation.
function weighted(values,seedLength,alpha) {
  const seed=mul(values.slice(0,seedLength).reduce(add,[0n,1n]),rat(1n,BigInt(seedLength)));
  const decay=sub([1n,1n],alpha);
  let weight=[1n,1n],tail=[0n,1n];
  for(let i=values.length-1;i>=seedLength;i--) {
    tail=add(tail,mul(weight,values[i])); weight=mul(weight,decay);
  }
  return add(mul(seed,weight),mul(alpha,tail));
}
const output=x=>({numerator:String(x[0]),denominator:String(x[1])});
function evaluate(c) {
  const closes=c.h1.map(parse), bars=c.m15.map(b=>Object.fromEntries(
    Object.entries(b).map(([k,v])=>[k,parse(v)])));
  if(closes.length<200||closes.length>1000||bars.length<21||bars.length>1000)
    throw Error('bounded warmed-up vectors required');
  const fast=weighted(closes,50,rat(2n,51n));
  const slow=weighted(closes,200,rat(2n,201n));
  const prior=bars.slice(-21,-1), signal=bars.at(-1);
  const direction=cmp(fast,slow);
  const side=direction>0&&cmp(signal.close,max(prior.map(b=>b.high)))>0?'BUY':
    direction<0&&cmp(signal.close,min(prior.map(b=>b.low)))<0?'SELL':null;
  const ranges=bars.slice(1).map((b,i)=>max([
    sub(b.high,b.low),abs(sub(b.high,bars[i].close)),abs(sub(b.low,bars[i].close))]));
  const atr=weighted(ranges,14,rat(1n,14n));
  const quantum=parse(c.quantum);
  const units=mul(mul(atr,rat(3n,2n)),rat(quantum[1],quantum[0]));
  const ceiling=(units[0]+units[1]-1n)/units[1];
  const stop=mul(rat(ceiling),quantum);
  return {name:c.name,side,ema50:output(fast),ema200:output(slow),atr14:output(atr),
    stop_distance:output(stop),target_distance:output(mul(stop,rat(2n)))};
}
const raw=readFileSync(0,'utf8');
if(raw.length>2*1024*1024) throw Error('input bound');
const cases=JSON.parse(raw);
if(!Array.isArray(cases)||cases.length>100) throw Error('case bound');
console.log(JSON.stringify(cases.map(evaluate)));
