#property strict
#property version "1.00"
#include "Kernel.mqh"
#include "NativePort.mqh"
#include "Reconcile.mqh"
#include "ProtectiveDispatch.mqh"
#include "../connected/HighResolutionClock.mqh"
input bool EnableDisabledGateway=false;
input bool BootstrapNewJournal=false;
input string RetainedJournalTip="";
input string Endpoint="";
input string Scope="",Client="",Release="",Policy="";
input long ExpectedLogin=0;
input string ExpectedServer="";
input string KeyFile="disabled-gateway.key";
input string JournalFile="disabled-gateway.journal";
input int DurationSeconds=180;
DemoKernel kernel;
DemoNativePort native_port;
DemoAcceptanceBudget native_budget;
input string BudgetPlanHash="",RetainedBudgetTip="";
input long BudgetStartsMs=0,BudgetExpiresMs=0,BudgetReferenceEquityCents=0;
input int BudgetPerEntryBps=25,BudgetTotalBps=50;
input string BudgetCurrency="CAD",BudgetEquityEvidence="";
DemoNativeHistory history;
DemoReconciler reconciler;
input string RetainedExecutionTip="",RetainedOutcomeTip="",RetainedBrokerStateTip="";
input string Broker="",EURUSDSymbol="EURUSD",USDJPYSymbol="USDJPY";
input bool QualifiedQuoteMapping=false,QualifiedSessionOpen=false;
input long QuoteOffsetMs=0,OperatingEvidenceUntilMs=0;
bool reconciling=false;
DemoProtectionStore protection;
input string RetainedProtectionTip="";
input long QualifiedRepairDelayMs=0,QualifiedExitDelayMs=0;
string native_incarnation="";
ShHighResolutionClock bounded_clock;
string dg_secret;
ulong started=0,due=0,synced=0,dg_counter=0;
int backoff=250;
bool Identity()
{
   return !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) &&
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO &&
      AccountInfoInteger(ACCOUNT_LOGIN)==ExpectedLogin && AccountInfoString(ACCOUNT_SERVER)==ExpectedServer;
}
void Stop(){ EventKillTimer(); kernel.Close(); protection.Close(); native_budget.Close(); bounded_clock.Reset(); dg_secret=""; ExpertRemove(); }
int OnInit()
{
   EventKillTimer(); kernel.Close(); protection.Close(); native_budget.Close(); bounded_clock.Reset(); dg_secret="";
   started=GetTickCount64(); due=0; synced=0; dg_counter=0; backoff=250;
   if(!EnableDisabledGateway || MQLInfoInteger(MQL_TESTER) || !Identity() || ExpectedLogin<=0 ||
      DurationSeconds<1 || DurationSeconds>300 || StringFind(Endpoint,"https://")!=0 ||
      StringSubstr(Endpoint,StringLen(Endpoint)-10)!="/v1/shadow" ||
      StringFind(Endpoint,"?")>=0 || StringFind(Endpoint,"#")>=0 || StringFind(Endpoint,"@")>=0 ||
      (BootstrapNewJournal && (PositionsTotal()!=0 || OrdersTotal()!=0))) return INIT_FAILED;
   int h=FileOpen(KeyFile,FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(h==INVALID_HANDLE) return INIT_FAILED;
   dg_secret=FileReadString(h); bool end=FileIsEnding(h); FileClose(h);
   if(!end || StringLen(dg_secret)<32 || StringLen(dg_secret)>64) return INIT_FAILED;
   for(int i=0;i<StringLen(dg_secret);i++) if(StringGetCharacter(dg_secret,i)<33 || StringGetCharacter(dg_secret,i)>126) return INIT_FAILED;
   if(!kernel.Open(JournalFile,Scope,Client,Release,Policy,dg_secret,BootstrapNewJournal,RetainedJournalTip,RetainedExecutionTip,RetainedOutcomeTip,RetainedBrokerStateTip)) return INIT_FAILED;
   native_incarnation=FxHash(Client+IntegerToString((long)GetMicrosecondCount())+IntegerToString((long)GetTickCount64()));
   if(!protection.Open(JournalFile+".protection",Scope,BootstrapNewJournal,RetainedProtectionTip)) { kernel.Close(); return INIT_FAILED; }
   if(!native_budget.Open(JournalFile+".budget",Scope,Release,Policy,BudgetPlanHash,
      BudgetStartsMs,BudgetExpiresMs,BudgetReferenceEquityCents,BudgetPerEntryBps,BudgetTotalBps,
      BudgetCurrency,BudgetEquityEvidence,BootstrapNewJournal,RetainedBudgetTip))
   {kernel.Close();protection.Close();return INIT_FAILED;}
   native_port.BindBudget(GetPointer(native_budget));
   native_port.BindProtection(GetPointer(protection),native_incarnation,QualifiedRepairDelayMs,QualifiedExitDelayMs);
   native_port.Bind(Broker,ExpectedServer,IntegerToString(ExpectedLogin),Release,Policy,EURUSDSymbol,USDJPYSymbol,kernel.State(),GetPointer(bounded_clock));
   if(!EventSetMillisecondTimer(250)){ kernel.Close();protection.Close();native_budget.Close();return INIT_FAILED; }
   return INIT_SUCCEEDED;
}
void OnTimer()
{
   if(!protection.Healthy() || !native_budget.Healthy() || !Identity() || GetTickCount64()-started>=(ulong)DurationSeconds*1000){ Stop(); return; }
   long observed=0;int observed_error=0;
   bool clock_ok=bounded_clock.NowUs((long)GetMicrosecondCount(),observed,observed_error);
   native_port.Observe(observed,observed_error,QuoteOffsetMs,clock_ok && QualifiedQuoteMapping,QualifiedSessionOpen,false,false,OperatingEvidenceUntilMs);
   // Finish one pinned scan before beginning another. Partial scans never reset
   // already-settled protection deadlines or authorize a mutation.
   bool completed=false;
   if(reconciling) { string verdict=reconciler.Step(kernel.State(),history); if(verdict!="INCOMPLETE"){ reconciling=false;completed=true; } }
   else if(history.Begin(IntegerToString(ExpectedLogin),ExpectedServer,0,TimeTradeServer())) { reconciler.Begin(); reconciling=true; }
   FxGateway *gateway=kernel.State();
   for(int i=0;i<gateway.Count();i++)
   {
      FxEntry entry=gateway.At(i);
      bool positive=completed && history.Valid() && reconciler.Confirmed(i);
      if(positive && clock_ok && !kernel.PublishState(entry,observed,observed_error,reconciler.Proof(i),true)) { Stop();return; }
      if(entry.work.action!="ENTER")continue;
      // A native closure witness does not replace the separate backend audit.
      if(positive && clock_ok && entry.state=="CLOSED" && entry.filled>0)
         native_budget.ConfirmClosed(entry,observed,reconciler.Proof(i),true,PositionsTotal()==0 && OrdersTotal()==0);
      SProtection saved;
      if(!protection.Read(entry.work.id,saved))continue;
      if(reconciling && (saved.phase=="PROTECTED" || saved.phase=="CLOSED"))continue;
      bool attempted=false;
      string action=DemoProtect(gateway,i,protection,native_port,(long)GetTickCount64(),native_incarnation,
         (bool)TerminalInfoInteger(TERMINAL_CONNECTED),positive,attempted);
      if(action=="PROTECTION_JOURNAL_UNAVAILABLE") {Stop();return;}
      if(attempted){ history.Invalidate();reconciler.Invalidate();reconciling=false; }
   }
   if(GetTickCount64()<due) return;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)){ due=GetTickCount64()+1000; return; }
   long sent=(long)GetMicrosecondCount(),utc=0; int error=0;
   bool bounded=bounded_clock.NowUs(sent,utc,error);
   bool sync=!bounded || GetTickCount64()-synced>=1000;
   if(!bounded) utc=(long)TimeGMT()*1000;
   string pending=kernel.Pending();
   string op=sync ? "PULL" : (pending!="" ? "REPORT" : "PULL");
   string payload=sync ? "disabled-sync/1" : pending;
   string nonce=FxHash(Client+IntegerToString(utc)+IntegerToString(sent)+IntegerToString((long)GetTickCount64())+IntegerToString((long)++dg_counter));
   string request=ShEncode(dg_secret,"C2S",Scope,Client,nonce,utc,op,payload);
   char data[],result[]; string headers;
   int bytes=StringToCharArray(request,data,0,WHOLE_ARRAY,CP_UTF8)-1; ArrayResize(data,bytes);
   int status=WebRequest("POST",Endpoint,"Content-Type: application/octet-stream\r\nConnection: close\r\n",1500,data,result,headers);
   long received=(long)GetMicrosecondCount(),rtt=received-sent,now=0; int uncertainty=0;
   if(!protection.Healthy() || !native_budget.Healthy() || !Identity() || GetTickCount64()-started>=(ulong)DurationSeconds*1000){ Stop(); return; }
   bool current=bounded;
   if(sync) now=bounded ? utc+rtt/1000 : (long)TimeGMT()*1000;
   else current=bounded_clock.NowUs(received,now,uncertainty);
   string response_op,response;
   bool ok=status==200 && ArraySize(result)<=32768 && rtt>=0 && rtt<=2000000 &&
      (sync || current) && ShDecode(CharArrayToString(result,0,ArraySize(result),CP_UTF8),dg_secret,"S2C",Scope,Client,nonce,now,response_op,response);
   if(ok && sync)
   {
      string f[];
      ok=response_op=="WORK" && StringSplit(response,'\t',f)==3 && f[0]=="disabled-clock/1" &&
         FxInteger(f[1]) && FxInteger(f[2]) && StringToInteger(f[2])<=100 &&
         bounded_clock.SyncUs(StringToInteger(f[1]),(int)StringToInteger(f[2]),sent,received);
      if(ok) synced=GetTickCount64();
   }
   else if(ok && pending!="") ok=response_op=="ACK" && kernel.Ack(response);
   else if(ok && response_op=="WORK")
   {
      ok=bounded_clock.NowUs((long)GetMicrosecondCount(),now,uncertainty);
      if(ok) { native_port.Observe(now,uncertainty,QuoteOffsetMs,QualifiedQuoteMapping,QualifiedSessionOpen,false,false,OperatingEvidenceUntilMs); ok=kernel.Receive(response,now,uncertainty,native_port); }
   }
   else if(ok) ok=response_op=="EMPTY" && response=="";
   backoff=ok ? 250 : (int)MathMin(backoff*2,5000); due=GetTickCount64()+backoff;
   if(!ok) Print("DISABLED_GATEWAY_EXCHANGE_REFUSED");
}
void OnDeinit(const int reason){ EventKillTimer(); kernel.Close(); protection.Close(); native_budget.Close(); bounded_clock.Reset(); dg_secret=""; }

void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result)
{ history.Invalidate(); reconciler.Invalidate(); reconciling=false; }
