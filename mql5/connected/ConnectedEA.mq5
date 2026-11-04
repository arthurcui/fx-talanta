#property strict
#property version "1.00"
#include "Inbox.mqh"
#include "HighResolutionClock.mqh"
// No order, position mutation, login, symbol selection or clock adjustment API.
input bool EnableConnected=false;
input bool BootstrapNewInbox=false;
input string ConfigFile="fx-connected-private.tsv";
CoInbox co_inbox;
ShHighResolutionClock co_clock;
string co_endpoint,co_scope,co_client,co_incarnation,co_epoch,co_server,co_binding,co_key,co_checkpoint;
long co_login=0,co_deadline=0,co_started=0,co_end=0,co_due=0,co_synced=0,co_nonce_counter=0;
int co_backoff=1000,co_diagnostics=0;
bool CoIdentity()
{
   return AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO &&
      AccountInfoInteger(ACCOUNT_LOGIN)==co_login && AccountInfoString(ACCOUNT_SERVER)==co_server &&
      TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)==0;
}
void CoLog(string code,bool final_marker=false)
{
   // Private bounded diagnostic log: no key, login, server, endpoint or prices.
   // Two of the 128 bounded entries are reserved for stop reason and deinit.
   if(co_checkpoint=="" || co_diagnostics>=(final_marker ? 128 : 126)) return;
   string path=co_checkpoint+".diagnostics";
   int file=FileOpen(path,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return;
   if(FileSize(file)<65536)
   {
      FileSeek(file,0,SEEK_END);
      FileWriteString(file,IntegerToString((long)GetTickCount64()-co_started)+"\t"+code+"\r\n");
      FileFlush(file); co_diagnostics++;
   }
   FileClose(file);
}
void CoStop(string reason){ CoLog(reason,true); EventKillTimer(); co_inbox.Close(); ExpertRemove(); }
bool CoEndpoint(string value)
{
   string suffix="/v1/connected-shadow";
   if(StringLen(value)<=StringLen(suffix) || StringSubstr(value,StringLen(value)-StringLen(suffix))!=suffix) return false;
   string origin=StringSubstr(value,0,StringLen(value)-StringLen(suffix)),port;
   if(StringFind(origin,"https://127.0.0.1:")==0) port=StringSubstr(origin,18);
   else if(StringFind(origin,"https://localhost:")==0) port=StringSubstr(origin,18);
   else return false;
   return FxInteger(port) && StringToInteger(port)>0 && StringToInteger(port)<=65535;
}
int OnInit()
{
   co_started=(long)GetTickCount64();
   if(!EnableConnected || MQLInfoInteger(MQL_TESTER) || !CoName(ConfigFile)) return INIT_FAILED;
   int file=FileOpen(ConfigFile,FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return INIT_FAILED;
   string raw=FileReadString(file); bool ending=FileIsEnding(file); FileClose(file);
   string f[];
   if(!ending || StringSplit(raw,'\t',f)!=13 || f[0]!="connected-config/1" || !CoEndpoint(f[1]) ||
      !FxHex(f[2],64) || !FxHex(f[3],64) || !FxHex(f[4],64) || !FxInteger(f[5]) || StringToInteger(f[5])<1 ||
      !FxInteger(f[6]) || StringToInteger(f[6])<1 || !FxSafe(f[7]) || f[7]=="" || !FxHex(f[8],64) ||
      !FxInteger(f[9]) || !CoName(f[10]) || !CoName(f[11]) || f[10]==f[11] || f[10]==ConfigFile || f[11]==ConfigFile ||
      StringLen(f[12])<32 || StringLen(f[12])>64) return INIT_FAILED;
   for(int i=0;i<StringLen(f[12]);i++) if(StringGetCharacter(f[12],i)<33 || StringGetCharacter(f[12],i)>126) return INIT_FAILED;
   co_endpoint=f[1]; co_scope=f[2]; co_client=f[3]; co_incarnation=f[4]; co_epoch=f[5];
   co_login=StringToInteger(f[6]); co_server=f[7]; co_binding=f[8]; co_deadline=StringToInteger(f[9]);
   co_key=f[12]; co_checkpoint=f[11];
   long coarse=(long)TimeGMT()*1000;
   if(!CoIdentity() || co_deadline<=coarse+1000 || co_deadline>coarse+900000)
   { CoLog("INIT_IDENTITY_OR_DEADLINE"); return INIT_FAILED; }
   co_end=co_started+co_deadline-coarse-1000;
   if(!co_inbox.Open(f[10],f[11],co_scope,co_client,co_incarnation,co_epoch,co_binding,co_key,BootstrapNewInbox))
   { CoLog("INIT_JOURNAL_REFUSED"); return INIT_FAILED; }
   if(!EventSetMillisecondTimer(250)){ co_inbox.Close(); CoLog("INIT_TIMER_FAILED"); return INIT_FAILED; }
   CoLog("STARTED_NO_ORDER"); return INIT_SUCCEEDED;
}
void OnTimer()
{
   long sent=(long)GetTickCount64(),utc=0; int error=0;
   if(sent>=co_end){ CoStop("DEADLINE_REACHED"); return; }
   if(sent<co_due) return;
   if(!CoIdentity()){ CoStop("IDENTITY_OR_TRADING_GUARD"); return; }
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   { CoLog("TERMINAL_DISCONNECTED"); co_due=sent+1000; return; }
   // GetTickCount64 controls scheduling only. The UTC clock receives raw
   // GetMicrosecondCount values, without converting or mixing counter epochs.
   long sent_us=(long)GetMicrosecondCount();
   if(sent_us<0){ CoStop("CLOCK_COUNTER_REGRESSION"); return; }
   bool bounded=co_clock.NowUs(sent_us,utc,error);
   if(bounded && utc+error>=co_deadline){ CoStop("DEADLINE_REACHED"); return; }
   bool sync=!bounded || sent-co_synced>=2000;
   if(!bounded) utc=(long)TimeGMT()*1000; // Bootstrap authentication only, never receipt/quote eligibility.
   string pending=co_inbox.Pending();
   string command=sync ? "SYNC" : (pending!="" ? "REPORT" : "PULL");
   string payload="connected/1\t"+command+"\t"+co_incarnation+"\t"+co_epoch;
   if(command=="REPORT") payload+="\t"+ShHex(pending);
   string nonce=FxHash(co_key+co_client+IntegerToString(utc)+IntegerToString(sent)+
      IntegerToString(sent_us)+IntegerToString(++co_nonce_counter));
   string request=ShEncode(co_key,"C2S",co_scope,co_client,nonce,utc,command=="REPORT" ? "REPORT" : "PULL",payload);
   char data[],result[]; string headers;
   int bytes=StringToCharArray(request,data,0,WHOLE_ARRAY,CP_UTF8)-1; ArrayResize(data,bytes);
   ResetLastError();
   int status=WebRequest("POST",co_endpoint,"Content-Type: application/octet-stream\r\n",1500,data,result,headers);
   int network_error=GetLastError(); long received_us=(long)GetMicrosecondCount();
   long received=(long)GetTickCount64();
   if(received_us<sent_us){ CoStop("CLOCK_COUNTER_REGRESSION"); return; }
   long rtt_us=received_us-sent_us;
   if(received>=co_end){ CoStop("DEADLINE_REACHED"); return; }
   if(!CoIdentity()){ CoStop("IDENTITY_OR_TRADING_GUARD"); return; }
   if(status!=200) CoLog(command+"_HTTP_"+IntegerToString(status)+"_ERROR_"+IntegerToString(network_error));
   long response_now=0; int response_error=0;
   // Do not advance the prior clock to receive time before Sync validates the
   // request's send counter. That would incorrectly classify it as an old request.
   bool current=bounded;
   if(sync) response_now=bounded ? utc+rtt_us/1000 : (long)TimeGMT()*1000;
   else current=co_clock.NowUs(received_us,response_now,response_error);
   string op,response;
   bool ok=status==200 && ArraySize(result)<=32768 && rtt_us<=2000000 &&
      (sync || current) && ShDecode(CharArrayToString(result,0,ArraySize(result),CP_UTF8),co_key,"S2C",co_scope,co_client,nonce,response_now,op,response);
   if(ok && sync)
   {
      string f[];
      bool clock_payload=op=="WORK" && StringSplit(response,'\t',f)==4 && f[0]=="connected/1" && f[1]=="CLOCK" &&
         FxInteger(f[2]) && FxInteger(f[3]) && StringToInteger(f[3])<=100;
      ok=clock_payload && co_clock.SyncUs(StringToInteger(f[2]),(int)StringToInteger(f[3]),sent_us,received_us);
      if(clock_payload)
         CoLog("CLOCK_SYNC_SERVER_ERROR_MS_"+f[3]+"_RTT_US_"+IntegerToString(rtt_us)+
            "_UNCERTAINTY_MS_"+IntegerToString(co_clock.LastSyncBoundMs())+"_ACCEPTED_"+(ok ? "1" : "0"));
      if(ok){ co_synced=received; CoLog("CLOCK_BOUNDED"); }
      else CoLog(co_clock.Reason());
   }
   else if(ok && command=="REPORT")
   {
      ok=op=="ACK" && co_inbox.Ack(response);
      if(ok) CoLog("RECEIPT_ACKNOWLEDGED"); else { CoStop("ACK_OR_JOURNAL_REFUSED"); return; }
   }
   else if(ok && op=="WORK")
   {
      string f[];
      if(!CoObservation(response,co_scope,co_binding,f)){ CoStop("OBSERVATION_REJECTED"); return; }
      MqlTick tick; long native_tick=0;
      if(SymbolInfoTick(f[9],tick) && tick.time_msc>0 && MathIsValidNumber(tick.bid) && MathIsValidNumber(tick.ask) && tick.bid>0 && tick.ask>=tick.bid)
      {
         native_tick=tick.time_msc-StringToInteger(f[13]);
         if(native_tick<=0) native_tick=0;
      }
      long assessed=(long)GetTickCount64(),assessed_us=(long)GetMicrosecondCount();
      if(!co_clock.NowUs(assessed_us,response_now,response_error)){ CoLog(co_clock.Reason()); ok=false; }
      else if(assessed>=co_end || response_now+response_error>=co_deadline){ CoStop("DEADLINE_REACHED"); return; }
      else if(response_now<StringToInteger(f[5]))
      {
         // A bounded midpoint may precede a very recent backend measurement.
         // Defer the same work; never persist a receipt the backend must reject.
         CoLog("OBSERVATION_MEASUREMENT_FUTURE"); co_due=assessed+250; return;
      }
      else
      {
         string receipt=CoReceipt(response,co_scope,co_binding,response_now,response_error,native_tick);
         if(receipt=="" || !co_inbox.Receive(response,receipt)){ CoStop("RECEIPT_JOURNAL_REFUSED"); return; }
         CoLog("HOLD_RECEIPT_DURABLE");
      }
   }
   else if(ok) ok=op=="EMPTY" && response=="";
   if(!ok && status==200) CoLog("AUTH_CLOCK_OR_RESPONSE_REJECTED");
   co_backoff=ok ? 1000 : (int)MathMin(co_backoff*2,30000);
   co_due=received+(ok ? 250 : co_backoff);
}
void OnDeinit(const int reason)
{
   CoLog("STOPPED_NO_ORDER",true); EventKillTimer(); co_inbox.Close(); co_key="";
}
