// Restricted, canonical M2A ExecutionRequest file codec for offline/Tester use.
// The file frame is NOT an authenticated production transport.
#ifndef FX_WIRE_MQH
#define FX_WIRE_MQH

string FxHash(const string text)
{
   uchar data[],key[],result[];
   int n=StringToCharArray(text,data,0,WHOLE_ARRAY,CP_UTF8);
   if(n<=0) return "";
   ArrayResize(data,n-1);
   if(CryptEncode(CRYPT_HASH_SHA256,data,key,result)!=32) return "";
   string out="";
   for(int i=0;i<32;i++) out+=StringFormat("%02x",result[i]);
   return out;
}

bool FxSafe(const string text)
{
   if(StringLen(text)>160) return false;
   for(int i=0;i<StringLen(text);i++)
   {
      ushort c=StringGetCharacter(text,i);
      if(c<32 || c>126 || c=='"' || c=='\\' || c=='\t' || c=='|' || c=='~') return text=="~";
   }
   return true;
}

bool FxHex(const string text,const int length)
{
   if(StringLen(text)!=length) return false;
   for(int i=0;i<length;i++)
   {
      ushort c=StringGetCharacter(text,i);
      if(!((c>='0' && c<='9') || (c>='a' && c<='f'))) return false;
   }
   return true;
}

bool FxUuid(const string text)
{
   if(StringLen(text)!=36) return false;
   if(StringSubstr(text,8,1)!="-" || StringSubstr(text,13,1)!="-" || StringSubstr(text,18,1)!="-" || StringSubstr(text,23,1)!="-") return false;
   string compact=text; StringReplace(compact,"-","");
   return FxHex(compact,32);
}

string FxQ(const string text){ return "\""+text+"\""; }
string FxNullable(const string text){ return text=="~" ? "null" : FxQ(text); }

bool FxInteger(const string text)
{
   int n=StringLen(text);
   if(n<1 || n>15 || (n>1 && StringGetCharacter(text,0)=='0')) return false;
   for(int i=0;i<n;i++) if(StringGetCharacter(text,i)<'0' || StringGetCharacter(text,i)>'9') return false;
   return true;
}

// Exact decimal to 1e-8 units. Reject unsupported precision instead of rounding.
bool FxUnits(const string text,long &units)
{
   int dot=StringFind(text,"."), n=StringLen(text);
   if(n<1 || n>18) return false;
   string whole=dot<0 ? text : StringSubstr(text,0,dot);
   string frac=dot<0 ? "" : StringSubstr(text,dot+1);
   if(!FxInteger(whole) || StringLen(whole)>8 || StringLen(frac)>8 || (dot>=0 && StringLen(frac)==0)) return false;
   for(int i=0;i<StringLen(frac);i++) if(StringGetCharacter(frac,i)<'0' || StringGetCharacter(frac,i)>'9') return false;
   if(StringLen(frac)>0 && StringGetCharacter(frac,StringLen(frac)-1)=='0') return false;
   while(StringLen(frac)<8) frac+="0";
   units=StringToInteger(whole)*100000000+StringToInteger(frac);
   return true;
}

string FxDecimal(const double value)
{
   string s=DoubleToString(value,8);
   while(StringLen(s)>0 && StringSubstr(s,StringLen(s)-1)=="0") s=StringSubstr(s,0,StringLen(s)-1);
   if(StringSubstr(s,StringLen(s)-1)==".") s=StringSubstr(s,0,StringLen(s)-1);
   return s;
}

long FxUtcMs(const string stamp,const bool ceil_creation=false)
{
   int n=StringLen(stamp);
   if(n!=20 && n!=27) return -1;
   if(StringSubstr(stamp,19,1)!=(n==20 ? "Z" : ".") || StringSubstr(stamp,n-1)!="Z") return -1;
   string base=StringSubstr(stamp,0,19);
   StringReplace(base,"T"," "); StringReplace(base,"-",".");
   datetime seconds=StringToTime(base);
   if(seconds<=0 || TimeToString(seconds,TIME_DATE|TIME_SECONDS)!=base) return -1;
   if(n==20) return (long)seconds*1000;
   string fraction=StringSubstr(stamp,20,6);
   for(int i=0;i<6;i++) if(StringGetCharacter(fraction,i)<'0' || StringGetCharacter(fraction,i)>'9') return -1;
   long micros=StringToInteger(fraction);
   return (long)seconds*1000+micros/1000+(ceil_creation && micros%1000!=0 ? 1 : 0);
}

struct FxWork
{
   string frame,digest,id,environment,broker,server,login,venue,release,policy,reservation;
   string action,symbol,broker_symbol,currency,side;
   long sequence,created_ms,expires_ms,volume,stop,target,expected_version;
   double max_risk;
   ulong position,order;
};

string FxCanonical(string &f[])
{
   string account="{\"broker\":"+FxQ(f[4])+",\"environment\":"+FxQ(f[3])+",\"login\":"+FxQ(f[6])+",\"server\":"+FxQ(f[5])+",\"venue\":"+FxQ(f[7])+"}";
   return "{\"account\":"+account+",\"action\":"+FxQ(f[16])+",\"broker_symbol\":"+FxQ(f[18])+
      ",\"created_at\":"+FxQ(f[9])+",\"currency\":"+FxQ(f[19])+",\"expected_state_version\":"+(f[27]=="~" ? "null" : f[27])+
      ",\"expires_at\":"+FxQ(f[10])+",\"intent_hash\":"+FxQ(f[13])+",\"kind\":\"execution_request\",\"max_risk\":"+FxQ(f[21])+
      ",\"max_volume\":"+FxQ(f[20])+",\"message_id\":"+FxQ(f[2])+",\"order_id\":"+FxNullable(f[26])+",\"policy_hash\":"+FxQ(f[12])+
      ",\"position_id\":"+FxNullable(f[25])+",\"release_hash\":"+FxQ(f[11])+",\"reservation_id\":"+FxQ(f[14])+",\"sequence\":"+f[8]+
      ",\"side\":"+FxNullable(f[22])+",\"snapshot_hash\":"+FxQ(f[15])+",\"stop\":"+FxNullable(f[23])+",\"symbol\":"+FxQ(f[17])+
      ",\"target\":"+FxNullable(f[24])+",\"version\":\"ea-protocol/1\"}";
}

string FxDecode(const string frame,FxWork &w)
{
   if(StringLen(frame)>4096) return "SCHEMA_INVALID";
   string f[];
   if(StringSplit(frame,'\t',f)!=28 || f[0]!="ea-file/1") return "SCHEMA_INVALID";
   for(int i=0;i<28;i++) if(!FxSafe(f[i]) || f[i]=="") return "SCHEMA_INVALID";
   if(!FxUuid(f[2]) || !FxUuid(f[14]) || !FxHex(f[1],64)) return "SCHEMA_INVALID";
   for(int i=11;i<=15;i++) if(i!=14 && !FxHex(f[i],64)) return "SCHEMA_INVALID";
   if(FxHash(FxCanonical(f))!=f[1]) return "HASH_MISMATCH";
   if(!FxInteger(f[8]) || StringToInteger(f[8])<1 || (f[27]!="~" && (!FxInteger(f[27]) || StringToInteger(f[27])<1))) return "SCHEMA_INVALID";
   if(f[3]!="PAPER" || f[7]!="SIMULATOR") return "ACCOUNT_MISMATCH";
   if(f[17]!="EURUSD" && f[17]!="USDJPY") return "UNSUPPORTED_SYMBOL";
   if(f[19]!="USD" && f[19]!="CAD") return "UNSUPPORTED_CURRENCY";
   w.frame=frame; w.digest=f[1]; w.id=f[2]; w.environment=f[3]; w.broker=f[4]; w.server=f[5]; w.login=f[6]; w.venue=f[7];
   w.sequence=StringToInteger(f[8]); w.created_ms=FxUtcMs(f[9],true); w.expires_ms=FxUtcMs(f[10]);
   w.release=f[11]; w.policy=f[12]; w.reservation=f[14]; w.action=f[16]; w.symbol=f[17]; w.broker_symbol=f[18]; w.currency=f[19];
   long risk;
   if(!FxUnits(f[20],w.volume) || w.volume<=0 || !FxUnits(f[21],risk)) return "SCHEMA_INVALID";
   w.max_risk=(double)risk/100000000; w.side=f[22]; w.stop=0; w.target=0;
   if(w.side!="~" && w.side!="BUY" && w.side!="SELL") return "SCHEMA_INVALID";
   if(f[23]!="~" && (!FxUnits(f[23],w.stop) || w.stop<=0)) return "SCHEMA_INVALID";
   if(f[24]!="~" && (!FxUnits(f[24],w.target) || w.target<=0)) return "SCHEMA_INVALID";
   if((f[25]!="~" && (!FxInteger(f[25]) || StringToInteger(f[25])<1)) || (f[26]!="~" && (!FxInteger(f[26]) || StringToInteger(f[26])<1))) return "SCHEMA_INVALID";
   w.position=f[25]=="~" ? 0 : (ulong)StringToInteger(f[25]); w.order=f[26]=="~" ? 0 : (ulong)StringToInteger(f[26]);
   w.expected_version=f[27]=="~" ? 0 : StringToInteger(f[27]);
   if(w.created_ms<0 || w.expires_ms<=w.created_ms) return "SCHEMA_INVALID";
   if(w.action=="ENTER")
   {
      if((w.side!="BUY" && w.side!="SELL") || w.stop<=0 || w.target<=0 || risk<=0 || w.position!=0 || w.order!=0) return "SCHEMA_INVALID";
   }
   else if(w.action=="CLOSE" || w.action=="TIGHTEN_STOP" || w.action=="CANCEL")
   {
      if(risk!=0 || w.expected_version<1 || (w.action=="CANCEL" ? w.order==0 : w.position==0)) return "SCHEMA_INVALID";
      if(w.action=="TIGHTEN_STOP" && w.stop<=0) return "SCHEMA_INVALID";
   }
   else return "UNSUPPORTED_ACTION";
   return "OK";
}
#endif
