#property strict
#property tester_file "demo-cases.tsv"
#property tester_file "demo-binding.tsv"
#include "Kernel.mqh"
#include "NativePort.mqh"
#include "Reconcile.mqh"
#include "Drain.mqh"
#include "ProtectiveDispatch.mqh"
int checks=INVALID_HANDLE;
void Check(string name,bool ok){ FileWriteString(checks,name+"\t"+(ok ? "1" : "0")+"\r\n"); }
class FixturePort : public DemoPort
{
public:
   int sends,contexts;uint code;long expected_version;double current_stop; bool enabled,stale,uncertain,own;
   FixturePort(){ sends=0;contexts=0;code=TRADE_RETCODE_DONE;expected_version=3;current_stop=1.098;enabled=true; stale=false; uncertain=false; own=true; }
   virtual bool Enabled(){ return MQLInfoInteger(MQL_TESTER) && enabled; }
   virtual bool Context(const FxWork &w,FxContext &c)
   {
      if(!MQLInfoInteger(MQL_TESTER)) return false;
      contexts++; ZeroMemory(c); c.broker=w.broker;c.server=w.server;c.login=w.login;c.currency=w.currency;c.release=w.release;c.policy=w.policy;c.symbol=w.broker_symbol;
      c.now_ms=1767614400020+(stale && contexts>1 ? 2000 : 0);c.tick_ms=1767614399500;c.clock_error_ms=10;
      c.connected=true;c.session_open=true;c.bid=1.1;c.ask=1.1002;c.tick_size=0.00001;c.min_stop=0.0001;
      c.min_lot=1000000;c.max_lot=10000000000;c.lot_step=1000000;
      c.owned=own;c.position_side="BUY";c.position_version=expected_version;c.position_volume=9000000;c.accepted_stop=current_stop;
      if(w.action!="ENTER"){ c.position=w.position;c.order=w.order; }
      return true;
   }
   virtual bool RefreshRisk(const FxWork &w,string &k[],string &v[]){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual string Prepare(const FxWork &w,const FxContext &c,long lots,MqlTradeRequest &r){ r.volume=(double)lots/1e8; return "OK"; }
   virtual bool Immediate(const FxWork &w,string risk,const FxContext &c){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual bool BeforeMutation(const FxWork &w){ return MQLInfoInteger(MQL_TESTER)!=0; }
   virtual bool Send(MqlTradeRequest &r,MqlTradeResult &s)
   { if(!Enabled()) return false; sends++; s.order=500;s.retcode=code;return !uncertain; }
};
class LifecyclePort : public FixturePort
{
public:
   DemoProtectionStore *protection;string boot,armed;bool refuse_final;
   LifecyclePort(){protection=NULL;refuse_final=false;}
   virtual bool Context(const FxWork &w,FxContext &c)
   {if(!FixturePort::Context(w,c))return false;c.unknown_exposure=protection.Unresolved(armed);return true;}
   virtual bool BeforeMutation(const FxWork &w)
   {bool ok=protection.Begin(w.id,100,boot,100,200);if(ok)armed=w.id;return ok;}
   virtual bool Immediate(const FxWork &w,string risk,const FxContext &c){return !refuse_final;}
   virtual bool NoMutation(const FxWork &w){armed="";return protection.NoCall(w.id);}
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
class ClosedHistory : public FixtureHistory
{
public:
   ClosedHistory(){volume=9000000;pending=0;final_order=true;}
   virtual int DealCount(){return 2;}
   virtual bool Deal(int i,DemoDeal &r)
   {FixtureHistory::Deal(i,r);r.ticket=100+i;r.order=i==0 ? 500 : 600;r.entry=i==0 ? DEAL_ENTRY_IN : DEAL_ENTRY_OUT;return true;}
   virtual bool Position(ulong id,DemoPosition &r){ZeroMemory(r);return true;}
};
class ManagementPort : public FixturePort
{
public:
   virtual bool Send(MqlTradeRequest &r,MqlTradeResult &s)
   {bool ok=FixturePort::Send(r,s);if(sends>1)s.order=600;return ok;}
};
class ManagementHistory : public DemoHistorySource
{
public:
   string root_comment,child_comment,action;bool positive;
   ManagementHistory(){positive=true;}
   virtual bool Valid(){return MQLInfoInteger(MQL_TESTER) && positive;}
   virtual int OrderCount(){return 2;}
   virtual int DealCount(){return action=="CLOSE" ? 2 : 0;}
   virtual bool Order(int i,DemoOrder &r)
   {ZeroMemory(r);r.ticket=i==0 ? 500 : 600;r.magic=(long)FX_MAGIC;r.symbol="EURUSD";r.comment=i==0 ? root_comment : child_comment;r.final_order=true;r.cancelled=action=="CANCEL" && i==0;return true;}
   virtual bool Deal(int i,DemoDeal &r)
   {ZeroMemory(r);r.ticket=100+i;r.order=i==0 ? 500 : 600;r.identifier=700;r.magic=(long)FX_MAGIC;r.volume=i==0 ? 9000000 : 4000000;r.entry=i==0 ? DEAL_ENTRY_IN : DEAL_ENTRY_OUT;r.comment=i==0 ? root_comment : child_comment;return true;}
   virtual bool Position(ulong id,DemoPosition &r){ZeroMemory(r);if(action=="CLOSE"){r.ticket=700;r.volume=5000000;r.stop=1.098;}return true;}
   virtual bool ConfirmStop(ulong ticket,double stop,string comment,double &actual)
   {actual=1.099;return positive && ticket==700 && comment==root_comment && actual>=stop;}
};
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   int case_file=FileOpen("demo-cases.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int binding=FileOpen("demo-binding.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   checks=FileOpen("demo-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(case_file==INVALID_HANDLE || binding==INVALID_HANDLE || checks==INVALID_HANDLE) return INIT_FAILED;
   string b[];StringSplit(FileReadString(binding),'\t',b);FileClose(binding);
   string frames[],risks[],packets[]; ArrayResize(frames,8);ArrayResize(risks,8);ArrayResize(packets,8);
   for(int i=0;i<8;i++){ string f[];if(StringSplit(FileReadString(case_file),'\t',f)!=4 || !ShUnhex(f[1],frames[i]) || !ShUnhex(f[2],risks[i]) || !ShUnhex(f[3],packets[i])) return INIT_FAILED; }
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
   Check("paired-restart-receipt",kernel.Open("kernel",b[0],b[1],b[2],b[3],b[4],false,DgFileTip("kernel.risk"),DgFileTip("kernel.execution"),DgFileTip("kernel.outcomes"),DgFileTip("kernel.states")) && kernel.Pending()==pending);
   Check("ack-persisted",kernel.Ack(FxHash(pending)) && kernel.Pending()=="");kernel.Close();
   // Fixed local protective dispatcher, no network/broker mutation port.
   FixturePort repairs;runtime.Open("repair.execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,repairs);
   runtime.State().Reconcile(0,true,9000000,9000000,0,500,700,0,true);
   repairs.expected_version=runtime.State().At(0).version;repairs.current_stop=0;repairs.code=TRADE_RETCODE_INVALID_STOPS;
   DemoProtectionStore repairs_store;repairs_store.Open("repairs.protection",b[0],true,"");repairs_store.Begin(first.id,100,boot,100,200);
   bool attempted=false;
   string repair_result=DemoProtect(runtime.State(),0,repairs_store,repairs,150,boot,true,true,attempted);
   Check("stop-rejection-durable",repair_result=="PROTECTION_REJECTED" && attempted && repairs.sends==2);
   repairs.code=TRADE_RETCODE_DONE;
   Check("rejected-stop-controlled-exit",DemoProtect(runtime.State(),0,repairs_store,repairs,160,boot,true,true,attempted)=="PROTECTION_ACKNOWLEDGED" && attempted && repairs.sends==3);
   Check("exit-ack-not-fill-no-resend",DemoProtect(runtime.State(),0,repairs_store,repairs,170,boot,true,false,attempted)=="ALERT_UNRESOLVED_NO_MUTATION" && !attempted && repairs.sends==3);
   repairs_store.Close();
   Check("protection-attempt-restart",repairs_store.Open("repairs.protection",b[0],false,DgFileTip("repairs.protection")) &&
      DemoProtect(runtime.State(),0,repairs_store,repairs,180,boot,true,false,attempted)=="RECONCILE_NO_RESEND" && repairs.sends==3);
   runtime.State().Reconcile(0,true,9000000,0,0,500,0,0,true);
   DemoProtect(runtime.State(),0,repairs_store,repairs,190,boot,true,true,attempted);
   SProtection reconciled;repairs_store.Read(first.id,reconciled);
   Check("positive-close-settles-protection",reconciled.phase=="CLOSED" && !repairs_store.Unresolved());repairs_store.Close();runtime.Close();
   for(int scenario=0;scenario<4;scenario++)
   {
      FixturePort fixture;string base="protect-fault-"+IntegerToString(scenario);
      runtime.Open(base+".execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,fixture);
      runtime.State().Reconcile(0,true,9000000,9000000,0,500,700,0,true);
      fixture.expected_version=runtime.State().At(0).version;fixture.current_stop=0;
      DemoProtectionStore ps;ps.Open(base+".protection",b[0],true,"");ps.Begin(first.id,100,boot,100,200);
      if(scenario==0)fixture.enabled=false;
      if(scenario==1)fixture.uncertain=true;
      if(scenario==2){fixture.stale=true;fixture.contexts=0;}
      if(scenario==3)fixture.own=false;
      string outcome=DemoProtect(runtime.State(),0,ps,fixture,150,boot,true,true,attempted);
      Check("protective-fault-"+IntegerToString(scenario),scenario==0 ? outcome=="TRADING_DISABLED" && fixture.sends==1 :
         scenario==1 ? outcome=="PROTECTION_UNKNOWN" && fixture.sends==2 : scenario==2 ? outcome=="PROTECTION_NOT_SENT" && fixture.sends==1 : outcome=="NOT_OWNED" && fixture.sends==1);
      if(scenario==1)Check("lost-protection-reply-no-resend",DemoProtect(runtime.State(),0,ps,fixture,160,boot,true,false,attempted)=="RECONCILE_NO_RESEND" && fixture.sends==2);
      ps.Close();runtime.Close();
   }
   // Durable native observations survive lost ACKs and restart, with no PULL
   // until the original payload has been acknowledged.
   FixturePort reports;runtime.Open("reports.execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,reports);
   FixtureHistory observed;observed.comment=FxComment(first);cursor.Begin();result="INCOMPLETE";
   while(result=="INCOMPLETE")result=cursor.Step(runtime.State(),observed,2);
   DemoStateOutbox outbox;outbox.Open("reports.states",b[0],true,"");e=runtime.State().At(0);
   Check("state-needs-positive-query",!outbox.Publish(e,1767614400020,10,cursor.Proof(0),false));
   Check("partial-fill-state-durable",outbox.Publish(e,1767614400020,10,cursor.Proof(0),cursor.Confirmed(0)) && outbox.Pending()!="");
   string state=outbox.Pending();int states_file=FileOpen("demo-state.txt",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);FileWriteString(states_file,state+"\r\n");FileClose(states_file);
   Check("same-version-no-duplicate",outbox.Publish(e,1767614400030,10,cursor.Proof(0),true) && outbox.Pending()==state);
   outbox.Close();Check("state-restart-retained-tip",!outbox.Open("reports.states",b[0],false,"") && outbox.Open("reports.states",b[0],false,DgFileTip("reports.states")) && outbox.Pending()==state);
   Check("state-ack-durable",outbox.Ack(FxHash(state)) && outbox.Pending()=="");outbox.Close();
   Check("state-ack-restart",outbox.Open("reports.states",b[0],false,DgFileTip("reports.states")) && outbox.Pending()=="");outbox.Close();runtime.Close();
   DemoKernel complete;FixturePort simulated;
   Check("kernel-fixed-dispatch-complete",complete.Open("complete",b[0],b[1],b[2],b[3],b[4],true,"","","") && complete.Receive(packets[0],1767614400020,10,simulated) && simulated.sends==1);
   string attempted_receipt=complete.Pending();
   Check("attempt-receipt-not-no-order",StringFind(attempted_receipt,"demo-receipt/2\t")==0 && StringFind(attempted_receipt,"\tACKNOWLEDGED\tATTEMPTED")>0);
   int attempt_file=FileOpen("demo-attempt.txt",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);FileWriteString(attempt_file,attempted_receipt+"\r\n");FileClose(attempt_file);
   complete.Close();
   Check("attempt-restart-no-resend",complete.Open("complete",b[0],b[1],b[2],b[3],b[4],false,DgFileTip("complete.risk"),DgFileTip("complete.execution"),DgFileTip("complete.outcomes"),DgFileTip("complete.states")) && complete.Pending()==attempted_receipt && simulated.sends==1);
   FixtureHistory full_history;full_history.comment=FxComment(first);cursor.Begin();result="INCOMPLETE";
   while(result=="INCOMPLETE")result=cursor.Step(complete.State(),full_history,2);
   Check("kernel-reconciled-state-queued",complete.PublishState(complete.State().At(0),1767614400020,10,cursor.Proof(0),cursor.Confirmed(0)) && complete.Pending()==attempted_receipt);
   Check("attempt-ack",complete.Ack(FxHash(attempted_receipt)) && StringFind(complete.Pending(),"demo-state/1\t")==0);
   string full_state=complete.Pending();complete.Close();
   Check("kernel-state-restart",complete.Open("complete",b[0],b[1],b[2],b[3],b[4],false,DgFileTip("complete.risk"),DgFileTip("complete.execution"),DgFileTip("complete.outcomes"),DgFileTip("complete.states")) && complete.Pending()==full_state && complete.Ack(FxHash(full_state)) && complete.Pending()=="");complete.Close();
   DemoProtectionStore aborted;aborted.Open("not-sent.protection",b[0],true,"");aborted.Begin(first.id,100,boot,100,200);
   Check("own-before-send-only-exemption",aborted.Unresolved() && !aborted.Unresolved(first.id));
   Check("aborted-entry-settles-no-call",aborted.NoCall(first.id) && !aborted.Unresolved());aborted.Close();
   Check("no-call-restart",aborted.Open("not-sent.protection",b[0],false,DgFileTip("not-sent.protection")) && !aborted.Unresolved());aborted.Close();
   for(int i=0;i<2;i++)
   {
      string base="lifecycle-"+IntegerToString(i);DemoProtectionStore ps;ps.Open(base+".protection",b[0],true,"");
      LifecyclePort port;port.protection=GetPointer(ps);port.boot=boot;port.refuse_final=i==1;
      runtime.Open(base+".execution",b[0],true,"");string outcome=runtime.Dispatch(frames[0],risks[0],ledger,port);
      Check("entry-protection-lifecycle-"+IntegerToString(i),i==0 ? outcome=="ACKNOWLEDGED" && port.sends==1 && ps.Unresolved() : outcome=="FINAL_BARRIER_REFUSED" && port.sends==0 && !ps.Unresolved());
      runtime.Close();ps.Close();
   }
   for(int i=0;i<3;i++)
   {
      string base="protection-recovery-"+IntegerToString(i);FixturePort port;runtime.Open(base+".execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,port);
      runtime.State().Reconcile(0,true,9000000,9000000,0,500,700,0,true);port.expected_version=runtime.State().At(0).version;port.current_stop=0;
      DemoProtectionStore ps;ps.Open(base+".protection",b[0],true,"");ps.Begin(first.id,100,boot,100,200);
      if(i==0)
      {
         ps.Arm(first.id,"ATTACH_STOP_ONCE",150,boot,"crash-before-call");ps.Close();ps.Open(base+".protection",b[0],false,DgFileTip(base+".protection"));
         Check("pre-call-crash-no-resend",DemoProtect(runtime.State(),0,ps,port,160,boot,true,true,attempted)=="RECONCILE_NO_RESEND" && port.sends==1);
      }
      else if(i==1)
      {
         port.code=TRADE_RETCODE_REJECT;
         Check("exit-rejection-hard-halt",DemoProtect(runtime.State(),0,ps,port,310,boot,true,true,attempted)=="PROTECTION_REJECTED" && ps.HardHalt() && port.sends==2);
         Check("rejected-exit-never-retried",DemoProtect(runtime.State(),0,ps,port,320,boot,true,true,attempted)=="ALERT_EXIT_REJECTED" && port.sends==2);
      }
      else
      {
         DemoProtect(runtime.State(),0,ps,port,150,boot,true,true,attempted);
         runtime.State().Reconcile(0,true,9000000,9000000,0,500,700,1.098,true);
         Check("repair-positive-query-required",DemoProtect(runtime.State(),0,ps,port,160,boot,true,true,attempted)=="PROTECTED_CONFIRMED" && port.sends==2 && !ps.Unresolved());
      }
      ps.Close();runtime.Close();
   }
   for(int i=5;i<8;i++)
   {
      string base="management-"+IntegerToString(i);ManagementPort port;runtime.Open(base+".execution",b[0],true,"");runtime.Dispatch(frames[0],risks[0],ledger,port);
      runtime.State().Reconcile(0,true,9000000,9000000,0,500,700,1.098,true);port.expected_version=4;
      FxWork child;FxDecode(frames[i],child,true);
      Check("management-dispatch-"+child.action,runtime.Dispatch(frames[i],risks[i],ledger,port)=="ACKNOWLEDGED");
      ManagementHistory source;source.root_comment=FxComment(first);source.child_comment=FxComment(child);source.action=child.action;
      cursor.Begin();result="INCOMPLETE";while(result=="INCOMPLETE")result=cursor.Step(runtime.State(),source,2);
      DemoStateOutbox box;box.Open(base+".states",b[0],true,"");
      Check("management-reconciled-"+child.action,cursor.Confirmed(1) && box.Publish(runtime.State().At(1),1767614400020,10,cursor.Proof(1),true) && box.Pending()!="");
      int file=FileOpen("demo-state-"+child.action+".txt",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);FileWriteString(file,box.Pending()+"\r\n");FileClose(file);
      box.Close();runtime.Close();
   }
   DemoProtectionStore overlap;overlap.Open("overlap.protection",b[0],true,"");overlap.Begin(first.id,100,boot,100,200);
   Check("known-unprotected-not-inflight",!overlap.MutationPending(first.id));
   overlap.Arm(first.id,"ATTACH_STOP_ONCE",150,boot,"local-repair");
   Check("inflight-protection-blocks-management",overlap.MutationPending(first.id));overlap.Close();
   DemoAcceptanceBudget cap;FxWork limited=first;limited.currency="CAD";limited.volume=1000000;limited.max_risk=5;
   long budget_start=1767614400000,budget_end=budget_start+300000;
   string plan_hash=FxHash("bounded-demo-fixture"),cap_scope=FxScope(limited);
   Check("budget-open",cap.Open("acceptance.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),true,""));
   string original_tip=cap.Tip();
   Check("budget-refuse-not-flat",!cap.Charge(limited,budget_start,false,200000) && cap.Tip()==original_tip);
   Check("budget-charge",cap.Charge(limited,budget_start,true,200000) && cap.Charged()==1);
   string charged_tip=cap.Tip();cap.Close();
   Check("budget-stale-checkpoint",!cap.Open("acceptance.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),false,original_tip));
   Check("budget-restore",cap.Open("acceptance.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),false,charged_tip));
   Check("budget-no-duplicate",!cap.Charge(limited,budget_start+1,true,200000));
   FxWork second_limited=limited;second_limited.id="10000000-0000-4000-8000-000000000002";second_limited.digest=FxHash("second");
   Check("budget-unknown-blocks-second",!cap.Charge(second_limited,budget_start+1,true,200000));
   FxEntry done;ZeroMemory(done);done.work=limited;done.state="CLOSED";done.filled=1000000;
   Check("budget-no-absence-closure",!cap.ConfirmClosed(done,budget_start+2,FxHash("closed"),false,true));
   Check("budget-positive-closure",cap.ConfirmClosed(done,budget_start+2,FxHash("closed"),true,true));
   Check("budget-second-charge",cap.Charge(second_limited,budget_start+3,true,200000));
   done.work=second_limited;
   Check("budget-post-expiry-reconcile",cap.ConfirmClosed(done,budget_end+1,FxHash("second-close"),true,true));
   charged_tip=cap.Tip();cap.Close();
   Check("budget-two-restored-no-refund",cap.Open("acceptance.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),false,charged_tip) && cap.Charged()==2);
   cap.Close();
   Check("budget-expiry-open",cap.Open("expiry.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),true,""));
   Check("budget-expired-entry",!cap.Charge(limited,budget_end,true,200000));
   string expiry_tip=cap.Tip();cap.Close();
   Check("budget-expiry-restored",cap.Open("expiry.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,200000,25,50,"CAD",FxHash("equity"),false,expiry_tip));
   Check("budget-expiry-never-reopens",!cap.Charge(limited,budget_end-1,true,200000));cap.Close();
   Check("percent-budget-open",cap.Open("percent.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,400000,25,50,"CAD",FxHash("equity-4000"),true,""));
   limited.max_risk=10.01;
   Check("percent-budget-boundary-refusal",!cap.Charge(limited,budget_start,true,400000));
   limited.max_risk=10;
   Check("percent-budget-scales-equity",cap.Charge(limited,budget_start,true,400000));
   done.work=limited;cap.ConfirmClosed(done,budget_start+1,FxHash("percent-closed"),true,true);
   second_limited.max_risk=5;
   Check("percent-budget-falling-equity-total",!cap.Charge(second_limited,budget_start+2,true,200000));
   second_limited.max_risk=10.01;
   Check("percent-budget-gains-no-expansion",!cap.Charge(second_limited,budget_start+2,true,800000));
   cap.Close();
   Check("drain-budget-open",cap.Open("drain.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,400000,25,50,"CAD",FxHash("drain-equity"),true,""));
   Check("entry-boundary-uncertainty",cap.EntriesOpen(budget_start+100,100) && !cap.EntriesOpen(budget_start+99,100) && !cap.EntriesOpen(budget_end-100,100));
   Check("entry-monotonic-deadline",DemoEntryWindowOpen(cap,budget_start+100,0,999,1000) && !DemoEntryWindowOpen(cap,budget_start+100,0,1000,1000));
   Check("entry-deadline-required",!DemoEntryWindowOpen(cap,budget_start+100,0,1,0));
   limited.max_risk=5;
   Check("drain-charge-retained",cap.Charge(limited,budget_start,true,400000) && cap.Drain() && cap.Drain() && cap.Charged()==1);
   string drain_tip=cap.Tip();cap.Close();
   Check("drain-restart-closed",cap.Open("drain.budget",cap_scope,limited.release,limited.policy,plan_hash,budget_start,budget_end,400000,25,50,"CAD",FxHash("drain-equity"),false,drain_tip) && cap.Draining() && !cap.EntriesOpen(budget_start+10,0));
   Check("drain-entry-never-reopens",!cap.Charge(second_limited,budget_start+10,true,400000));
   done.work=limited;
   Check("drain-positive-closure-remains",cap.ConfirmClosed(done,budget_end+10,FxHash("drain-closed"),true,true));cap.Close();
   FixturePort drain_port;runtime.Open("drain.execution",b[0],true,"");
   Check("drain-empty-no-positive-query",!DemoDrainComplete(runtime.State(),cursor,false,true,true,false,false));
   runtime.Dispatch(frames[0],risks[0],ledger,drain_port);
   Check("drain-ack-not-flat-proof",!DemoDrainComplete(runtime.State(),cursor,true,true,true,false,false));
   ClosedHistory closing;closing.comment=FxComment(first);cursor.Begin();result="INCOMPLETE";
   while(result=="INCOMPLETE")result=cursor.Step(runtime.State(),closing,2);
   Check("drain-positive-close",cursor.Confirmed(0) && DemoDrainComplete(runtime.State(),cursor,true,true,true,false,false));
   Check("drain-report-must-deliver",!DemoDrainComplete(runtime.State(),cursor,true,true,true,false,true));
   Check("drain-disconnection-not-completion",!DemoDrainComplete(runtime.State(),cursor,true,false,true,false,false));
   Check("drain-unexpected-exposure",!DemoDrainComplete(runtime.State(),cursor,true,true,false,false,false));
   Check("drain-protection-unknown",!DemoDrainComplete(runtime.State(),cursor,true,true,true,true,false));
   cursor.Invalidate();
   Check("drain-invalidated-scan",!DemoDrainComplete(runtime.State(),cursor,true,true,true,false,false));runtime.Close();
   FileClose(checks);return INIT_SUCCEEDED;
}
void OnTick(){ TesterStop(); }
