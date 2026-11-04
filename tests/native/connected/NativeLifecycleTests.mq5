#property strict
// Exercise the actual publisher's warm-init/failed-init path, without a broker.
#define OnInit PublisherInit
#define OnTick PublisherTick
#define OnTimer PublisherTimer
#define OnDeinit PublisherDeinit
#include "../../../mql5/readonly/QuoteStream.mq5"
#undef OnInit
#undef OnTick
#undef OnTimer
#undef OnDeinit
#include "../../../mql5/connected/HighResolutionClock.mqh"
int checks=0,failures=0,results=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(results,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   results=FileOpen("connected-lifecycle-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(results==INVALID_HANDLE) return INIT_FAILED;
   sequence=88; dropped=9; head=8; count=17; stopping=true;
   tick_callbacks=20; read_errors=3;
   Check("unbound-init-refused",PublisherInit()==INIT_PARAMETERS_INCORRECT);
   Check("warm-init-sequence-reset",sequence==0 && dropped==0);
   Check("warm-init-buffer-reset",head==0 && count==0 && !stopping);
   Check("warm-init-diagnostics-reset",tick_callbacks==0 && read_errors==0);
   Check("failed-init-no-handle",output==INVALID_HANDLE);
   PublisherDeinit(REASON_INITFAILED);
   Check("failed-init-cleanup-idempotent",output==INVALID_HANDLE && count==0);
   stopping=true; PublisherTick();
   Check("stopped-tick-ignored",count==0 && sequence==0);
   ShHighResolutionClock clock; long utc=0; int error=0;
   Check("initial-clock-unqualified",!clock.NowUs(0,utc,error));
   Check("clock-qualified",clock.SyncUs(1800000000000,10,0,1000));
   clock.Reset();
   Check("warm-init-clock-invalidated",!clock.NowUs(2000,utc,error));
   Check("warm-init-fresh-clock-required",clock.SyncUs(1800000001000,10,0,1000));
   FileFlush(results); FileClose(results); results=INVALID_HANDLE;
   Print("FX_LIFECYCLE_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
