#ifndef FX_BROKER_MQH
#define FX_BROKER_MQH
#include "Core.mqh"

const ulong FX_MAGIC=741236;
int fx_send_calls=0;
string FxComment(const FxWork &w){ return "FT"+StringSubstr(w.digest,0,24); }

// Sole order-sending boundary. There is deliberately NO live/demo enable input.
bool FxTesterSend(MqlTradeRequest &request,MqlTradeResult &result)
{
   if(!MQLInfoInteger(MQL_TESTER) || !SymbolInfoInteger(request.symbol,SYMBOL_CUSTOM)) return false;
   fx_send_calls++;
   return OrderSend(request,result);
}

bool FxKnownComment(FxGateway &gateway,const string comment)
{
   for(int i=0;i<gateway.Count();i++) { FxEntry e=gateway.At(i); if(FxComment(e.work)==comment) return true; }
   return false;
}

FxContext FxNativeContext(FxGateway &gateway,const FxWork &w)
{
   FxContext c;
   // The ONLY supported namespace is this synthetic Tester binding.
   c.broker="fixture"; c.server="offline"; c.login=IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   c.currency=AccountInfoString(ACCOUNT_CURRENCY); c.release="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; c.policy=c.release;
   c.symbol=w.broker_symbol; c.now_ms=(long)TimeCurrent()*1000+999; c.clock_error_ms=0;
   MqlTick tick={}; bool quote=SymbolInfoTick(c.symbol,tick); c.tick_ms=tick.time_msc; c.bid=tick.bid; c.ask=tick.ask;
   c.connected=MQLInfoInteger(MQL_TESTER) && quote && SymbolInfoInteger(c.symbol,SYMBOL_CUSTOM);
   c.session_open=false;
   MqlDateTime now; TimeToStruct(TimeCurrent(),now); datetime from,to;
   for(uint session=0;session<16 && SymbolInfoSessionTrade(c.symbol,(ENUM_DAY_OF_WEEK)now.day_of_week,session,from,to);session++)
   {
      long second=now.hour*3600+now.min*60+now.sec;
      if((long)from<=second && second<(long)to) c.session_open=true;
   }
   c.min_lot=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_MIN)*100000000);
   c.max_lot=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_MAX)*100000000);
   c.lot_step=(long)MathRound(SymbolInfoDouble(c.symbol,SYMBOL_VOLUME_STEP)*100000000);
   c.tick_size=SymbolInfoDouble(c.symbol,SYMBOL_TRADE_TICK_SIZE);
   double point=SymbolInfoDouble(c.symbol,SYMBOL_POINT);
   c.min_stop=SymbolInfoInteger(c.symbol,SYMBOL_TRADE_STOPS_LEVEL)*point;
   c.freeze_distance=SymbolInfoInteger(c.symbol,SYMBOL_TRADE_FREEZE_LEVEL)*point;
   c.owner_pause=false; c.loss_halt=false; // Full independent policy is an M2C gate; connected calls are impossible here.
   c.unknown_exposure=false; c.owned=false; c.mutation_unknown=false;
   c.position=0; c.order=0; c.position_volume=0; c.position_version=0; c.position_side="~"; c.accepted_stop=0; c.accepted_target=0;
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      bool owned=PositionGetInteger(POSITION_MAGIC)==(long)FX_MAGIC && FxKnownComment(gateway,PositionGetString(POSITION_COMMENT));
      if(!owned) c.unknown_exposure=true;
      if(PositionGetString(POSITION_SYMBOL)==c.symbol && (w.action=="ENTER" || ticket==w.position))
      {
         c.position=ticket; c.owned=owned; c.position_volume=(long)MathRound(PositionGetDouble(POSITION_VOLUME)*100000000);
         c.accepted_stop=PositionGetDouble(POSITION_SL); c.accepted_target=PositionGetDouble(POSITION_TP);
         c.position_side=PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? "BUY" : "SELL";
         for(int j=0;j<gateway.Count();j++) { FxEntry e=gateway.At(j); if(e.position==ticket && e.work.action=="ENTER") c.position_version=e.version; }
      }
   }
   for(int i=0;i<OrdersTotal();i++)
   {
      ulong ticket=OrderGetTicket(i);
      bool owned=OrderGetInteger(ORDER_MAGIC)==(long)FX_MAGIC && FxKnownComment(gateway,OrderGetString(ORDER_COMMENT));
      if(!owned) c.unknown_exposure=true;
      if(OrderGetString(ORDER_SYMBOL)==c.symbol && (w.action=="ENTER" || ticket==w.order))
      {
         c.order=ticket;
         if(w.action=="CANCEL")
         {
            c.owned=owned;
            for(int j=0;j<gateway.Count();j++) { FxEntry e=gateway.At(j); if(e.order==ticket) c.position_version=e.version; }
         }
      }
   }
   for(int i=0;i<gateway.Count();i++)
   {
      FxEntry e=gateway.At(i);
      if(e.work.id!=w.id && (e.state=="SUBMITTING" || e.state=="OUTCOME_UNKNOWN" || e.state=="ACKNOWLEDGED") &&
         ((w.position!=0 && e.work.position==w.position) || (w.order!=0 && e.work.order==w.order))) c.mutation_unknown=true;
   }
   return c;
}

string FxPrepare(const FxWork &w,const FxContext &c,const long lots,MqlTradeRequest &request)
{
   ZeroMemory(request);
   request.symbol=w.broker_symbol; request.magic=FX_MAGIC; request.comment=FxComment(w); request.deviation=5;
   request.volume=(double)lots/100000000; request.type_time=ORDER_TIME_GTC;
   long fill=SymbolInfoInteger(w.broker_symbol,SYMBOL_FILLING_MODE);
   if((fill&SYMBOL_FILLING_FOK)!=0) request.type_filling=ORDER_FILLING_FOK;
   else if((fill&SYMBOL_FILLING_IOC)!=0) request.type_filling=ORDER_FILLING_IOC;
   else return "UNSUPPORTED_FILL_MODE";
   if(w.action=="ENTER")
   {
      request.action=TRADE_ACTION_DEAL; request.type=w.side=="BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      request.price=w.side=="BUY" ? c.ask : c.bid; request.sl=(double)w.stop/100000000; request.tp=(double)w.target/100000000;
      double profit=0;
      if(!OrderCalcProfit(request.type,request.symbol,request.volume,request.price,request.sl,profit) || MathAbs(profit)>w.max_risk) return "RISK_ALLOWANCE";
   }
   else if(w.action=="CLOSE")
   {
      request.action=TRADE_ACTION_DEAL; request.position=w.position;
      request.type=c.position_side=="BUY" ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      request.price=c.position_side=="BUY" ? c.bid : c.ask;
   }
   else if(w.action=="TIGHTEN_STOP")
   {
      request.action=TRADE_ACTION_SLTP; request.position=w.position; request.sl=(double)w.stop/100000000;
      request.tp=c.accepted_target; // Tightening cannot remove or silently change the existing target.
   }
   else if(w.action=="CANCEL") { request.action=TRADE_ACTION_REMOVE; request.order=w.order; }
   else return "UNSUPPORTED_ACTION";
   MqlTradeCheckResult checked={};
   if(!OrderCheck(request,checked)) return "ORDER_CHECK_REJECTED";
   return "OK";
}

string FxDispatch(FxGateway &gateway,const string frame)
{
   if(!MQLInfoInteger(MQL_TESTER)) return "CONNECTED_EXECUTION_DISABLED";
   FxWork w; string code=FxDecode(frame,w); if(code!="OK") return code;
   FxContext context=FxNativeContext(gateway,w); int index;
   code=gateway.Admit(frame,context,index);
   if(code!="OK") return code;
   long lots; code=FxValidate(w,context,lots);
   MqlTradeRequest request={};
   if(code=="OK") code=FxPrepare(w,context,lots,request);
   if(code!="OK") { gateway.AbortBeforeCall(index,code); return code; }
   if(!gateway.MarkSubmitting(index)) return "JOURNAL_UNAVAILABLE";
   // Check again after the write/flush. A slow journal cannot extend quote age or TTL.
   context=FxNativeContext(gateway,w);
   code=FxValidate(w,context,lots);
   if(code=="OK") code=FxPrepare(w,context,lots,request);
   if(code!="OK") { gateway.AbortBeforeCall(index,code); return code; }
   MqlTradeResult result={};
   bool sent=FxTesterSend(request,result);
   bool accepted=sent && (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_DONE_PARTIAL || result.retcode==TRADE_RETCODE_PLACED);
   if(!gateway.Result(index,accepted,result.order,"RETCODE_"+IntegerToString(result.retcode))) return "JOURNAL_UNAVAILABLE";
   return accepted ? "ACKNOWLEDGED" : "OUTCOME_UNKNOWN";
}

bool FxReconcile(FxGateway &gateway)
{
   ulong cutoff=GetTickCount64()+20;
   if(!MQLInfoInteger(MQL_TESTER) || !HistorySelect(0,TimeCurrent()+60)) return false;
   // Cooperative bounds: a single terminal query cannot be preempted. Oversized
   // fixture histories fail closed, retaining dirty state and unresolved risk.
   if(gateway.Count()>1024 || HistoryOrdersTotal()>10000 || HistoryDealsTotal()>10000) return false;
   for(int n=0;n<gateway.Count();n++)
   {
      if(GetTickCount64()>=cutoff) return false;
      FxEntry e=gateway.At(n);
      if(e.state=="READY" || e.state=="REJECTED" || e.state=="CLOSED") continue;
      if(e.work.action=="TIGHTEN_STOP")
      {
         if(PositionSelectByTicket(e.work.position) && PositionGetInteger(POSITION_MAGIC)==(long)FX_MAGIC &&
            MathAbs(PositionGetDouble(POSITION_SL)-(double)e.work.stop/100000000)<0.000000005)
            if(!gateway.Reconcile(n,true,0,0,0,0,e.work.position,0,true)) return false;
         continue;
      }
      if(e.work.action=="CANCEL")
      {
         if(HistoryOrderSelect(e.work.order) && HistoryOrderGetInteger(e.work.order,ORDER_STATE)==ORDER_STATE_CANCELED)
            if(!gateway.Reconcile(n,true,0,0,0,e.work.order,0,0,true)) return false;
         if(!HistorySelect(0,TimeCurrent()+60)) return false;
         continue;
      }
      ulong order=e.order;
      if(order==0)
      {
         int matches=0;
         for(int i=0;i<HistoryOrdersTotal();i++)
         {
            if(GetTickCount64()>=cutoff) return false;
            ulong candidate=HistoryOrderGetTicket(i);
            if(HistoryOrderGetInteger(candidate,ORDER_MAGIC)==(long)FX_MAGIC && HistoryOrderGetString(candidate,ORDER_COMMENT)==FxComment(e.work) && HistoryOrderGetString(candidate,ORDER_SYMBOL)==e.work.broker_symbol)
            { order=candidate; matches++; }
         }
         if(matches!=1) continue; // Empty or ambiguous history preserves uncertainty.
      }
      long filled=0; ulong identifier=0;
      for(int i=0;i<HistoryDealsTotal();i++)
      {
         if(GetTickCount64()>=cutoff) return false;
         ulong deal=HistoryDealGetTicket(i);
         if((ulong)HistoryDealGetInteger(deal,DEAL_ORDER)==order && HistoryDealGetInteger(deal,DEAL_MAGIC)==(long)FX_MAGIC)
         {
            filled+=(long)MathRound(HistoryDealGetDouble(deal,DEAL_VOLUME)*100000000);
            identifier=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
         }
      }
      long pending=0; bool final_order=false;
      if(OrderSelect(order)) pending=(long)MathRound(OrderGetDouble(ORDER_VOLUME_CURRENT)*100000000);
      else
      {
         long state=HistoryOrderGetInteger(order,ORDER_STATE);
         final_order=state==ORDER_STATE_FILLED || state==ORDER_STATE_CANCELED || state==ORDER_STATE_REJECTED || state==ORDER_STATE_EXPIRED;
      }
      if(filled==0 && !final_order) continue;
      long open_volume=0; ulong position=0; double stop=0; bool contaminated=false;
      if(e.work.action=="ENTER")
      {
         long balance=0;
         for(int i=0;i<HistoryDealsTotal();i++)
         {
            if(GetTickCount64()>=cutoff) return false;
         ulong deal=HistoryDealGetTicket(i);
            if(identifier!=0 && (ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID)==identifier)
            {
               long volume=(long)MathRound(HistoryDealGetDouble(deal,DEAL_VOLUME)*100000000);
               long kind=HistoryDealGetInteger(deal,DEAL_ENTRY);
               if(kind==DEAL_ENTRY_IN) balance+=volume;
               else if(kind==DEAL_ENTRY_OUT || kind==DEAL_ENTRY_OUT_BY) balance-=volume;
               else contaminated=true; // Netting reversal is never silently adopted.
            }
            if(identifier!=0 && (ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID)==identifier &&
               (HistoryDealGetInteger(deal,DEAL_MAGIC)!=(long)FX_MAGIC ||
               (!FxKnownComment(gateway,HistoryDealGetString(deal,DEAL_COMMENT)) &&
                HistoryDealGetInteger(deal,DEAL_REASON)!=DEAL_REASON_SL && HistoryDealGetInteger(deal,DEAL_REASON)!=DEAL_REASON_TP))) contaminated=true;
         }
         for(int i=0;i<PositionsTotal();i++)
         {
            if(GetTickCount64()>=cutoff) return false;
            ulong ticket=PositionGetTicket(i);
            if(identifier!=0 && (ulong)PositionGetInteger(POSITION_IDENTIFIER)==identifier)
            { position=ticket; open_volume=(long)MathRound(PositionGetDouble(POSITION_VOLUME)*100000000); stop=PositionGetDouble(POSITION_SL); }
         }
         // Absence of a position alone is not positive closure evidence.
         if(balance!=open_volume || balance<0) contaminated=true;
      }
      if(!contaminated) if(!gateway.Reconcile(n,true,filled,open_volume,pending,order,position,stop,final_order)) return false;
   }
   return GetTickCount64()<cutoff;
}
#endif
