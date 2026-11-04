#property strict
#include "../../../mql5/connected/Clock.mqh"
int checks=0,failures=0,output=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(output,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   output=FileOpen("connected-clock-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(output==INVALID_HANDLE) return INIT_FAILED;
   long stamp=1800000000000,utc=0; int error=0;
   ShClock c;
   Check("initial-unverified",!c.Now(1,utc,error) && utc==0 && error==0);
   Check("odd-rtt-sync",c.Sync(stamp,10,1000,1021));
   Check("odd-rtt-interval",c.Now(1021,utc,error) && utc==stamp+10 && error==53);
   Check("aged-interval",c.Now(1022,utc,error) && utc==stamp+11 && error==54);
   Check("both-asymmetric-extremes",utc-error<=stamp-10+1 && utc+error>=stamp+10+21+1);
   ShClock boundary;
   Check("exact-error-sync",boundary.Sync(stamp,68,100,100));
   Check("exact-error-accepted",boundary.Now(100,utc,error) && utc==stamp && error==100);
   Check("aging-over-limit",!boundary.Now(101,utc,error) && boundary.Reason()=="CLOCK_EXPIRED");
   Check("fresh-resync",boundary.Sync(stamp+1,10,101,101));
   Check("just-before-expiry",boundary.Now(5100,utc,error) && utc==stamp+5000 && error==43);
   Check("exact-expiry",!boundary.Now(5101,utc,error));
   Check("expired-never-revives",!boundary.Now(200,utc,error));
   ShClock invalid;
   Check("server-error-excess",!invalid.Sync(stamp,69,1,1));
   Check("rtt-error-excess",!invalid.Sync(stamp,0,1,138));
   Check("rtt-excess",!invalid.Sync(stamp,0,1,2002));
   Check("negative-error",!invalid.Sync(stamp,-1,1,1));
   Check("negative-rtt",!invalid.Sync(stamp,0,2,1));
   Check("negative-counter",!invalid.Sync(stamp,0,-1,1));
   Check("zero-server-clock",!invalid.Sync(0,0,1,1));
   Check("overflow-guard",!invalid.Sync(9000000000000000,0,1,1));
   Check("invalid-has-no-clock",!invalid.Now(1,utc,error) && utc==0 && error==0);
   ShClock ordering;
   Check("ordered-sync",ordering.Sync(stamp,10,100,120));
   Check("ordered-now",ordering.Now(200,utc,error) && utc==stamp+90 && error==53);
   Check("old-request-rejected",!ordering.Sync(stamp+100,10,199,201) && ordering.Reason()=="CLOCK_REGRESSION");
   Check("current-request-recovery",ordering.Sync(stamp+100,10,200,220));
   Check("new-anchor",ordering.Now(220,utc,error) && utc==stamp+110 && error==52);
   Check("counter-regression",!ordering.Now(219,utc,error) && ordering.Reason()=="CLOCK_REGRESSION");
   ShClock jump;
   Check("jump-initial",jump.Sync(stamp,10,100,120));
   Check("disjoint-update",!jump.Sync(stamp+10000,10,200,220) && jump.Reason()=="CLOCK_INTERVAL_DISJOINT");
   Check("jump-invalidates",!jump.Now(220,utc,error));
   ShClock observed;
   Check("observed-initial",observed.Sync(stamp,10,100,120) && observed.Now(200,utc,error));
   Check("utc-regression",!observed.Sync(stamp+80,10,200,200) && observed.Reason()=="CLOCK_REGRESSION");
   FileFlush(output); FileClose(output);
   Print("FX_CONNECTED_CLOCK_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
