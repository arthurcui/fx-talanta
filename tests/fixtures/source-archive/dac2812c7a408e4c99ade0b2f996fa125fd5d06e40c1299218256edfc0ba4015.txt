#property strict
#property tester_file "demo-cases.tsv"
#property tester_file "demo-binding.tsv"
#include "Kernel.mqh"
#include "NativePort.mqh"
#include "Reconcile.mqh"
int checks=INVALID_HANDLE;
void Check(string name,bool ok){ FileWriteString(checks,name+"\t"+(ok ? "1" : "0")+"\r\n"); }
class FixturePort : public DemoPort
{
public:
   int sends,contexts; bool enabled,stale,uncertain,own;
   FixturePort(){ sends=0; contexts=0; enabled=true; stale=false; uncertain=false; own=true; }
   virtual bool Enabled(){ return MQLInfoInteger(MQL_TESTER) && enabled; }
   virtual bool Context(const FxWork &w,FxContext &c)
   {
      if(!MQLInfoInteger(MQL_TESTER)) return false;
      contexts++; ZeroMemory(c); c.broker=w.broker;c.server=w.server;c.login=w.login;c.currency=w.currency;c.release=w.release;c.policy=w.policy;c.symbol=w.broker_symbol;
      c.now_ms=1767614400020+(stale && contexts>1 ? 2000 : 0);c.tick_ms=1767614399500;c.clock_error_ms=10;
      c.connected=true;c.session_open=true;c.bid=1.1;c.ask=1.1002;c.tick_size=0.00001;c.min_stop=0.0001;
      c.min_lot=1000000;c.max_lot=10000000000;c.lot_step=1000000;
      c.owned=own;c.position_side="BUY";c.position_version=3;c.position_volume=9000000;c.accepted_stop=1.098;
      if(w.action!="ENTER"){ c.position=w.position;c.order=w.order; }
      return true;
   }
   virtual bool RefreshRisk(const FxWork &w,string &k[],string &v[]){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual string Prepare(const FxWork &w,const FxContext &c,long lots,MqlTradeRequest &r){ r.volume=(double)lots/1e8; return "OK"; }
   virtual bool Immediate(const FxWork &w,string risk,const FxContext &c){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual bool BeforeMutation(const FxWork &w){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual bool Send(MqlTradeRequest &r,MqlTradeResult &s)
   { if(!Enabled()) return false; sends++; s.order=500;s.retcode=TRADE_RETCODE_DONE;return !uncertain; }
};
class FixtureHistory : public DemoHistorySource
{
public:
   string comment; bool valid,final_order,contaminated; long volume,pending;
   FixtureHistory(){ valid=true;final_order=false;contaminated=false;volume=4000000;pending=5000000; }
   virtual bool Valid(){ return MQLInfoInteger(MQL_TESTER) && valid; }
   virtual int OrderCount(){ return 40; }
   virtual int DealCount(){ return 1; }
   virtual bool Order(int i,DemoOrder &r)
   { ZeroMemory(r);r.ticket=i==39 ? 500 : 1000+i;r.magic=(long)FX_MAGIC;r.symbol="EURUSD";r.comment=comment;r.final_order=final_order;r.pending=pending;return true; }
   virtual bool Deal(int i,DemoDeal &r)
   { ZeroMemory(r);r.order=500;r.identifier=700;r.magic=contaminated ? 0 : (long)FX_MAGIC;r.volume=volume;r.entry=DEAL_ENTRY_IN;r.comment=comment;return true; }
   virtual bool Position(ulong id,DemoPosition &r){ r.ticket=700;r.volume=volume;r.stop=1.098;return true; }
};
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   int case_file=FileOpen("demo-cases.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int binding=FileOpen("demo-binding.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   checks=FileOpen("demo-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(case_file==INVALID_HANDLE || binding==INVALID_HANDLE || checks==INVALID_HANDLE) return INIT_FAILED;
   string b[];StringSplit(FileReadString(binding),'\t',b);FileClose(binding);
   string frames[],risks[],packets[]; ArrayResize(frames,5);ArrayResize(risks,5);ArrayResize(packets,5);
   for(int i=0;i<5;i++){ string f[];if(StringSplit(FileReadString(case_file),'\t',f)!=4 || !ShUnhex(f[1],frames[i]) || !ShUnhex(f[2],risks[i]) || !ShUnhex(f[3],packets[i])) return INIT_FAILED; }
   FileClose(case_file);
   SLoss ledger;ledger.day=20260105;ledger.start=10000;ledger.flows=0;ledger.units=10000;ledger.high=1;ledger.loss=0;ledger.paused=false;ledger.hard=false;ledger.owner=false;
   DemoNativePort real_port; Check("compiled-native-submission-disabled",!real_port.Enabled());
   for(int i=0;i<4;i++)
   {
      DemoRuntime runtime;FixturePort fixture;
      bool opened=runtime.Open("action-"+IntegerToString(i),b[0],true,"");
      string outcome=runtime.Dispatch(frames[i],risks[i],ledger,fixture);
      FxWork w;FxDecode(frames[i],w,true);
      Check("dispatch-"+w.action,opened && outcome=="ACKNOWLEDGED" && fixture.sends==1);
      Check("replay-"+w.action,runtime.Dispatch(frames[i],risks[i],ledger,fixture)=="REPLAY" && fixture.sends==1);
      runtime.Close();
   }
   DemoRuntime runtime;FixturePort fake;
   Check("bootstrap",runtime.Open("main.execution",b[0],true,""));
   fake.enabled=false;
   Check("disabled-before-submitting",runtime.Dispatch(frames[0],risks[0],ledger,fake)=="TRADING_DISABLED" && fake.sends==0 && runtime.State().At(0).state=="REJECTED");
   runtime.Close();string tip=DgFileTip("main.execution");
   Check("checkpoint-required",!runtime.Open("main.execution",b[0],false,""));
   Check("checkpoint-restores-replay",runtime.Open("main.execution",b[0],false,tip) && runtime.Dispatch(frames[0],risks[0],ledger,fake)=="REPLAY");runtime.Close();
   FixturePort late;late.stale=true;runtime.Open("late.execution",b[0],true,"");
   Check("post-flush-stale-block",runtime.Dispatch(frames[0],risks[0],ledger,late)=="STALE_QUOTE" && late.sends==0);runtime.Close();
   FixturePort refused; refused.stale=true;refused.contexts=1;runtime.Open("sequence.execution",b[0],true,"");
   Check("refusal-recorded",runtime.Dispatch(frames[0],risks[0],ledger,refused)=="STALE_QUOTE" && runtime.State().Count()==1);
   refused.stale=false;Check("next-sequence-after-refusal",runtime.Dispatch(frames[4],risks[4],ledger,refused)=="ACKNOWLEDGED");runtime.Close();
   FixturePort close_port;runtime.Open("close-partial.execution",b[0],true,"");runtime.Dispatch(frames[1],risks[1],ledger,close_port);
   Check("partial-close-retains-larger-position",runtime.State().Reconcile(0,true,1000000,8000000,0,500,700,1.098,true));runtime.Close();
   FixturePort lost;lost.uncertain=true;runtime.Open("lost.execution",b[0],true,"");
   Check("uncertain-no-resend",runtime.Dispatch(frames[0],risks[0],ledger,lost)=="OUTCOME_UNKNOWN" && runtime.Dispatch(frames[0],risks[0],ledger,lost)=="REPLAY" && lost.sends==1);runtime.Close();
   FixturePort owner;owner.own=false;runtime.Open("owner.execution",b[0],true,"");
   Check("foreign-position-refused",runtime.Dispatch(frames[1],risks[1],ledger,owner)=="NOT_OWNED" && owner.sends==0);runtime.Close();
   FixturePort broker;runtime.Open("history.execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,broker);
   FixtureHistory history;FxWork first;FxDecode(frames[0],first,true);history.comment=FxComment(first);
   DemoReconciler cursor;cursor.Begin();string result="INCOMPLETE";int loops=0;
   while(result=="INCOMPLETE" && loops++<50) result=cursor.Step(runtime.State(),history,2);
   FxEntry e=runtime.State().At(0);
   Check("cursor-progress-partial-fill",loops>10 && loops<50 && result=="UNRESOLVED" && e.filled==4000000 && e.remaining==5000000 && e.state=="PROTECTED");
   history.volume=9000000;history.pending=0;history.final_order=true;cursor.Begin();result="INCOMPLETE";
   while(result=="INCOMPLETE") result=cursor.Step(runtime.State(),history,2);
   Check("positive-final-reconciliation",result=="RECONCILED" && runtime.State().At(0).open_volume==9000000);
   history.contaminated=true;cursor.Begin();result="INCOMPLETE";while(result=="INCOMPLETE") result=cursor.Step(runtime.State(),history,2);
   Check("manual-contamination-refused",result=="UNRESOLVED");runtime.Close();
   DemoProtectionStore protect;string boot=b[1];
   Check("protection-before-call-durable",protect.Open("protect",b[0],true,"") && protect.Begin(first.id,100,boot,100,200));
   Check("disabled-repair-not-sent",protect.Step(first.id,150,boot,true,true,false,false,false,false,false)=="ATTACH_STOP_ONCE");
   Check("deadline-sticky-halt",protect.Step(first.id,310,boot,true,true,false,false,false,false,false)=="CONTROLLED_EXIT_ONCE" && protect.HardHalt());
   protect.Close();string ptip=DgFileTip("protect");
   Check("protection-restart-retains-halt",protect.Open("protect",b[0],false,ptip) && protect.HardHalt());protect.Close();
   DemoKernel kernel;FixturePort disabled;disabled.enabled=false;
   Check("transport-full-request",kernel.Open("kernel",b[0],b[1],b[2],b[3],b[4],true,"","","") && kernel.Receive(packets[0],1767614400020,10,disabled));
   string pending=kernel.Pending();int receipt_file=FileOpen("demo-receipt.txt",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);FileWriteString(receipt_file,pending+"\r\n");FileClose(receipt_file);
   Check("separate-native-outcome",StringFind(pending,"\tTRADING_DISABLED\tREJECTED\t0")>0 && disabled.sends==0);
   kernel.Close();
   Check("paired-restart-receipt",kernel.Open("kernel",b[0],b[1],b[2],b[3],b[4],false,DgFileTip("kernel.risk"),DgFileTip("kernel.execution"),DgFileTip("kernel.outcomes")) && kernel.Pending()==pending);
   Check("ack-persisted",kernel.Ack(FxHash(pending)) && kernel.Pending()=="");kernel.Close();
   FileClose(checks);return INIT_SUCCEEDED;
}
void OnTick(){ TesterStop(); }
