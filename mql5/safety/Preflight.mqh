#ifndef FX_SAFETY_PREFLIGHT
#define FX_SAFETY_PREFLIGHT
#include "Risk.mqh"
#include "Control.mqh"
void SSet(string &keys[],string &values[],string name,string value)
{
   for(int i=0;i<ArraySize(keys);i++) if(keys[i]==name) { values[i]=value; return; }
}
// Read-only integration point: the native durable state overrides entry flags.
// Caps come from the authenticated M2A request; values can only narrow them.
// Fresh account/snapshot binding, transport and real send integration remain gated.
string SPreflight(string &keys[],string &snapshot[],const SLoss &ledger,long elapsed_ms,
                 double request_volume,double request_risk,bool fenced,bool storage,
                 double &volume,double &loss,double &gross,double &margin)
{
   volume=0; loss=0; gross=0; margin=0;
   if(!fenced || !storage) return "STORAGE_OR_FENCE_BLOCK";
   if(elapsed_ms<0) return "SNAPSHOT_FUTURE";
   if(SV(keys,snapshot,"day_start")!=ledger.start || SV(keys,snapshot,"day_loss")!=ledger.loss) return "SNAPSHOT_STATE_CONFLICT";
   string v[]; ArrayCopy(v,snapshot);
   int flags=(int)SV(keys,v,"flags");
   if(ledger.hard) flags|=1; if(ledger.paused) flags|=2; if(ledger.owner) flags|=64;
   SSet(keys,v,"flags",IntegerToString(flags));
   SSet(keys,v,"quote_age_ms",IntegerToString((long)SV(keys,v,"quote_age_ms")+elapsed_ms));
   SSet(keys,v,"conversion_age_ms",IntegerToString((long)SV(keys,v,"conversion_age_ms")+elapsed_ms));
   SSet(keys,v,"expires_in_ms",IntegerToString((long)SV(keys,v,"expires_in_ms")-elapsed_ms));
   SSet(keys,v,"request_volume",DoubleToString(MathFloor(MathMin(request_volume,SV(keys,v,"request_volume"))*1e8)/1e8,8));
   SSet(keys,v,"request_risk",DoubleToString(MathFloor(MathMin(request_risk,SV(keys,v,"request_risk"))*1e8)/1e8,8));
   return SRisk(keys,v,volume,loss,gross,margin);
}
#endif
