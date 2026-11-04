#ifndef FX_CONNECTED_HIGH_RESOLUTION_CLOCK
#define FX_CONNECTED_HIGH_RESOLUTION_CLOCK
// Authenticated response/nonce/server clock validation belongs to the caller.
// Use raw GetMicrosecondCount(), never GetTickCount64(), for both clock inputs.
// https://www.mql5.com/en/book/common/timing/timing_count
// The 2 ms guard covers counter/UTC conversion arithmetic under the assumed
// microsecond counter model. It is NOT a physical timer accuracy certificate.
// The existing 100 ppm rate envelope remains an assumption, charged for both
// the request interval and subsequent projection. No host clock adjustment,
// favorable sample selection, TimeGMT precision inference or quote-age credit.
class ShHighResolutionClock
{
private:
   bool valid;
   long anchor_utc,anchor_us,last_us,last_utc;
   int anchor_error,last_sync_bound;
   string reason;
   bool Reject(string why){ valid=false; reason=why; return false; }
   int Drift(long microseconds)
   {
      // ceil(microseconds * 100 ppm / 1000), avoiding multiplication overflow.
      return (int)((microseconds+9999999)/10000000);
   }
   bool Estimate(long microseconds,long &utc,int &error)
   {
      long elapsed=microseconds-anchor_us;
      if(elapsed<0 || elapsed>=5000000) return false;
      error=anchor_error+Drift(elapsed);
      if(error>100) return false;
      utc=anchor_utc+elapsed/1000; return true;
   }
public:
   ShHighResolutionClock()
   {
      valid=false; anchor_utc=0; anchor_us=0; anchor_error=0;
      last_us=-1; last_utc=-1; last_sync_bound=-1; reason="CLOCK_UNVERIFIED";
   }
   string Reason(){ return reason; }
   int LastSyncBoundMs(){ return last_sync_bound; }
   bool SyncUs(long server_ms,int error_ms,long sent_us,long recv_us)
   {
      last_sync_bound=-1;
      // Bounds leave room for midpoint, projection and interval arithmetic.
      // Check before subtraction; GetMicrosecondCount's ulong must fit long.
      if(server_ms<1 || server_ms>8999999999990000 || error_ms<0 || error_ms>100 ||
         sent_us<0 || recv_us<0 || sent_us>9000000000000000 || recv_us>9000000000000000)
         return Reject("CLOCK_UNVERIFIED");
      if(sent_us<last_us || recv_us<sent_us) return Reject("CLOCK_REGRESSION");
      long rtt=recv_us-sent_us;
      if(rtt>2000000) return Reject("CLOCK_UNVERIFIED");
      long midpoint=server_ms+rtt/2000;
      int uncertainty=error_ms+(int)((rtt+1999)/2000)+2+Drift(rtt);
      last_sync_bound=uncertainty;
      if(uncertainty>100) return Reject("CLOCK_UNVERIFIED");
      long previous=0; int previous_error=0;
      if(valid && Estimate(recv_us,previous,previous_error) &&
         (midpoint+uncertainty<previous-previous_error || midpoint-uncertainty>previous+previous_error))
         return Reject("CLOCK_INTERVAL_DISJOINT");
      if(midpoint<last_utc) return Reject("CLOCK_REGRESSION");
      anchor_utc=midpoint; anchor_us=recv_us; anchor_error=uncertainty;
      last_us=recv_us; last_utc=midpoint; valid=true; reason="CLOCK_BOUNDED";
      return true;
   }
   bool NowUs(long microseconds,long &utc,int &error)
   {
      utc=0; error=0;
      if(!valid) return false;
      if(microseconds<0 || microseconds>9000000000000000) return Reject("CLOCK_UNVERIFIED");
      if(microseconds<last_us) return Reject("CLOCK_REGRESSION");
      if(!Estimate(microseconds,utc,error))
      { utc=0; error=0; return Reject("CLOCK_EXPIRED"); }
      last_us=microseconds; last_utc=utc; return true;
   }
};
#endif
