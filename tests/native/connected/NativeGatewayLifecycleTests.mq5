#property strict
// Deterministic no-order handler fault injection, not terminal event-loss qualification.
bool FixtureHistorySelect(datetime from,datetime to){ return false; }
#define HistorySelect FixtureHistorySelect
#include "../../../mql5/gateway/Broker.mqh"
#undef HistorySelect
#include "../../../mql5/gateway/Telemetry.mqh"
bool timer_ok=false,reconciliation_ok=false;
int timer_attempts=0,reconciliations=0,dispatches=0;
bool FixtureTimer(int seconds){ timer_attempts++; return timer_ok; }
long FixtureAccount(ENUM_ACCOUNT_INFO_INTEGER property){ return 42; }
long FixtureSymbol(string symbol,ENUM_SYMBOL_INFO_INTEGER property){ return 1; }
bool FixtureReconcile(FxGateway &gateway){ reconciliations++; return reconciliation_ok; }
string FixtureDispatch(FxGateway &gateway,const string frame){ dispatches++; return "FIXTURE_NO_ORDER"; }
#define EventSetTimer FixtureTimer
#define AccountInfoInteger FixtureAccount
#define SymbolInfoInteger FixtureSymbol
#define FxReconcile FixtureReconcile
#define FxDispatch FixtureDispatch
#define OnInit GatewayInit
#define OnTimer GatewayTimer
#define OnTick GatewayTick
#define OnDeinit GatewayDeinit
#include "../gateway/FixedGateway.mq5"
#undef EventSetTimer
#undef AccountInfoInteger
#undef SymbolInfoInteger
#undef FxReconcile
#undef FxDispatch
#undef OnInit
#undef OnTimer
#undef OnTick
#undef OnDeinit
int checks=0,failures=0,results=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(results,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   results=FileOpen("gateway-lifecycle-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(results==INVALID_HANDLE) return INIT_FAILED;
   int fixture=FileOpen("m2b-work.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(fixture==INVALID_HANDLE) return INIT_FAILED;
   FileWriteString(fixture,"fixture-invalid-frame\r\n"); FileClose(fixture);
   Check("history-query-failure-is-incomplete",!FxReconcile(fixed_gateway));
   Check("timer-creation-failure-refused",GatewayInit()==INIT_FAILED && timer_attempts==1);
   Check("timer-failure-closes-work-file",work_file==INVALID_HANDLE);
   GatewayDeinit(REASON_INITFAILED);
   Check("failed-init-cleanup-idempotent",work_file==INVALID_HANDLE);
   timer_ok=true;
   Check("warm-init-opens-again",GatewayInit()==INIT_SUCCEEDED && timer_attempts==2);
   Check("warm-init-clears-transient-state",reconcile_needed && !telemetry_ready);
   GatewayTimer();
   Check("failed-reconciliation-retains-dirty",reconcile_needed && reconciliations==1);
   Check("failed-reconciliation-does-not-consume-work",dispatches==0 && FileTell(work_file)==0);
   reconciliation_ok=true; GatewayTimer();
   Check("timer-retries-without-tick",reconciliations==2 && !reconcile_needed);
   Check("timer-consumes-work-without-tick",dispatches==1);
   GatewayTimer();
   Check("timer-reconciles-without-notification",reconciliations==3 && dispatches==1);
   GatewayTick(); Check("tick-only-marks-dirty",reconcile_needed && dispatches==1);
   GatewayDeinit(REASON_REMOVE); Check("deinit-invalidates-file",work_file==INVALID_HANDLE);
   FileFlush(results); FileClose(results); results=INVALID_HANDLE;
   Print("FX_GATEWAY_LIFECYCLE_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
