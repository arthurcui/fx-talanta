#ifndef FX_DEMO_PROTECTIVE_DISPATCH
#define FX_DEMO_PROTECTIVE_DISPATCH
#include "Runtime.mqh"
// Fixed local risk-reduction authority, derived only from an owned ENTER record.
// It never consumes/reassigns backend sequence numbers or invents a signed request.
bool DemoDefiniteReject(uint code)
{
   return code==TRADE_RETCODE_REJECT || code==TRADE_RETCODE_INVALID || code==TRADE_RETCODE_INVALID_VOLUME ||
      code==TRADE_RETCODE_INVALID_PRICE || code==TRADE_RETCODE_INVALID_STOPS || code==TRADE_RETCODE_TRADE_DISABLED ||
      code==TRADE_RETCODE_MARKET_CLOSED || code==TRADE_RETCODE_NO_MONEY || code==TRADE_RETCODE_INVALID_FILL;
}
string DemoProtect(FxGateway &gateway,int index,DemoProtectionStore &store,DemoPort &port,
                   long mono,string boot,bool broker,bool confirmed,bool &attempted,bool campaign_close=false)
{
   attempted=false;
   if(index<0 || index>=gateway.Count()) return "INVALID_PARENT";
   FxEntry entry=gateway.At(index);
   if(entry.work.action!="ENTER" || !store.Has(entry.work.id)) return "NO_PROTECTION_STATE";
   string action=store.Step(entry.work.id,mono,boot,broker,confirmed,entry.state=="PROTECTED",
      entry.state=="CLOSED",entry.state=="OUTCOME_UNKNOWN",false,false);
   if(action=="JOURNAL_UNAVAILABLE" || action=="STORAGE_OR_STATE_MISSING")return "PROTECTION_JOURNAL_UNAVAILABLE";
   if(campaign_close && confirmed && broker && entry.state=="PROTECTED" && entry.open_volume>0)
   {
      // A positive protected position may be closed at campaign end. The same
      // retained one-shot exit fence covers both emergency and planned closure.
      if(store.ExitAttempted(entry.work.id))return "CAMPAIGN_EXIT_RECONCILE_NO_RESEND";
      SProtection current;
      if(!store.Read(entry.work.id,current) || current.boot!=boot || mono<current.last ||
         store.MutationPending(entry.work.id))return "CAMPAIGN_EXIT_UNRESOLVED";
      action="CONTROLLED_EXIT_ONCE";
   }
   if(action!="ATTACH_STOP_ONCE" && action!="CONTROLLED_EXIT_ONCE") return action;
   if(!port.Enabled()) return "TRADING_DISABLED";
   if(!confirmed || entry.position==0 || entry.open_volume<=0) return "RECONCILE_NO_MUTATION";
   FxWork local=entry.work; local.action=action=="ATTACH_STOP_ONCE" ? "TIGHTEN_STOP" : "CLOSE";
   local.position=entry.position;local.order=0;local.volume=entry.open_volume;local.max_risk=0;
   local.expected_version=entry.version;local.side="~";local.target=0;
   if(local.action=="CLOSE") local.stop=0;
   FxContext c; if(!port.Context(local,c)) return "CONTEXT_UNAVAILABLE";
   // A locally generated risk-reducing instruction has its own short deadline;
   // the original strategy entry expiry is never extended or reused for entry.
   local.created_ms=c.now_ms-c.clock_error_ms;local.expires_ms=c.now_ms+2000;
   long lots=0;string reason=FxValidate(local,c,lots,true);
   if(reason!="OK") return reason;
   MqlTradeRequest request={};reason=port.Prepare(local,c,lots,request);
   if(reason!="OK") return reason;
   string facts="LOCAL_PROTECTION,"+entry.work.digest+","+local.action+","+IntegerToString(entry.version)+","+DemoFacts(c,lots,"");
   if(!store.Arm(entry.work.id,action,mono,boot,facts)) return "PROTECTION_JOURNAL_UNAVAILABLE";
   attempted=true;long retained=lots;
   if(!port.Context(local,c)) reason="CONTEXT_UNAVAILABLE";
   else reason=FxValidate(local,c,lots,true);
   lots=(long)MathMin(lots,retained);
   if(reason=="OK")reason=port.Prepare(local,c,lots,request);
   if(reason=="OK" && !gateway.Audit(index,"LOCAL_PROTECTION,"+local.action+","+DemoFacts(c,lots,""))) return "PROTECTION_JOURNAL_UNAVAILABLE";
   if(reason!="OK" || !port.Immediate(local,"",c) || !port.Enabled())
   {
      if(!store.Result(entry.work.id,action,"REJECTED",0)) return "PROTECTION_JOURNAL_UNAVAILABLE";
      return "PROTECTION_NOT_SENT";
   }
   request.volume=(double)lots/1e8;
   if(local.action=="TIGHTEN_STOP") request.tp=c.accepted_target;
   MqlTradeResult result={};bool sent=port.Send(request,result);
   string outcome=sent && (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_DONE_PARTIAL || result.retcode==TRADE_RETCODE_PLACED) ?
      "ACKNOWLEDGED" : (DemoDefiniteReject(result.retcode) ? "REJECTED" : "UNKNOWN");
   if(!store.Result(entry.work.id,action,outcome,result.retcode)) return "PROTECTION_JOURNAL_UNAVAILABLE";
   return "PROTECTION_"+outcome;
}
#endif
