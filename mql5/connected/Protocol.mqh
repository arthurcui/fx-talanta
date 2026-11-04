#ifndef FX_CONNECTED_PROTOCOL
#define FX_CONNECTED_PROTOCOL
#include "../shadow/Protocol.mqh"
#include "Clock.mqh"
bool CoSigned(string value)
{
   if(StringSubstr(value,0,1)!="-") return FxInteger(value);
   string magnitude=StringSubstr(value,1);
   return magnitude!="0" && FxInteger(magnitude);
}
bool CoName(string value)
{
   if(StringLen(value)<1 || StringLen(value)>100 || StringFind(value,"..")>=0) return false;
   for(int i=0;i<StringLen(value);i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='a' && c<='z') || (c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_' || c=='.' || c=='-')) return false;
   }
   return true;
}
bool CoCodes(string value)
{
   if(StringLen(value)>1024) return false;
   for(int i=0;i<StringLen(value);i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_' || c==',')) return false;
   }
   return true;
}
bool CoObservation(string raw,string scope,string binding,string &f[])
{
   if(StringLen(raw)>2048 || StringSplit(raw,'\t',f)!=14 || f[0]!="connected-observation/1" ||
      !FxUuid(f[1]) || !FxInteger(f[2]) || StringToInteger(f[2])<1 || f[3]!=scope ||
      !FxHex(f[4],64) || !FxInteger(f[5]) || !FxInteger(f[6]) || !FxInteger(f[7]) ||
      (f[8]!="EURUSD" && f[8]!="USDJPY") || !CoName(f[9]) || !FxInteger(f[10]) ||
      !CoCodes(f[11]) || f[12]!=binding || !CoSigned(f[13])) return false;
   long measured=StringToInteger(f[5]),expires=StringToInteger(f[6]);
   return measured>0 && expires>measured && expires-measured<=60000 &&
      StringToInteger(f[7])<=100 && StringToInteger(f[10])>0 && MathAbs(StringToInteger(f[13]))<=50400000;
}
string CoReceipt(string observation,string scope,string binding,long now,int error,long native_tick)
{
   string f[];
   if(!CoObservation(observation,scope,binding,f) || now<StringToInteger(f[5]) || error<0 || error>100 || native_tick<0) return "";
   long source_error=(long)MathMax(error,StringToInteger(f[7]));
   long source_age=now-StringToInteger(f[10])+source_error;
   long native_age=native_tick==0 ? -1 : now-native_tick+error;
   string reason="REQUIRED_INPUTS";
   if(now+source_error>=StringToInteger(f[6])) reason="EXPIRED";
   else if(native_tick==0) reason="NATIVE_DATA_UNAVAILABLE";
   else if(now-StringToInteger(f[10])-source_error<0 || source_age>2000 ||
      now-native_tick-error<0 || native_age>2000) reason="QUOTE_STALE";
   return "connected-hold/1\t"+f[1]+"\t"+f[2]+"\t"+f[4]+"\t"+IntegerToString(now)+"\t"+
      IntegerToString(error)+"\t"+IntegerToString(source_age)+"\t"+IntegerToString(native_tick)+"\t"+
      IntegerToString(native_age)+"\t"+reason+"\t"+f[11]+"\t0";
}
bool CoReceiptValid(string observation,string receipt,string scope,string binding)
{
   string f[];
   if(StringSplit(receipt,'\t',f)!=12 || f[0]!="connected-hold/1" || !FxInteger(f[4]) ||
      !FxInteger(f[5]) || !FxInteger(f[7]) || f[11]!="0") return false;
   return CoReceipt(observation,scope,binding,StringToInteger(f[4]),(int)StringToInteger(f[5]),StringToInteger(f[7]))==receipt;
}
#endif
