#property strict
#property tester_file "m2c-risk.tsv"
#include "../../../mql5/safety/Risk.mqh"
#include "../../../mql5/safety/Control.mqh"
#include "../../../mql5/safety/Fence.mqh"
#include "../../../mql5/safety/Preflight.mqh"
#include "../../../mql5/safety/StateStore.mqh"
#include "../../../mql5/safety/Exposure.mqh"
#include "../../../mql5/gateway/Core.mqh"
int checks=0,failures=0;
void Check(bool ok,string name)
{
   checks++; if(!ok) failures++;
   Print("FX_M2C_CHECK ",name," ",(ok ? "PASS" : "FAIL"));
}
bool RiskCases()
{
   int source_handle=FileOpen("m2c-risk.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int output=FileOpen("m2c-native.tsv",FILE_WRITE|FILE_CSV|FILE_ANSI,'\t',CP_UTF8);
   if(source_handle==INVALID_HANDLE || output==INVALID_HANDLE) return false;
   string keys[],row[]; int count=StringSplit(FileReadString(source_handle),'\t',keys),cases=0;
   FileWrite(output,"id","reason","volume","risk","gross","margin","duration_us");
   while(!FileIsEnding(source_handle))
   {
      string line=FileReadString(source_handle); if(line=="") continue;
      if(StringSplit(line,'\t',row)!=count) { FileClose(source_handle); FileClose(output); return false; }
      double volume,loss,gross,margin; ulong start=GetMicrosecondCount();
      string reason=SRisk(keys,row,volume,loss,gross,margin);
      ulong elapsed=GetMicrosecondCount()-start;
      FileWrite(output,row[0],reason,DoubleToString(volume,8),DoubleToString(loss,6),DoubleToString(gross,6),DoubleToString(margin,6),elapsed);
      if(cases==0)
      {
         SLoss ledger; ledger.day=1; ledger.start=10000; ledger.flows=0; ledger.units=10000; ledger.high=1;
         ledger.loss=0; ledger.paused=false; ledger.hard=false; ledger.owner=false;
         Check(SPreflight(keys,row,ledger,1000,0.08,25,true,true,volume,loss,gross,margin)=="ACCEPTED" && volume==0.08,"compose-narrows-reservation");
         Check(SPreflight(keys,row,ledger,1500,0.09,25,true,true,volume,loss,gross,margin)=="QUOTE_STALE","compose-rechecks-age");
         ledger.hard=true;
         Check(SPreflight(keys,row,ledger,0,0.09,25,true,true,volume,loss,gross,margin)=="HARD_HALT","compose-persisted-halt");
         ledger.hard=false; ledger.owner=true;
         Check(SPreflight(keys,row,ledger,0,0.09,25,true,true,volume,loss,gross,margin)=="OWNER_PAUSED","compose-owner-pause");
      }
      cases++;
   }
   FileFlush(output); FileClose(source_handle); FileClose(output);
   Print("FX_M2C_RISK_CASES ",cases);
   return cases>0;
}
void Controls()
{
   SPosition positions[1]; SReservation reserves[1]; SExposure exposure;
   positions[0].scope="scope"; positions[0].id="position"; positions[0].reservation="reserve";
   positions[0].symbol="EURUSD"; positions[0].side="BUY"; positions[0].volume=0.04;
   positions[0].liquidation=1.1; positions[0].stop=1.098; positions[0].contract=100000;
   positions[0].base_rate=1.1; positions[0].quote_rate=1; positions[0].exit_cost=4;
   positions[0].margin=88; positions[0].owned=true;
   reserves[0].scope="scope"; reserves[0].id="reserve"; reserves[0].symbol="EURUSD"; reserves[0].side="BUY";
   reserves[0].authorized=0.09; reserves[0].filled=0.04; reserves[0].pending=0.05;
   reserves[0].risk=233; reserves[0].base=110000; reserves[0].counter=110020;
   reserves[0].margin=2200; reserves[0].final_order=false; reserves[0].unknown=false;
   Check(SAggregate("scope",positions,reserves,exposure) && MathAbs(exposure.risk-19.81)<1e-8 && MathAbs(exposure.gross-9900)<1e-8 && MathAbs(exposure.margin-198)<1e-8 && exposure.slots==1,"partial-no-double-count");
   reserves[0].unknown=true;
   Check(SAggregate("scope",positions,reserves,exposure) && exposure.flags==4 && MathAbs(exposure.risk-19.81)<1e-8,"unknown-keeps-remainder");
   reserves[0].unknown=false; reserves[0].final_order=true; reserves[0].pending=0;
   Check(SAggregate("scope",positions,reserves,exposure) && MathAbs(exposure.risk-8.16)<1e-8 && exposure.slots==1,"confirmed-cancel-releases-only-remainder");
   positions[0].stop=0;
   Check(SAggregate("scope",positions,reserves,exposure) && exposure.flags==8,"unprotected-account-block");
   positions[0].stop=1.098; positions[0].owned=false;
   Check(SAggregate("scope",positions,reserves,exposure) && exposure.flags==32,"external-exposure-block");
   reserves[0].authorized=0.08; reserves[0].pending=0.05;
   Check(!SAggregate("scope",positions,reserves,exposure),"rounded-reservation-no-expansion");
   Check(!SAggregate("wrong-scope",positions,reserves,exposure),"exposure-account-mismatch");
   SLoss s; s.day=1; s.start=10000; s.flows=0; s.units=10000; s.high=1; s.loss=0; s.paused=false; s.hard=false; s.owner=true;
   Check(SLossStep(s,1,9900,0,0,true,0) && s.paused && !s.hard,"daily-boundary");
   Check(SLossStep(s,1,19900,10000,9900,true,0) && s.paused && MathAbs(s.loss-100)<1e-6,"deposit-preserves-loss");
   Check(!SLossStep(s,2,19900,0,0,true,0),"no-midnight-proof");
   Check(SLossStep(s,2,19900,0,0,true,19900) && !s.paused && s.owner,"utc-rollover-owner-persists");
   Check(SLossStep(s,2,s.units*0.95,0,0,true,0) && s.hard,"drawdown-boundary");
   Check(SLossStep(s,3,30000,0,0,true,30000) && s.hard,"hard-halt-persists");
   Check(!SLossStep(s,2,30000,0,0,true,0),"clock-day-regression");
   Check(!SLossStep(s,3,30000,100,0,true,0),"flow-needs-evidence");
   Check(SState(127)=="HARD_HALT" && SState(126)=="LOSS_PAUSE","composed-precedence");
   SProtection p; p.phase="PENDING"; p.boot="boot-a"; p.submitted=0; p.repair=1000; p.exit=2000; p.last=0; p.hard=false;
   Check(SProtect(p,100,"boot-a",false,true,true,false,false,false)=="ALERT_STORAGE_NO_MUTATION","storage-failure");
   Check(SProtect(p,100,"boot-a",true,true,true,false,false,false)=="ATTACH_STOP_ONCE","repair-once");
   Check(SProtect(p,101,"boot-a",true,true,false,false,false,true)=="RECONCILE_NO_RESEND","lost-repair-ack");
   Check(SProtect(p,2001,"boot-a",true,false,false,false,false,false)=="RECONCILE_NO_RESEND" && p.hard,"unknown-deadline-halt");
   Check(SProtect(p,2002,"boot-a",true,true,true,false,true,false)=="CLOSED_CONFIRMED" && p.hard,"closure-keeps-halt");
   Check(SProtect(p,2003,"boot-a",true,true,true,false,false,false)=="RECONCILE_NO_RESEND","closed-not-readopted");
   p.phase="PENDING"; p.last=0; p.hard=false;
   Check(SProtect(p,1000,"boot-a",true,true,true,false,false,false)=="CONTROLLED_EXIT_ONCE","repair-deadline-exit");
   Check(SProtect(p,1001,"boot-a",true,true,true,false,false,false,true)=="ALERT_EXIT_REJECTED" && p.hard,"exit-rejected");
   p.phase="REPAIRING"; p.last=0; p.hard=false;
   Check(SProtect(p,500,"boot-a",true,true,true,false,false,false,true)=="CONTROLLED_EXIT_ONCE","repair-rejected-exit");
   p.phase="PENDING"; p.last=0; p.hard=false;
   Check(SProtect(p,1,"boot-b",true,true,true,false,false,false)=="RECONCILE_CLOCK_NO_MUTATION" && p.hard,"reboot-not-new-timer");
   p.phase="PROTECTED"; p.last=1; p.hard=false;
   Check(SProtect(p,3000,"boot-a",true,true,true,true,false,false)=="PROTECTED_CONFIRMED" && !p.hard,"settled-no-false-deadline");
   Check(SFence(2,2,5000,1000,10,0,1,true,true,true)=="ACCEPTED","fence-valid");
   Check(SFence(2,1,5000,1000,10,0,1,true,true,true)=="FENCED","old-writer");
   Check(SFence(2,2,5000,4990,10,0,1,true,true,true)=="EXPIRED","lease-expiry-boundary");
   Check(SFence(2,2,5000,1000,10,1,1,true,true,true)=="SEQUENCE_CONFLICT","replayed-sequence");
   Check(SFence(2,2,5000,1000,10,0,1,true,true,false)=="AUTHENTICATION_FAILURE","bad-auth");
   Check(SFence(2,2,5000,1000,101,0,1,true,true,true)=="CLOCK_UNVERIFIED","fence-clock");
   Check(SFence(2,2,5000,1000,10,0,1,false,true,true)=="STARTUP_RECONCILE","restart-fence");
   int auth=FileOpen("m2c-hmac.txt",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(auth,SHmac("kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk","fixture")+"\n"); FileFlush(auth); FileClose(auth);
   string records[]; FxJournal journal,second;
   Check(journal.Open("m2c-loss.journal",records),"open-durable-copy");
   Check(journal.Append("fixture-scope\t1\tHARD_HALT\tOWNER_PAUSED\tOUTCOME_UNKNOWN"),"persist-restrictions");
   Check(!second.Open("m2c-loss.journal",records),"exclusive-writer");
   journal.Close();
   Check(journal.Open("m2c-loss.journal",records) && ArraySize(records)>=1 && records[ArraySize(records)-1]=="fixture-scope\t1\tHARD_HALT\tOWNER_PAUSED\tOUTCOME_UNKNOWN","restart-preserves-restrictions");
   journal.Close();
   SStateStore durable;
   Check(!durable.Open("m2c-never-created.journal","scope-a",false,s),"loss-store-no-silent-reset");
   Check(durable.Open("m2c-full-loss.journal","scope-a",true,s),"loss-store-bootstrap");
   Check(durable.Store(s,5),"loss-store-full-state");
   durable.Close();
   Check(durable.Open("m2c-full-loss.journal","scope-a",false,s) && durable.State().hard && durable.State().owner && durable.Epoch()==5,"loss-store-reopen");
   SLoss attempted=s; attempted.hard=false;
   Check(!durable.Store(attempted,6),"loss-store-halt-cannot-clear");
   Check(!durable.Store(s,4),"loss-store-epoch-cannot-regress");
   attempted=s; attempted.high=s.high/2;
   Check(!durable.Store(attempted,6),"loss-store-high-water-cannot-regress");
   attempted=s; attempted.start=s.start*2;
   Check(!durable.Store(attempted,6),"loss-store-day-baseline-cannot-reset");
   durable.Close();
   Check(!durable.Open("m2c-full-loss.journal","scope-b",false,s),"loss-store-wrong-account");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) { Print("FX_M2C_CONNECTED_EXECUTION_DISABLED"); return INIT_FAILED; }
   Controls(); Check(RiskCases(),"risk-file-complete");
   Print("FX_M2C_SUMMARY checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
