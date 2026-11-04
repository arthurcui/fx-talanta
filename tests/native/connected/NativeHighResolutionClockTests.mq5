#property strict
#include "../../../mql5/connected/HighResolutionClock.mqh"
int checks=0,failures=0,output=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(output,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   output=FileOpen("connected-high-resolution-clock-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(output==INVALID_HANDLE) return INIT_FAILED;
   long stamp=1800000000000,utc=0; int error=0;
   ShHighResolutionClock c;
   Check("initial-unverified",!c.NowUs(1,utc,error) && utc==0 && error==0 && c.LastSyncBoundMs()==-1);
   Check("73ms-server-10ms-rtt",c.SyncUs(stamp,73,1000000,1010000));
   Check("rtt-drift-included",c.NowUs(1010000,utc,error) && utc==stamp+5 && error==81 && c.LastSyncBoundMs()==81);
   Check("one-microsecond-aging",c.NowUs(1010001,utc,error) && utc==stamp+5 && error==82);
   Check("integer-projection",c.NowUs(1011000,utc,error) && utc==stamp+6 && error==82);
   Check("both-asymmetric-extremes",utc-error<=stamp-73+1 && utc+error>=stamp+73+10+1);

   c.Reset();
   Check("warm-reinit-invalidates-clock",!c.NowUs(1011001,utc,error) && utc==0 && error==0);
   Check("warm-reinit-clears-diagnostics",c.LastSyncBoundMs()==-1 && c.Reason()=="CLOCK_UNVERIFIED");
   Check("warm-reinit-requires-new-sync",c.SyncUs(stamp,10,100,1100));

   ShHighResolutionClock odd;
   Check("odd-microsecond-sync",odd.SyncUs(stamp,10,1000,11001));
   Check("odd-half-rtt-rounded-outward",odd.NowUs(11001,utc,error) && utc==stamp+5 && error==19);
   Check("fractional-projection-rounded-outward",odd.NowUs(13000,utc,error) && utc==stamp+6 && error==20);
   ShHighResolutionClock tiny;
   Check("one-microsecond-rtt",tiny.SyncUs(stamp,10,1000,1001) && tiny.NowUs(1001,utc,error) && utc==stamp && error==14);

   ShHighResolutionClock boundary;
   Check("98ms-zero-rtt-sync",boundary.SyncUs(stamp,98,100,100));
   Check("exact-100ms-bound",boundary.NowUs(100,utc,error) && utc==stamp && error==100);
   Check("aging-over-100ms-denied",!boundary.NowUs(101,utc,error) && utc==0 && error==0 && boundary.Reason()=="CLOCK_EXPIRED");
   Check("fresh-resync",boundary.SyncUs(stamp+1,10,101,101));
   Check("one-microsecond-before-five-seconds",boundary.NowUs(5000100,utc,error) && utc==stamp+5000 && error==13);
   Check("exact-five-seconds-expired",!boundary.NowUs(5000101,utc,error) && utc==0 && error==0);
   Check("expired-never-revives",!boundary.NowUs(200,utc,error));

   ShHighResolutionClock invalid;
   Check("99ms-zero-rtt-rejected",!invalid.SyncUs(stamp,99,1,1) && invalid.LastSyncBoundMs()==101);
   Check("rtt-budget-excess",!invalid.SyncUs(stamp,0,1,198001) && invalid.LastSyncBoundMs()==102);
   Check("exact-rtt-cap-still-fails-uncertainty",!invalid.SyncUs(stamp,0,1,2000001) && invalid.LastSyncBoundMs()==1003);
   Check("rtt-over-two-seconds",!invalid.SyncUs(stamp,0,1,2000002) && invalid.LastSyncBoundMs()==-1);
   Check("negative-error",!invalid.SyncUs(stamp,-1,1,1));
   Check("server-error-over-100ms",!invalid.SyncUs(stamp,101,1,1));
   Check("receive-before-send",!invalid.SyncUs(stamp,0,2,1) && invalid.Reason()=="CLOCK_REGRESSION");
   Check("negative-counter",!invalid.SyncUs(stamp,0,-1,1));
   Check("zero-server-clock",!invalid.SyncUs(0,0,1,1));
   Check("server-overflow-guard",!invalid.SyncUs(9000000000000000,0,1,1));
   Check("send-counter-overflow-guard",!invalid.SyncUs(stamp,0,9000000000000001,9000000000000001));
   Check("receive-counter-overflow-guard",!invalid.SyncUs(stamp,0,1,9000000000000001));
   Check("invalid-has-no-clock",!invalid.NowUs(1,utc,error) && utc==0 && error==0);

   ShHighResolutionClock ordering;
   Check("ordered-sync",ordering.SyncUs(stamp,10,100000,120000));
   Check("ordered-now",ordering.NowUs(200000,utc,error) && utc==stamp+90 && error==24);
   Check("old-request-rejected",!ordering.SyncUs(stamp+100,10,199999,220000) && ordering.Reason()=="CLOCK_REGRESSION");
   Check("old-request-invalidates",!ordering.NowUs(220000,utc,error));
   Check("current-request-recovery",ordering.SyncUs(stamp+100,10,200000,220000));
   Check("new-anchor",ordering.NowUs(220000,utc,error) && utc==stamp+110 && error==23);
   Check("counter-regression",!ordering.NowUs(219999,utc,error) && ordering.Reason()=="CLOCK_REGRESSION");

   ShHighResolutionClock jump;
   Check("jump-initial",jump.SyncUs(stamp,10,100000,120000));
   Check("disjoint-update",!jump.SyncUs(stamp+10000,10,200000,220000) && jump.Reason()=="CLOCK_INTERVAL_DISJOINT");
   Check("jump-invalidates",!jump.NowUs(220000,utc,error));
   ShHighResolutionClock observed;
   Check("observed-initial",observed.SyncUs(stamp,10,100000,120000) && observed.NowUs(200000,utc,error));
   Check("utc-regression",!observed.SyncUs(stamp+80,10,200000,200000) && observed.Reason()=="CLOCK_REGRESSION");

   ShHighResolutionClock restart;
   Check("restart-has-no-restored-anchor",!restart.NowUs(0,utc,error) && restart.LastSyncBoundMs()==-1);
   Check("restart-needs-fresh-sync",restart.SyncUs(stamp+100,10,0,1000) && restart.NowUs(1000,utc,error) && error==14);
   Check("restart-counter-reset-denied",!restart.NowUs(0,utc,error) && restart.Reason()=="CLOCK_REGRESSION");

   ShHighResolutionClock limit;
   Check("counter-upper-bound",limit.SyncUs(stamp,0,9000000000000000,9000000000000000) && limit.NowUs(9000000000000000,utc,error) && error==2);
   Check("now-counter-overflow-guard",!limit.NowUs(9000000000000001,utc,error) && limit.Reason()=="CLOCK_UNVERIFIED");
   ShHighResolutionClock malformed;
   Check("malformed-initial",malformed.SyncUs(stamp,10,0,0));
   Check("malformed-sync-invalidates-old-clock",!malformed.SyncUs(stamp,-1,1,1) && !malformed.NowUs(2,utc,error) && malformed.LastSyncBoundMs()==-1);
   FileFlush(output); FileClose(output);
   Print("FX_CONNECTED_HIGH_RESOLUTION_CLOCK_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
