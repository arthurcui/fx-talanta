#ifndef FX_DEMO_RECONCILE
#define FX_DEMO_RECONCILE
#include "../gateway/Broker.mqh"
struct DemoOrder { ulong ticket; long magic; string symbol,comment; bool final_order,cancelled; long pending; };
struct DemoDeal { ulong ticket,order,identifier;long time_ms; long magic,volume,entry,reason; string comment; };
struct DemoPosition { ulong ticket; long volume; double stop; };
// CryptEncode does not produce a digest for a zero-length MQL5 data array.
// A flat account is a valid snapshot, distinct from an unavailable snapshot.
string DemoPositionsFingerprint(string positions){return FxHash("demo-positions/1\n"+positions);}
class DemoHistorySource
{
public:
   virtual bool Valid(){ return false; }
   virtual int OrderCount(){ return -1; }
   virtual int DealCount(){ return -1; }
   virtual bool Order(int i,DemoOrder &r){ return false; }
   virtual bool Deal(int i,DemoDeal &r){ return false; }
   virtual bool Position(ulong id,DemoPosition &r){ return false; }
   virtual bool ConfirmStop(ulong ticket,double stop,string comment,double &actual){ return false; }
};
// Cursor survives callbacks. A failed query never becomes positive closure.
// The source pins a bounded selection and invalidates on transaction/snapshot change.
class DemoReconciler
{
private:
   int current,stage,cursor,matches;
   long filled,balance;
   ulong identifier;
   DemoOrder order;
   bool contaminated,unresolved,active;
   bool confirmed[];
   string proofs[],proof;
   bool Witness(FxGateway &g,string facts){proof=FxHash(proof+facts);return g.Audit(current,"BROKER_WITNESS,"+facts);}
   void Next(){ current++; stage=0; cursor=0; matches=0; filled=0; balance=0; identifier=0; contaminated=false;proof=""; ZeroMemory(order); }
public:
   DemoReconciler(){ active=false; }
   void Begin(){ ArrayResize(confirmed,1024); ArrayInitialize(confirmed,false);ArrayResize(proofs,1024);current=-1; unresolved=false; active=true; Next(); }
   void Invalidate(){ active=false; ArrayInitialize(confirmed,false); }
   string Proof(int index){return Confirmed(index) ? proofs[index] : "";}
   bool Confirmed(int index){ return index>=0 && index<ArraySize(confirmed) && confirmed[index]; }
   string Step(FxGateway &gateway,DemoHistorySource &source,int budget=128)
   {
      if(!active || budget<1 || budget>128 || !source.Valid()) { active=false; return "UNRESOLVED"; }
      int orders=source.OrderCount(),deals=source.DealCount();
      if(orders<0 || deals<0 || orders>10000 || deals>10000 || gateway.Count()>1024) { active=false; return "UNRESOLVED"; }
      int consumed=0;
      while(current<gateway.Count() && consumed<budget)
      {
         FxEntry e=gateway.At(current);
         if(e.state=="READY" || e.state=="REJECTED") { Next(); consumed++; continue; }
         if(e.work.action=="TIGHTEN_STOP")
         {
            string owner="";
            for(int j=0;j<gateway.Count();j++){ FxEntry old=gateway.At(j); if(old.work.action=="ENTER" && old.position==e.work.position) owner=FxComment(old.work); }
            double actual=0;
            if(owner=="" || !source.ConfirmStop(e.work.position,(double)e.work.stop/1e8,owner,actual) || !source.Valid() ||
               !Witness(gateway,"STOP,"+IntegerToString((long)e.work.position)+","+FxDecimal(actual)) ||
               !gateway.Reconcile(current,true,0,0,0,0,e.work.position,actual,true)) unresolved=true;
            else {confirmed[current]=true;proofs[current]=FxHash(FxScope(e.work)+e.work.digest+proof);}
            Next(); consumed++; continue;
         }
         if(stage==0)
         {
            if(cursor<orders)
            {
               DemoOrder row; if(!source.Order(cursor++,row)) { active=false; return "UNRESOLVED"; } consumed++;
               bool target=e.work.action=="CANCEL" ? row.ticket==e.work.order :
                  (e.order!=0 ? row.ticket==e.order : row.comment==FxComment(e.work));
               if(target && row.magic==(long)FX_MAGIC && row.symbol==e.work.broker_symbol && FxKnownComment(gateway,row.comment))
               {
                  order=row; matches++;
                  if(!Witness(gateway,"ORDER,"+IntegerToString((long)row.ticket)+","+IntegerToString(row.magic)+","+ShHex(row.symbol)+","+ShHex(row.comment)+","+
                     IntegerToString(row.pending)+","+(row.final_order ? "1" : "0")+","+(row.cancelled ? "1" : "0"))) {Invalidate();return "UNRESOLVED";}
               }
               continue;
            }
            if(matches!=1) { unresolved=true; Next(); continue; }
            stage=1; cursor=0;
         }
         if(stage==1)
         {
            if(cursor<deals)
            {
               DemoDeal row; if(!source.Deal(cursor++,row)) { active=false; return "UNRESOLVED"; } consumed++;
               if(row.order==order.ticket)
               {
                  if(row.magic!=(long)FX_MAGIC || row.volume<0 || (identifier!=0 && identifier!=row.identifier)) contaminated=true;
                  filled+=row.volume; identifier=row.identifier;
               }
               continue;
            }
            stage=2; cursor=0;
         }
         if(stage==2)
         {
            if(cursor<deals)
            {
               DemoDeal row; if(!source.Deal(cursor++,row)) { active=false; return "UNRESOLVED"; } consumed++;
               if(identifier!=0 && row.identifier==identifier)
               {
                  if(!Witness(gateway,"DEAL,"+IntegerToString((long)row.ticket)+","+IntegerToString((long)row.order)+","+IntegerToString((long)row.identifier)+","+
                     IntegerToString(row.time_ms)+","+IntegerToString(row.magic)+","+IntegerToString(row.volume)+","+IntegerToString(row.entry)+","+
                     IntegerToString(row.reason)+","+ShHex(row.comment))) {Invalidate();return "UNRESOLVED";}
                  if(row.entry==DEAL_ENTRY_IN) balance+=row.volume;
                  else if(row.entry==DEAL_ENTRY_OUT || row.entry==DEAL_ENTRY_OUT_BY) balance-=row.volume;
                  else contaminated=true;
                  if(row.magic!=(long)FX_MAGIC || (!FxKnownComment(gateway,row.comment) && row.reason!=DEAL_REASON_SL && row.reason!=DEAL_REASON_TP)) contaminated=true;
               }
               continue;
            }
            stage=3;
         }
         DemoPosition position; ZeroMemory(position);
         if(!source.Valid() || !source.Position(identifier,position)) { active=false; return "UNRESOLVED"; }
         if(!Witness(gateway,"POSITION,"+IntegerToString((long)position.ticket)+","+IntegerToString(position.volume)+","+FxDecimal(position.stop))) {Invalidate();return "UNRESOLVED";}
         if(e.work.action=="CANCEL")
         {
            // A final non-cancelled order must not be mistaken for cancellation.
            if(!order.cancelled || !gateway.Reconcile(current,true,0,0,0,order.ticket,0,0,true)) unresolved=true;
            else {confirmed[current]=true;proofs[current]=FxHash(FxScope(e.work)+e.work.digest+proof);}
         }
         else if(contaminated || balance<0 || balance!=position.volume ||
                 !gateway.Reconcile(current,true,filled,position.volume,order.pending,order.ticket,
                                    position.ticket,position.stop,order.final_order)) unresolved=true;
         else { confirmed[current]=true; proofs[current]=FxHash(FxScope(e.work)+e.work.digest+proof); }
         Next(); consumed++;
      }
      if(current<gateway.Count()) return "INCOMPLETE";
      active=false; return unresolved || gateway.Uncertain() ? "UNRESOLVED" : "RECONCILED";
   }
};
class DemoNativeHistory : public DemoHistorySource
{
private:
   bool valid;
   int orders,deals;
   ulong pending_tickets[];
   string login,server,positions_hash;
   string PositionsHash()
   {
      if(PositionsTotal()>1024 || OrdersTotal()>1024) return "";
      string text="";
      for(int i=0;i<PositionsTotal();i++) { ulong t=PositionGetTicket(i); if(t==0) return "";
         text+=IntegerToString((long)t)+":"+DoubleToString(PositionGetDouble(POSITION_VOLUME),8)+":"+
         DoubleToString(PositionGetDouble(POSITION_SL),8)+":"+DoubleToString(PositionGetDouble(POSITION_TP),8)+";"; }
      for(int i=0;i<OrdersTotal();i++){ ulong t=OrderGetTicket(i); if(t==0) return "";
         text+=IntegerToString((long)t)+":"+DoubleToString(OrderGetDouble(ORDER_VOLUME_CURRENT),8)+";"; }
      return DemoPositionsFingerprint(text);
   }
public:
   DemoNativeHistory(){ valid=false; }
   void Invalidate(){ valid=false; }
   bool Begin(string expected_login,string expected_server,datetime from,datetime until)
   {
      login=expected_login; server=expected_server; valid=false;
      if(from<0 || until<from || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO ||
         IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))!=login || AccountInfoString(ACCOUNT_SERVER)!=server || !HistorySelect(from,until)) return false;
      ArrayResize(pending_tickets,OrdersTotal());
      for(int i=0;i<OrdersTotal();i++) { pending_tickets[i]=OrderGetTicket(i); if(pending_tickets[i]==0) return false; }
      orders=HistoryOrdersTotal(); deals=HistoryDealsTotal(); positions_hash=PositionsHash();
      valid=orders<=10000 && deals<=10000 && positions_hash!=""; return valid;
   }
   virtual bool Valid()
   {
      valid=valid && AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO &&
         IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))==login && AccountInfoString(ACCOUNT_SERVER)==server &&
         HistoryOrdersTotal()==orders && HistoryDealsTotal()==deals && PositionsHash()==positions_hash;
      return valid;
   }
   virtual int OrderCount(){ return orders+ArraySize(pending_tickets); }
   virtual int DealCount(){ return deals; }
   virtual bool Order(int i,DemoOrder &r)
   {
      if(i>=orders)
      {
         int j=i-orders; if(j>=ArraySize(pending_tickets) || !OrderSelect(pending_tickets[j])) return false;
         r.ticket=pending_tickets[j]; r.magic=OrderGetInteger(ORDER_MAGIC); r.symbol=OrderGetString(ORDER_SYMBOL); r.comment=OrderGetString(ORDER_COMMENT);
         r.final_order=false; r.cancelled=false; r.pending=(long)MathRound(OrderGetDouble(ORDER_VOLUME_CURRENT)*1e8); return true;
      }
      ulong t=HistoryOrderGetTicket(i); if(t==0) return false;
      r.ticket=t; r.magic=HistoryOrderGetInteger(t,ORDER_MAGIC); r.symbol=HistoryOrderGetString(t,ORDER_SYMBOL);
      r.comment=HistoryOrderGetString(t,ORDER_COMMENT);
      long state=HistoryOrderGetInteger(t,ORDER_STATE);
      r.final_order=state==ORDER_STATE_FILLED || state==ORDER_STATE_CANCELED || state==ORDER_STATE_REJECTED || state==ORDER_STATE_EXPIRED;
      r.cancelled=state==ORDER_STATE_CANCELED;
      r.pending=OrderSelect(t) ? (long)MathRound(OrderGetDouble(ORDER_VOLUME_CURRENT)*1e8) : 0; return true;
   }
   virtual bool Deal(int i,DemoDeal &r)
   {
      ulong t=HistoryDealGetTicket(i); if(t==0) return false;
      r.ticket=t;r.time_ms=HistoryDealGetInteger(t,DEAL_TIME_MSC);
      r.order=(ulong)HistoryDealGetInteger(t,DEAL_ORDER); r.identifier=(ulong)HistoryDealGetInteger(t,DEAL_POSITION_ID);
      r.magic=HistoryDealGetInteger(t,DEAL_MAGIC); r.volume=(long)MathRound(HistoryDealGetDouble(t,DEAL_VOLUME)*1e8);
      r.entry=HistoryDealGetInteger(t,DEAL_ENTRY); r.reason=HistoryDealGetInteger(t,DEAL_REASON); r.comment=HistoryDealGetString(t,DEAL_COMMENT); return true;
   }
   virtual bool ConfirmStop(ulong ticket,double stop,string comment,double &actual)
   {
      if(!PositionSelectByTicket(ticket) || PositionGetInteger(POSITION_MAGIC)!=(long)FX_MAGIC ||
         PositionGetString(POSITION_COMMENT)!=comment) return false;
      actual=PositionGetDouble(POSITION_SL);
      return actual>0 && (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? actual>=stop : actual<=stop);
   }
   virtual bool Position(ulong id,DemoPosition &r)
   {
      ZeroMemory(r);
      for(int i=0;i<PositionsTotal();i++){ ulong t=PositionGetTicket(i); if(t==0) return false;
         if(id!=0 && (ulong)PositionGetInteger(POSITION_IDENTIFIER)==id) { r.ticket=t; r.volume=(long)MathRound(PositionGetDouble(POSITION_VOLUME)*1e8); r.stop=PositionGetDouble(POSITION_SL); } }
      return true;
   }
};
#endif
