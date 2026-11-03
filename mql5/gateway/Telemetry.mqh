#ifndef FX_TELEMETRY_MQH
#define FX_TELEMETRY_MQH
#include "Core.mqh"
string FxIsoMs(const long ms)
{
   string stamp=TimeToString((datetime)(ms/1000),TIME_DATE|TIME_SECONDS);
   StringReplace(stamp,".","-"); StringReplace(stamp," ","T");
   return stamp+StringFormat(".%03dZ",(int)(ms%1000));
}

bool FxTelemetry(const FxContext &c,const string canonical_symbol)
{
   if(!MQLInfoInteger(MQL_TESTER)) return false;
   bool has_quote=c.tick_ms>0;
   string error=has_quote && c.now_ms-c.tick_ms>2000 ? "STALE_QUOTE" : "~";
   string body="{\"version\":\"channel-telemetry/1\",\"account\":{\"broker\":\"fixture\",\"server\":\"offline\",\"login\":\"42\",\"environment\":\"PAPER\",\"venue\":\"SIMULATOR\"},"+
      "\"symbol\":"+FxQ(canonical_symbol)+",\"channel\":\"EA\",\"capability\":\"QUOTES\",\"state\":"+FxQ(c.connected ? "HEALTHY" : "DISCONNECTED")+
      ",\"measured_at\":"+FxQ(FxIsoMs(c.now_ms))+",\"last_heartbeat\":"+FxQ(FxIsoMs(c.now_ms))+
      ",\"last_success\":"+(has_quote ? FxQ(FxIsoMs(c.now_ms)) : "null")+
      ",\"original_tick_at\":"+(has_quote ? FxQ(FxIsoMs(c.tick_ms)) : "null")+
      ",\"last_quote_receipt\":"+(has_quote ? FxQ(FxIsoMs(c.now_ms)) : "null")+
      ",\"last_error\":"+(error=="~" ? "null" : FxQ(FxIsoMs(c.now_ms)))+",\"error_code\":"+FxNullable(error)+
      ",\"delivery_median_ms\":null,\"delivery_p95_ms\":null,\"window_seconds\":null,\"samples\":0}";
   string path="fx-m2b/ea-quote.json";
   int file=FileOpen(path+".tmp",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return false;
   bool ok=FileWriteString(file,body)==StringLen(body); FileFlush(file); FileClose(file);
   return ok && FileMove(path+".tmp",0,path,FILE_REWRITE);
}
#endif
