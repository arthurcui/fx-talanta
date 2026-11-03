#property strict
#property tester_file "m2b-requests.tsv"
#include "NativeTests.mqh"
#include "Broker.mqh"
#include "Telemetry.mqh"

FxGateway fx_gateway;
string fx_frames[],fx_path;
int fx_stage=0,fx_ticks=0,fx_callbacks=0;
bool fx_done=false;

string FxTestFrame(const string source,const string action,const int sequence,const ulong position,const long version)
{
   string f[]; StringSplit(source,'\t',f);
   f[2]=StringFormat("00000000-0000-0000-0000-%012d",sequence+20);
   f[14]=StringFormat("00000000-0000-0000-0000-%012d",sequence+120);
   f[8]=IntegerToString(sequence); f[16]=action;
   if(action!="ENTER")
   {
      f[21]="0"; f[25]=IntegerToString((long)position); f[27]=IntegerToString(version);
      f[23]=action=="TIGHTEN_STOP" ? "1.099" : "~"; f[24]="~";
   }
   f[1]=FxHash(FxCanonical(f));
   string frame=f[0]; for(int i=1;i<ArraySize(f);i++) frame+="\t"+f[i];
   return frame;
}

int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER) || AccountInfoInteger(ACCOUNT_LOGIN)!=42 || !SymbolInfoInteger(_Symbol,SYMBOL_CUSTOM)) return INIT_FAILED;
   if(!FxRunNativeTests()) return INIT_FAILED;
   int file=FileOpen("m2b-requests.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) return INIT_FAILED;
   ArrayResize(fx_frames,8); for(int i=0;i<8;i++) fx_frames[i]=FileReadString(file); FileClose(file);
   fx_path="fx-m2b-tests/native-orders-"+IntegerToString((long)GetTickCount64())+".journal";
   return fx_gateway.Open(fx_path) ? INIT_SUCCEEDED : INIT_FAILED;
}

void OnTradeTransaction(const MqlTradeTransaction &transaction,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   fx_callbacks++; // Only a notification count; all state comes from FxReconcile queries.
}

void OnTick()
{
   if(fx_done) return;
   fx_ticks++;
   if(fx_ticks>100) { FxCheck("native_bounded_completion",false); fx_done=true; TesterStop(); return; }
   FxReconcile(fx_gateway);
   if(fx_stage==0)
   {
      FxCheck("native_buy_ack",FxDispatch(fx_gateway,fx_frames[0])=="ACKNOWLEDGED");
      fx_stage=1; return;
   }
   FxEntry original=fx_gateway.At(0);
   if(fx_stage==1 && original.state=="PROTECTED")
   {
      FxCheck("native_positive_fill",original.filled==9000000 && original.open_volume==9000000 && original.position!=0);
      FxCheck("native_initial_sl",MathAbs(original.accepted_stop-1.098)<0.000000005);
      int calls=fx_send_calls;
      FxCheck("native_duplicate_no_send",FxDispatch(fx_gateway,fx_frames[0])=="REPLAY" && fx_send_calls==calls);
      FxContext telemetry=FxNativeContext(fx_gateway,original.work);
      FxCheck("native_telemetry_written",FxTelemetry(telemetry,"EURUSD"));
      string tighten=FxTestFrame(fx_frames[0],"TIGHTEN_STOP",2,original.position,original.version);
      FxCheck("native_tighten_ack",FxDispatch(fx_gateway,tighten)=="ACKNOWLEDGED");
      fx_stage=2; return;
   }
   if(fx_stage==2 && fx_gateway.Count()>=2)
   {
      FxEntry tighten=fx_gateway.At(1);
      if(tighten.state!="CLOSED") return;
      FxCheck("native_tighter_stop",MathAbs(original.accepted_stop-1.099)<0.000000005);
      FxCheck("native_tp_preserved",PositionSelectByTicket(original.position) && MathAbs(PositionGetDouble(POSITION_TP)-1.1046)<0.000000005);
      string close=FxTestFrame(fx_frames[0],"CLOSE",3,original.position,original.version);
      FxCheck("native_close_ack",FxDispatch(fx_gateway,close)=="ACKNOWLEDGED");
      fx_stage=3; return;
   }
   if(fx_stage==3 && original.state=="CLOSED" && PositionsTotal()==0)
   {
      FxCheck("native_buy_flat",true);
      fx_gateway.Close(); FxCheck("native_restart_after_close",fx_gateway.Open(fx_path));
      int calls=fx_send_calls;
      FxCheck("native_restart_no_resend",FxDispatch(fx_gateway,fx_frames[0])=="REPLAY" && fx_send_calls==calls);
      string sell=FxTestFrame(fx_frames[6],"ENTER",4,0,0);
      FxCheck("native_sell_ack",FxDispatch(fx_gateway,sell)=="ACKNOWLEDGED");
      fx_stage=4; return;
   }
   if(fx_stage==4 && fx_gateway.Count()>=4)
   {
      FxEntry sell=fx_gateway.At(3);
      if(sell.state!="PROTECTED") return;
      FxCheck("native_sell_protected",sell.open_volume==9000000 && MathAbs(sell.accepted_stop-1.102)<0.000000005);
      string close=FxTestFrame(fx_frames[6],"CLOSE",5,sell.position,sell.version);
      FxCheck("native_sell_close_ack",FxDispatch(fx_gateway,close)=="ACKNOWLEDGED");
      fx_stage=5; return;
   }
   if(fx_stage==5 && PositionsTotal()==0)
   {
      FxEntry close=fx_gateway.At(4);
      if(close.state!="CLOSED") return;
      // Seed a resting synthetic order only in this harness to exercise CANCEL.
      // The fixed gateway itself exposes market entry, never arbitrary order placement.
      string pending=FxTestFrame(fx_frames[0],"ENTER",6,0,0);
      FxWork work; FxDecode(pending,work);
      FxContext context=FxNativeContext(fx_gateway,work); int index;
      FxCheck("native_pending_admission",fx_gateway.Admit(pending,context,index)=="OK");
      MqlTradeRequest request={}; MqlTradeResult result={};
      request.action=TRADE_ACTION_PENDING; request.type=ORDER_TYPE_BUY_LIMIT;
      request.symbol=_Symbol; request.volume=0.09; request.price=1.099;
      request.sl=1.098; request.tp=1.1046; request.magic=FX_MAGIC; request.comment=FxComment(work);
      request.type_filling=ORDER_FILLING_RETURN; request.type_time=ORDER_TIME_GTC;
      bool prepared=fx_gateway.MarkSubmitting(index);
      bool accepted=prepared && FxTesterSend(request,result) && (result.retcode==TRADE_RETCODE_DONE || result.retcode==TRADE_RETCODE_PLACED);
      FxCheck("native_pending_seed",accepted && fx_gateway.Result(index,true,result.order,"TESTER_PENDING_SEED"));
      fx_stage=6; return;
   }
   if(fx_stage==6 && fx_gateway.Count()>=6)
   {
      FxEntry pending=fx_gateway.At(5);
      if(pending.order==0 || !OrderSelect(pending.order)) return;
      string cancel=FxTestFrame(fx_frames[0],"CANCEL",7,0,pending.version);
      string f[]; StringSplit(cancel,'\t',f); f[25]="~"; f[26]=IntegerToString((long)pending.order);
      f[1]=FxHash(FxCanonical(f)); cancel=f[0]; for(int i=1;i<ArraySize(f);i++) cancel+="\t"+f[i];
      FxCheck("native_cancel_ack",FxDispatch(fx_gateway,cancel)=="ACKNOWLEDGED");
      fx_stage=7; return;
   }
   if(fx_stage==7 && fx_gateway.Count()>=7)
   {
      FxEntry pending=fx_gateway.At(5),cancel=fx_gateway.At(6);
      if(pending.state!="CLOSED" || cancel.state!="CLOSED") return;
      FxCheck("native_cancel_positive_history",pending.remaining==0 && pending.filled==0);
      FxCheck("native_no_reversal_or_orders",OrdersTotal()==0);
      FxCheck("native_callback_reconciliation",fx_callbacks>0);
      FxCheck("native_exact_send_count",fx_send_calls==7);
      fx_done=true;
      Print("FX_M2B_ORDER_RESULT checks=",fx_checks," failures=",fx_failures," sends=",fx_send_calls," callbacks=",fx_callbacks," final_positions=",PositionsTotal()," final_orders=",OrdersTotal());
      TesterStop();
   }
}
double OnTester(){ if(!fx_done) FxCheck("native_completed",false); return fx_failures==0 ? fx_checks : -fx_failures; }
void OnDeinit(const int reason){ fx_gateway.Close(); }
