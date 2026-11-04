#ifndef FX_DEMO_RUNTIME
#define FX_DEMO_RUNTIME
#include "../gateway/Core.mqh"
#include "../shadow/Protocol.mqh"
#include "../safety/Control.mqh"
#include "Protection.mqh"
// Runtime receives an already authenticated, account-fenced request. Its port is
// fixed by the compiled host, never selected by a request or model.
class DemoPort
{
public:
   virtual bool Enabled(){ return false; }
   virtual bool Context(const FxWork &w,FxContext &c){ return false; }
   virtual string Prepare(const FxWork &w,const FxContext &c,long lots,MqlTradeRequest &r){ return "PORT_UNAVAILABLE"; }
   virtual bool RefreshRisk(const FxWork &w,string &keys[],string &values[]){ return false; }
   virtual bool Immediate(const FxWork &w,string risk,const FxContext &c){ return false; }
   virtual bool BeforeMutation(const FxWork &w){ return false; }
   virtual bool NoMutation(const FxWork &w){return true;}
   virtual bool Send(MqlTradeRequest &r,MqlTradeResult &s){ return false; }
};
string DemoSafety(const FxWork &w,string risk,const SLoss &ledger,const FxContext &c,long &lots,DemoPort &port)
{
   string f[],v[],k[];
   if(!ShWork(risk,FxScope(w),w.release,w.policy,f,v) || f[1]!=w.id || f[2]!=w.digest || StringToInteger(f[6])!=w.sequence) return "SNAPSHOT_REQUEST_MISMATCH";
   StringSplit(SHADOW_FIELDS,'\t',k);
   if(SText(k,v,"symbol")!=w.symbol || SText(k,v,"currency")!=w.currency) return "SNAPSHOT_REQUEST_MISMATCH";
   string reason=FxValidate(w,c,lots,true); if(reason!="OK") return reason;
   if(w.action!="ENTER") return "OK";
   MqlDateTime dt; if(!TimeToStruct((datetime)(c.now_ms/1000),dt) || ledger.day!=dt.year*10000+dt.mon*100+dt.day) return "LOSS_DAY_UNRECONCILED"; // Ownership/version and no-loosening checks above apply even during a halt.
   if(SText(k,v,"side")!=w.side || MathAbs(SV(k,v,"stop")-(double)w.stop/1e8)>1e-10) return "SNAPSHOT_REQUEST_MISMATCH";
   if(!port.RefreshRisk(w,k,v)) return "BROKER_RISK_UNAVAILABLE";
   SSet(k,v,"clock_error_ms",IntegerToString((long)MathMax(c.clock_error_ms,SV(k,v,"clock_error_ms"))));
   double volume=0,loss=0,gross=0,margin=0;
   // Validate the original conversion relationship before deriving anything.
   // A refreshed quote must not repair an invalid authenticated snapshot.
   reason=SPreflight(k,v,ledger,c.now_ms-(long)SV(k,v,"measured_at_ms"),(double)w.volume/1e8,w.max_risk,true,true,volume,loss,gross,margin);
   if(reason!="ACCEPTED") return reason;
   double source_volume=volume,usd=SV(k,v,"usd_to_account");
   SSet(k,v,"bid",DoubleToString(c.bid,8)); SSet(k,v,"ask",DoubleToString(c.ask,8));
   // Only the symbol-price-derived legs change. The USD/account observation,
   // its age, original quote age and original source hash remain unchanged.
   SSet(k,v,"base_to_account",DoubleToString(w.symbol=="EURUSD" ? c.bid*usd : usd,16));
   SSet(k,v,"quote_to_account",DoubleToString(w.symbol=="EURUSD" ? usd : usd/c.bid,16));
   reason=SPreflight(k,v,ledger,c.now_ms-(long)SV(k,v,"measured_at_ms"),source_volume,w.max_risk,true,true,volume,loss,gross,margin);
   if(reason!="ACCEPTED") return reason;
   lots=((long)MathMin(lots,MathFloor(volume*1e8+0.000001))/c.lot_step)*c.lot_step;
   return lots>=c.min_lot ? "OK" : "MINIMUM_LOT";
}
string DemoFacts(const FxContext &c,long lots,string risk)
{
   return FxHash(risk)+","+IntegerToString(c.now_ms)+","+IntegerToString(c.tick_ms)+","+IntegerToString(c.clock_error_ms)+","+
      IntegerToString(lots)+","+DoubleToString(c.bid,8)+","+DoubleToString(c.ask,8)+","+IntegerToString(c.min_lot)+","+
      IntegerToString(c.max_lot)+","+IntegerToString(c.lot_step)+","+DoubleToString(c.tick_size,8)+","+DoubleToString(c.min_stop,8)+","+
      DoubleToString(c.freeze_distance,8)+","+IntegerToString((long)c.position)+","+IntegerToString((long)c.order)+","+
      IntegerToString(c.position_volume)+","+IntegerToString(c.position_version)+","+DoubleToString(c.accepted_stop,8)+","+
      DoubleToString(c.accepted_target,8)+","+(c.owned ? "1" : "0")+","+(c.unknown_exposure ? "1" : "0")+","+
      (c.mutation_unknown ? "1" : "0")+","+(c.owner_pause ? "1" : "0")+","+(c.loss_halt ? "1" : "0");
}
class DemoRuntime
{
private:
   FxGateway gateway;
   string bound_scope;
   bool ready;
public:
   DemoRuntime(){ ready=false; }
   bool Open(string file,string scope,bool bootstrap,string retained_tip)
   { bound_scope=scope; ready=gateway.Open(file,true,scope,bootstrap,retained_tip); return ready; }
   void Close(){ gateway.Close(); ready=false; }
   FxGateway *State(){ return GetPointer(gateway); }
   string Dispatch(string frame,string risk,const SLoss &ledger,DemoPort &port)
   {
      if(!ready) return "JOURNAL_UNAVAILABLE";
      FxWork w; string reason=FxDecode(frame,w,true); if(reason!="OK") return reason;
      if(FxScope(w)!=bound_scope) return "ACCOUNT_MISMATCH";
      for(int i=0;i<gateway.Count();i++){ FxEntry old=gateway.At(i); if(old.work.id==w.id) return old.work.digest==w.digest ? "REPLAY" : "HASH_CONFLICT"; }
      // Stable-ID replay is resolved by Admit before a second mutation can occur.
      FxContext c; if(!port.Context(w,c)) return gateway.Reject(frame,"CONTEXT_UNAVAILABLE");
      long lots=0; reason=DemoSafety(w,risk,ledger,c,lots,port);
      if(reason!="OK") return gateway.Reject(frame,reason);
      c.max_lot=(long)MathMin(c.max_lot,lots);
      int index=-1; reason=gateway.Admit(frame,c,index); if(reason!="OK") return reason;
      if(!gateway.Audit(index,DemoFacts(c,lots,risk))) return "JOURNAL_UNAVAILABLE";
      MqlTradeRequest request={};
      reason=port.Prepare(w,c,lots,request);
      if(reason!="OK") { gateway.AbortBeforeCall(index,reason); return reason; }
      if(!port.Enabled()) { gateway.AbortBeforeCall(index,"TRADING_DISABLED"); return "TRADING_DISABLED"; }
      if(!gateway.MarkSubmitting(index)) return "JOURNAL_UNAVAILABLE";
      // Refresh after persistence. Never increase the admitted amount or refresh
      // the captured source timestamp with a newer broker-cache quote.
      long retained=lots;
      if(!port.Context(w,c)) reason="CONTEXT_UNAVAILABLE";
      else reason=DemoSafety(w,risk,ledger,c,lots,port);
      lots=(long)MathMin(lots,retained);
      if(reason=="OK") reason=port.Prepare(w,c,lots,request);
      if(reason!="OK" || !port.Enabled())
      { string why=reason=="OK" ? "TRADING_DISABLED" : reason; gateway.AbortBeforeCall(index,why); return why; }
      if(!port.BeforeMutation(w)) { gateway.AbortBeforeCall(index,"PROTECTION_STORAGE_UNAVAILABLE"); return "PROTECTION_STORAGE_UNAVAILABLE"; }
      // Protection persistence is also before the final barrier. OrderCheck is
      // advisory and may block; there is no network or disk operation between
      // Immediate and the fixed port's submission call.
      retained=lots;
      if(!port.Context(w,c)) reason="CONTEXT_UNAVAILABLE";
      else reason=DemoSafety(w,risk,ledger,c,lots,port);
      lots=(long)MathMin(lots,retained);
      if(reason=="OK" && !gateway.Audit(index,DemoFacts(c,lots,risk))) return "JOURNAL_UNAVAILABLE";
      if(reason!="OK" || !port.Immediate(w,risk,c) || !port.Enabled())
      { string why=reason!="OK" ? reason : "FINAL_BARRIER_REFUSED"; gateway.AbortBeforeCall(index,why); if(!port.NoMutation(w))return "PROTECTION_JOURNAL_UNAVAILABLE";return why; }
      request.volume=(double)lots/1e8;
      if(w.action=="TIGHTEN_STOP") request.tp=c.accepted_target;
      MqlTradeResult result={}; bool sent=port.Send(request,result);
      bool accepted=sent && (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_DONE_PARTIAL || result.retcode==TRADE_RETCODE_PLACED);
      if(!gateway.Result(index,accepted,result.order,"RETCODE_"+IntegerToString(result.retcode))) return "JOURNAL_UNAVAILABLE";
      return accepted ? "ACKNOWLEDGED" : "OUTCOME_UNKNOWN";
   }
   string Protect(SProtection &state,long now,string boot,bool broker,bool reconciled,
                  bool protected_ok,bool closed,bool unknown,bool rejected, bool &mutation_requested)
   {
      SProtection proposed;
      return DgProtection(state,proposed,now,boot,true,broker,reconciled,protected_ok,closed,unknown,rejected,mutation_requested);
   }
};
#endif
