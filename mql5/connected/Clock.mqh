#ifndef FX_CONNECTED_CLOCK
#define FX_CONNECTED_CLOCK
// Authenticated response/nonce/server clock validation belongs to the caller.
// Counter granularity guard: GetTickCount64 uses the Windows system timer.
// https://www.mql5.com/en/book/common/timing/timing_count
// No host clock adjustment, TimeGMT precision inference or quote-age credit.
class ShClock
{
private:
   bool valid;
   long anchor_utc,anchor_mono,last_mono,last_utc;
   int anchor_error;
   string reason;
   bool Reject(string why){ valid=false; reason=why; return false; }
   bool Estimate(long mono,long &utc,int &error)
   {
      long elapsed=mono-anchor_mono;
      if(elapsed<0 || elapsed>=5000) return false;
      error=anchor_error+(int)((elapsed*100+999999)/1000000);
      if(error>100) return false;
      utc=anchor_utc+elapsed; return true;
   }
public:
   ShClock(){ valid=false; anchor_utc=0; anchor_mono=0; anchor_error=0; last_mono=-1; last_utc=-1; reason="CLOCK_UNVERIFIED"; }
   string Reason(){ return reason; }
   bool Sync(long server_ms,int error_ms,long sent_mono,long recv_mono)
   {
      if(server_ms<1 || server_ms>8999999999995000 || error_ms<0 || error_ms>100 ||
         sent_mono<0 || recv_mono<0 || sent_mono>9000000000000000 || recv_mono>9000000000000000)
         return Reject("CLOCK_UNVERIFIED");
      if(sent_mono<last_mono || recv_mono<sent_mono) return Reject("CLOCK_REGRESSION");
      long rtt=recv_mono-sent_mono;
      if(rtt>2000) return Reject("CLOCK_UNVERIFIED");
      long midpoint=server_ms+rtt/2;
      int uncertainty=error_ms+(int)((rtt+1)/2)+32;
      if(uncertainty>100) return Reject("CLOCK_UNVERIFIED");
      long previous=0; int previous_error=0;
      if(valid && Estimate(recv_mono,previous,previous_error) &&
         (midpoint+uncertainty<previous-previous_error || midpoint-uncertainty>previous+previous_error))
         return Reject("CLOCK_INTERVAL_DISJOINT");
      if(midpoint<last_utc) return Reject("CLOCK_REGRESSION");
      anchor_utc=midpoint; anchor_mono=recv_mono; anchor_error=uncertainty;
      last_mono=recv_mono; last_utc=midpoint; valid=true; reason="CLOCK_BOUNDED";
      return true;
   }
   bool Now(long mono,long &utc,int &error)
   {
      utc=0; error=0;
      if(!valid) return false;
      if(mono<0 || mono>9000000000000000) return Reject("CLOCK_UNVERIFIED");
      if(mono<last_mono) return Reject("CLOCK_REGRESSION");
      if(!Estimate(mono,utc,error)){ utc=0; error=0; return Reject("CLOCK_EXPIRED"); }
      last_mono=mono; last_utc=utc; return true;
   }
};
#endif
