#ifndef FX_SHADOW_PROTOCOL
#define FX_SHADOW_PROTOCOL
#include "../gateway/Wire.mqh"
#include "../safety/Fence.mqh"
#include "../safety/Preflight.mqh"
#include "Fields.mqh"
// Separate domain. No execution/gateway/broker object is instantiated.
string ShHex(string text)
{
   string out="";
   for(int i=0;i<StringLen(text);i++) out+=StringFormat("%02x",StringGetCharacter(text,i));
   return out;
}
bool ShUnhex(string text,string &out)
{
   out=""; if(text=="-") return true;
   if(StringLen(text)%2!=0 || !FxHex(text,StringLen(text))) return false;
   string digits="0123456789abcdef";
   for(int i=0;i<StringLen(text);i+=2)
   {
      int v=16*StringFind(digits,StringSubstr(text,i,1))+StringFind(digits,StringSubstr(text,i+1,1));
      if(v>126 || (v<32 && v!=9 && v!=10)) return false;
      out+=ShortToString((ushort)v);
   }
   return true;
}
string ShEncode(string key,string direction,string scope,string client,string nonce,long now,string op,string payload)
{
   if(!FxHex(scope,64) || !FxHex(client,64) || !FxHex(nonce,64)) return "";
   string prefix="shadow/1\t"+direction+"\t"+scope+"\t"+client+"\t"+nonce+"\t"+
      IntegerToString(now)+"\t"+IntegerToString(now+5000)+"\t"+op+"\t"+(payload=="" ? "-" : ShHex(payload));
   string mac=SHmac(key,prefix);
   if(mac=="" || StringLen(prefix)+65>32768) return "";
   return prefix+"\t"+mac;
}
bool ShDecode(string raw,string key,string direction,string scope,string client,string nonce,long now,string &op,string &payload)
{
   string f[]; op=""; payload="";
   if(StringLen(raw)>32768 || StringSplit(raw,'\t',f)!=10 || f[0]!="shadow/1" ||
      f[1]!=direction || f[2]!=scope || f[3]!=client || f[4]!=nonce ||
      !FxInteger(f[5]) || !FxInteger(f[6]) || !FxHex(f[9],64)) return false;
   long issued=StringToInteger(f[5]),expires=StringToInteger(f[6]);
   if(expires<=issued || expires-issued>5000 || issued>now+2000 || expires<=now) return false;
   string prefix=StringSubstr(raw,0,StringLen(raw)-65);
   if(SHmac(key,prefix)!=f[9] || !ShUnhex(f[8],payload)) return false;
   op=f[7];
   return op=="PULL" || op=="REPORT" || op=="WORK" || op=="EMPTY" || op=="ACK" || op=="ERROR";
}
bool ShWork(string work,string scope,string release,string policy,string &f[],string &values[])
{
   string keys[]; StringSplit(SHADOW_FIELDS,'\t',keys);
   if(StringLen(work)>4096 || StringSplit(work,'\t',f)!=9+ArraySize(keys) || f[0]!="shadow-work/1" ||
      !FxUuid(f[1]) || !FxHex(f[2],64) || f[3]!=scope || f[4]!=release || f[5]!=policy ||
      !FxInteger(f[6]) || StringToInteger(f[6])<1 || !FxInteger(f[7]) || !FxInteger(f[8]) ||
      StringToInteger(f[8])<=StringToInteger(f[7])) return false;
   ArrayResize(values,ArraySize(keys));
   for(int i=0;i<ArraySize(keys);i++)
   {
      string v=f[9+i]; if(StringLen(v)==0 || StringLen(v)>32) return false;
      if(keys[i]=="symbol" || keys[i]=="currency" || keys[i]=="side" || keys[i]=="commission_currency")
      { if(v!="EURUSD" && v!="USDJPY" && v!="USD" && v!="CAD" && v!="BUY" && v!="SELL") return false; }
      else
      {
         for(int n=0;n<StringLen(v);n++)
         { ushort c=StringGetCharacter(v,n); if((c<'0' || c>'9') && c!='.' && c!='-' && c!='E' && c!='e' && c!='+') return false; }
         if(!MathIsValidNumber(StringToDouble(v))) return false;
      }
      values[i]=v;
   }
   return SV(keys,values,"measured_at_ms")<=StringToInteger(f[7]);
}
string ShAssess(string work,string scope,string release,string policy,long now,int local_error)
{
   string f[],v[],k[];
   if(!ShWork(work,scope,release,policy,f,v) || local_error<0 || local_error>100000000) return "";
   StringSplit(SHADOW_FIELDS,'\t',k);
   long elapsed=now-(long)SV(k,v,"measured_at_ms");
   long error=(long)MathMax(local_error,SV(k,v,"clock_error_ms"));
   long age=(long)SV(k,v,"quote_age_ms")+elapsed+error;
   string reason; double volume=0,loss=0,gross=0,margin=0;
   if(now<StringToInteger(f[7]) || elapsed<0) reason="FUTURE_MESSAGE";
   else if(now+error>=StringToInteger(f[8])) reason="EXPIRED";
   else if(MathAbs((long)SV(k,v,"quote_age_ms")+elapsed)>100000000 ||
           MathAbs((long)SV(k,v,"conversion_age_ms")+elapsed)>100000000 ||
           MathAbs((long)SV(k,v,"expires_in_ms")-elapsed)>100000000) reason="STALE_SNAPSHOT";
   else
   {
      SSet(k,v,"clock_error_ms",IntegerToString(error));
      SSet(k,v,"quote_age_ms",IntegerToString((long)SV(k,v,"quote_age_ms")+elapsed));
      SSet(k,v,"conversion_age_ms",IntegerToString((long)SV(k,v,"conversion_age_ms")+elapsed));
      SSet(k,v,"expires_in_ms",IntegerToString((long)MathMin(SV(k,v,"expires_in_ms")-elapsed,StringToInteger(f[8])-now)));
      reason=SRisk(k,v,volume,loss,gross,margin);
   }
   return "shadow-receipt/1\t"+f[1]+"\t"+FxHash(work)+"\t"+f[6]+"\t"+reason+"\t"+
      IntegerToString(now)+"\t"+IntegerToString(age)+"\t"+FxDecimal(volume)+"\t"+IntegerToString(local_error)+"\t0";
}
#endif
