#property strict
#property tester_file "m2b-work.tsv"
#include "Broker.mqh"
#include "Telemetry.mqh"

FxGateway fixed_gateway;
bool reconcile_needed=true;
int work_file=INVALID_HANDLE;
FxWork telemetry_work;
bool telemetry_ready=false;

int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) { Print("FX_M2B_CONNECTED_EXECUTION_DISABLED"); return INIT_FAILED; }
   if(AccountInfoInteger(ACCOUNT_LOGIN)!=42 || !SymbolInfoInteger(_Symbol,SYMBOL_CUSTOM)) return INIT_FAILED;
   if(!fixed_gateway.Open("fx-m2b/fixture-42.journal")) return INIT_FAILED;
   work_file=FileOpen("m2b-work.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(work_file==INVALID_HANDLE) { fixed_gateway.Close(); return INIT_FAILED; }
   EventSetTimer(1);
   return INIT_SUCCEEDED;
}

void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   // Callback order is not authoritative. Reconstruct using fresh broker queries.
   reconcile_needed=true;
}

void FxPublishTelemetry()
{
   if(telemetry_ready) { FxContext context=FxNativeContext(fixed_gateway,telemetry_work); FxTelemetry(context,telemetry_work.symbol); }
}
void OnTimer()
{
   if(reconcile_needed) { FxReconcile(fixed_gateway); reconcile_needed=false; }
   FxPublishTelemetry();
}
void OnTick()
{
   FxReconcile(fixed_gateway);
   if(work_file!=INVALID_HANDLE && !FileIsEnding(work_file))
   {
      string frame=FileReadString(work_file);
      if(frame!="")
      {
         FxWork work;
         if(FxDecode(frame,work)=="OK") { telemetry_work=work; telemetry_ready=true; }
         Print("FX_M2B_DISPATCH ",FxDispatch(fixed_gateway,frame));
      }
   }
   FxPublishTelemetry();
}
void OnDeinit(const int reason)
{
   EventKillTimer(); if(work_file!=INVALID_HANDLE) FileClose(work_file); fixed_gateway.Close();
}
