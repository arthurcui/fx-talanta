#property strict
#property version "1.00"
#include "Inbox.mqh"
// New no-order EA, deliberately separate from the Tester order gateway.
// No deployment is performed by this repository increment.
input bool EnableShadow=false;
input bool BootstrapNewInbox=false;
input string Endpoint=""; // exact private HTTPS /v1/shadow route; allowlist separately
input string Scope="";
input string Client="";
input string Release="";
input string Policy="";
input long ExpectedLogin=0;
input string ExpectedServer="";
input string KeyFile="fx-shadow-private.key"; // private ASCII key, never a parameter/log
input string JournalFile="fx-shadow.journal";
ShInbox inbox;
string shadow_key;
ulong due=0,shadow_counter=0;
int backoff=1000;
long last_utc=0;
bool Identity()
{
   return AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO &&
      AccountInfoInteger(ACCOUNT_LOGIN)==ExpectedLogin && AccountInfoString(ACCOUNT_SERVER)==ExpectedServer;
}
int OnInit()
{
   if(!EnableShadow || MQLInfoInteger(MQL_TESTER) || ExpectedLogin<=0 || !Identity() ||
      StringFind(Endpoint,"https://")!=0 || StringSubstr(Endpoint,StringLen(Endpoint)-10)!="/v1/shadow" ||
      StringFind(Endpoint,"?")>=0 || StringFind(Endpoint,"#")>=0 || StringFind(Endpoint,"@")>=0 ||
      !FxHex(Scope,64) || !FxHex(Client,64) || !FxHex(Release,64) || !FxHex(Policy,64)) return INIT_FAILED;
   int key=FileOpen(KeyFile,FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(key==INVALID_HANDLE) return INIT_FAILED;
   shadow_key=FileReadString(key); bool ending=FileIsEnding(key); FileClose(key);
   if(!ending || StringLen(shadow_key)<32 || StringLen(shadow_key)>64) return INIT_FAILED;
   for(int i=0;i<StringLen(shadow_key);i++) if(StringGetCharacter(shadow_key,i)<33 || StringGetCharacter(shadow_key,i)>126) return INIT_FAILED;
   if(!inbox.Open(JournalFile,Scope,Client,Release,Policy,shadow_key,BootstrapNewInbox)) return INIT_FAILED;
   if(!EventSetMillisecondTimer(250)) { inbox.Close(); return INIT_FAILED; }
   return INIT_SUCCEEDED;
}
void OnTimer()
{
   if(GetTickCount64()<due) return;
   long now=(long)TimeGMT()*1000;
   if(!Identity() || !TerminalInfoInteger(TERMINAL_CONNECTED) || now<last_utc)
   { due=GetTickCount64()+10000; Print("SHADOW_CHANNEL_UNAVAILABLE"); return; }
   last_utc=now;
   // Nonce uniqueness, not secrecy. Timestamp, client and microsecond shadow_counter
   // distinguish sessions; HMAC supplies authentication.
   string nonce=FxHash(Client+IntegerToString(now)+IntegerToString((long)GetMicrosecondCount())+IntegerToString((long)++shadow_counter));
   string pending=inbox.Pending();
   string request=ShEncode(shadow_key,"C2S",Scope,Client,nonce,now,pending=="" ? "PULL" : "REPORT",pending);
   char data[],result[]; string headers;
   int bytes=StringToCharArray(request,data,0,WHOLE_ARRAY,CP_UTF8)-1; ArrayResize(data,bytes);
   ulong started=GetTickCount64();
   int status=WebRequest("POST",Endpoint,"Content-Type: application/octet-stream\r\n",1500,data,result,headers);
   long received=(long)TimeGMT()*1000; string op,payload;
   bool ok=status==200 && ArraySize(result)<=32768 && GetTickCount64()-started<=2000 && received>=now &&
      ShDecode(CharArrayToString(result,0,ArraySize(result),CP_UTF8),shadow_key,"S2C",Scope,Client,nonce,received,op,payload);
   if(ok)
   {
      if(pending!="") ok=op=="ACK" && inbox.Ack(payload);
      // TimeGMT is second-resolution and no qualified clock adapter is wired.
      // Preserve 1000 ms uncertainty: never claim two-second entry eligibility.
      else if(op=="WORK") ok=inbox.Receive(payload,received,1000);
      else ok=op=="EMPTY" && payload=="";
   }
   backoff=ok ? 1000 : (int)MathMin(backoff*2,30000);
   due=GetTickCount64()+backoff;
   if(!ok) Print("SHADOW_EXCHANGE_FAILED");
}
void OnDeinit(const int reason){ EventKillTimer(); inbox.Close(); shadow_key=""; }
