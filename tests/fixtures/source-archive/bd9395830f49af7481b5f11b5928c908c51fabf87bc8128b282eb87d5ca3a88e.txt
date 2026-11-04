#ifndef FX_DEMO_NATIVE_PORT
#define FX_DEMO_NATIVE_PORT
#include "Runtime.mqh"
#include "AcceptanceBudget.mqh"
#include "../connected/HighResolutionClock.mqh"
#include "../gateway/Broker.mqh"
// Hard release gate. Neither request, input setting nor Algo Trading can enable it.
const bool FX_DEMO_SUBMISSION_AUTHORIZED=false;
class DemoNativePort : public DemoPort
{
private:
   string broker,server,login,release,policy,eurusd,usdjpy;
   long now_ms,error_ms,offset_ms;
   bool mapped,session,paused,halted;
   FxGateway *state;
   ShHighResolutionClock *clock;
   long valid_until;
   DemoProtectionStore *protection;
   DemoAcceptanceBudget *budget;
   string boot,armed_before_send;
   long repair_delay,exit_delay;
public:
   DemoNativePort(){ budget=NULL; protection=NULL; boot=""; repair_delay=0;exit_delay=0; mapped=false; now_ms=0; error_ms=1000; state=NULL; clock=NULL; valid_until=0; paused=true; halted=true; session=false; }
   void Bind(string b,string s,string l,string r,string p,string eur,string jpy,FxGateway *journal,ShHighResolutionClock *verified_clock)
   { broker=b; server=s; login=l; release=r; policy=p; eurusd=eur; usdjpy=jpy; state=journal; clock=verified_clock; }
   void Observe(long now,int error,long qualified_offset,bool mapping_qualified,bool open,bool owner_pause,bool hard_halt,long evidence_until)
   { now_ms=now; error_ms=error; offset_ms=qualified_offset; mapped=mapping_qualified; session=open; paused=owner_pause; halted=hard_halt; valid_until=evidence_until; }
   virtual bool Enabled(){ return FX_DEMO_SUBMISSION_AUTHORIZED && budget!=NULL && budget.Healthy() && !MQLInfoInteger(MQL_TESTER) &&
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO && TerminalInfoInteger(TERMINAL_TRADE_ALLOWED); }
   virtual bool Context(const FxWork &w,FxContext &c)
   {
      int current_error=0;
      if(clock==NULL || !clock.NowUs((long)GetMicrosecondCount(),now_ms,current_error)) return false;
      error_ms=current_error;
      if(now_ms+error_ms>=valid_until || MathAbs(offset_ms)>50400000 || !mapped || error_ms<0 || error_ms>100 || state==NULL ||
         AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO ||
         IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))!=login || AccountInfoString(ACCOUNT_SERVER)!=server ||
         PositionsTotal()>1024 || OrdersTotal()>1024) return false;
      ZeroMemory(c); c.broker=broker; c.server=server; c.login=login;
      c.release=release; c.policy=policy; c.currency=AccountInfoString(ACCOUNT_CURRENCY);
      c.symbol=w.symbol=="EURUSD" ? eurusd : usdjpy; c.now_ms=now_ms; c.clock_error_ms=error_ms;
      MqlTick tick={}; if(!SymbolInfoTick(c.symbol,tick)) return false;
      c.tick_ms=tick.time_msc-offset_ms; c.bid=tick.bid; c.ask=tick.ask;
      c.connected=TerminalInfoInteger(TERMINAL_CONNECTED); c.session_open=session;
      c.owner_pause=paused; c.loss_halt=halted || protection==NULL || protection.HardHalt();
      c.unknown_exposure=protection==NULL || protection.Unresolved(w.action=="ENTER" && w.id==armed_before_send ? armed_before_send : ""); c.position_side="~";
      c.min_lot=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_MIN)*1e8);
      c.max_lot=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_MAX)*1e8);
      c.lot_step=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_STEP)*1e8);
      c.tick_size=SymbolInfoDouble(c.symbol,SYMBOL_TRADE_TICK_SIZE);
      double point=SymbolInfoDouble(c.symbol,SYMBOL_POINT);
      c.min_stop=SymbolInfoInteger(c.symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
      c.freeze_distance=SymbolInfoInteger(c.symbol,SYMBOL_TRADE_FREEZE_LEVEL)*point;
      for(int i=0;i<PositionsTotal();i++)
      {
         ulong ticket=PositionGetTicket(i); if(ticket==0) return false;
         bool owned=PositionGetInteger(POSITION_MAGIC)==(long)FX_MAGIC && FxKnownComment(state,PositionGetString(POSITION_COMMENT));
         if(!owned) c.unknown_exposure=true;
         if(PositionGetString(POSITION_SYMBOL)==c.symbol && (w.action=="ENTER" || ticket==w.position))
         {
            c.position=ticket; c.owned=owned; c.position_volume=(long)MathRound(PositionGetDouble(POSITION_VOLUME)*1e8);
            c.accepted_stop=PositionGetDouble(POSITION_SL); c.accepted_target=PositionGetDouble(POSITION_TP);
            c.position_side=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? "BUY" : "SELL";
            for(int j=0;j<state.Count();j++){ FxEntry e=state.At(j); if(e.position==ticket && e.work.action=="ENTER") c.position_version=e.version; }
         }
      }
      for(int i=0;i<OrdersTotal();i++)
      {
         ulong ticket=OrderGetTicket(i); if(ticket==0) return false;
         bool owned=OrderGetInteger(ORDER_MAGIC)==(long)FX_MAGIC && FxKnownComment(state,OrderGetString(ORDER_COMMENT));
         if(!owned) c.unknown_exposure=true;
         if(OrderGetString(ORDER_SYMBOL)==c.symbol && (w.action=="ENTER" || ticket==w.order))
         { c.order=ticket; if(w.action=="CANCEL"){ c.owned=owned; for(int j=0;j<state.Count();j++){ FxEntry e=state.At(j); if(e.order==ticket) c.position_version=e.version; } } }
      }
      for(int i=0;i<state.Count();i++){ FxEntry e=state.At(i);
         if(e.work.id!=w.id && e.work.action=="ENTER" && w.position!=0 && e.position==w.position &&
            (protection==NULL || protection.MutationPending(e.work.id)))c.mutation_unknown=true;
         if(e.work.id!=w.id && (e.remaining>0 || e.state=="READY" || e.state=="SUBMITTING" || e.state=="OUTCOME_UNKNOWN" || e.state=="PROTECTION_PENDING" || e.state=="ACKNOWLEDGED"))c.unknown_exposure=true;
         if(e.work.id!=w.id && (e.state=="SUBMITTING" || e.state=="OUTCOME_UNKNOWN" || e.state=="ACKNOWLEDGED") &&
            ((w.position!=0 && e.work.position==w.position) || (w.order!=0 && e.work.order==w.order))) c.mutation_unknown=true; }
      return true;
   }
   virtual string Prepare(const FxWork &w,const FxContext &c,long lots,MqlTradeRequest &request)
   {
      // Construction/ownership/risk checks remain available with trading off.
      // OrderCheck can itself refuse a disabled terminal; never reinterpret that as approval.
      return FxPrepare(w,c,lots,request);
   }
   virtual bool RefreshRisk(const FxWork &w,string &keys[],string &values[])
   {
      double equity=AccountInfoDouble(ACCOUNT_EQUITY),margin=AccountInfoDouble(ACCOUNT_MARGIN);
      if(equity<=0 || margin<0 || margin>SV(keys,values,"existing_margin")+0.000001 ||
         PositionsTotal()+OrdersTotal()>SV(keys,values,"occupied_slots") ||
         AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE)!=ACCOUNT_STOPOUT_MODE_PERCENT) return false;
      MqlTick tick={}; if(!SymbolInfoTick(w.broker_symbol,tick)) return false;
      ENUM_ORDER_TYPE side=w.side=="BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double price=w.side=="BUY" ? tick.ask : tick.bid,loss=0,required=0;
      if(!OrderCalcProfit(side,w.broker_symbol,1.0,price,(double)w.stop/1e8,loss) ||
         !OrderCalcMargin(side,w.broker_symbol,1.0,price,required) || required<=0) return false;
      SSet(keys,values,"equity",DoubleToString(MathMin(equity,SV(keys,values,"equity")),8));
      SSet(keys,values,"broker_loss_per_lot",DoubleToString(MathMax(MathAbs(loss),SV(keys,values,"broker_loss_per_lot")),8));
      SSet(keys,values,"broker_margin_per_lot",DoubleToString(MathMax(required,SV(keys,values,"broker_margin_per_lot")),8));
      return true;
   }
   void BindProtection(DemoProtectionStore *p,string incarnation,long repair_ms,long exit_ms)
   { protection=p; boot=incarnation;repair_delay=repair_ms;exit_delay=exit_ms; }
   virtual bool Immediate(const FxWork &w,string risk,const FxContext &c)
   {
      long at=0;int error=0;
      if(clock==NULL || !clock.NowUs((long)GetMicrosecondCount(),at,error) || error>100 || at<c.now_ms ||
         at+error>=w.expires_ms || at+error-c.tick_ms>2000) return false;
      if(w.action!="ENTER") return true;
      string f[],v[],k[]; if(!ShWork(risk,FxScope(w),w.release,w.policy,f,v)) return false;
      StringSplit(SHADOW_FIELDS,'\t',k);
      return SV(k,v,"quote_age_ms")+at-SV(k,v,"measured_at_ms")+MathMax(error,SV(k,v,"clock_error_ms"))<=2000;
   }
   void BindBudget(DemoAcceptanceBudget *value){budget=value;}
   virtual bool BeforeMutation(const FxWork &w)
   {
      if(protection==NULL || (w.action=="ENTER" && protection.HardHalt())) return false;
      if(w.action=="ENTER" && (budget==NULL || !budget.Charge(w,now_ms,PositionsTotal()==0 && OrdersTotal()==0,(long)MathFloor(AccountInfoDouble(ACCOUNT_EQUITY)*100.0))))return false;
      // Immutable local deadlines start before submission, never after its reply.
      if(w.action=="ENTER"){bool ok=protection.Begin(w.id,(long)GetTickCount64(),boot,repair_delay,exit_delay);if(ok)armed_before_send=w.id;return ok;}
      return true; // Owned risk reduction still has the gateway's durable SUBMITTING fence.
   }
   virtual bool NoMutation(const FxWork &w)
   {bool ok=w.action!="ENTER" || (protection!=NULL && protection.NoCall(w.id));armed_before_send="";return ok;}
   virtual bool Send(MqlTradeRequest &request,MqlTradeResult &result)
   {
      armed_before_send="";
      if(!Enabled() || IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))!=login ||
         AccountInfoString(ACCOUNT_SERVER)!=server) return false;
      return OrderSend(request,result);
   }
};
#endif
