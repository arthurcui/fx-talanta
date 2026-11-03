#ifndef FX_NATIVE_TESTS_MQH
#define FX_NATIVE_TESTS_MQH
#include "Core.mqh"

int fx_checks=0,fx_failures=0;
void FxCheck(const string name,const bool pass)
{
   fx_checks++; if(!pass) fx_failures++;
   Print("FX_M2B_CHECK ",name," ",pass ? "PASS" : "FAIL");
}

FxContext FxFixtureContext()
{
   FxContext c;
   c.broker="fixture"; c.server="offline"; c.login="42"; c.currency="USD";
   c.release="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; c.policy=c.release; c.symbol="FXT_EURUSD";
   c.now_ms=(long)D'2026.01.05 00:00:01'*1000; c.tick_ms=c.now_ms; c.clock_error_ms=0;
   c.min_lot=1000000; c.max_lot=10000000000; c.lot_step=1000000;
   c.bid=1.1; c.ask=1.1002; c.tick_size=0.00001; c.min_stop=0.0001; c.freeze_distance=0.0001;
   c.connected=true; c.session_open=true; c.unknown_exposure=false; c.owner_pause=false; c.loss_halt=false;
   c.owned=false; c.mutation_unknown=false; c.position=0; c.order=0; c.position_volume=0; c.position_version=0;
   c.position_side="BUY"; c.accepted_stop=0; c.accepted_target=0;
   return c;
}

bool FxRunNativeTests()
{
   fx_checks=0; fx_failures=0;
   int file=FileOpen("m2b-requests.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(file==INVALID_HANDLE) { FxCheck("fixture_file",false); return false; }
   string frames[]; ArrayResize(frames,8);
   for(int i=0;i<8;i++) frames[i]=FileReadString(file);
   FileClose(file);
   FxWork w; FxContext c=FxFixtureContext(); long volume=0;
   FxCheck("python_native_canonical_hash",FxDecode(frames[0],w)=="OK");
   FxCheck("entry_buy",FxValidate(w,c,volume)=="OK" && volume==9000000);
   FxContext bad=c; bad.tick_ms-=2001;
   FxCheck("two_second_ceiling",FxValidate(w,bad,volume)=="STALE_QUOTE");
   bad=c; bad.tick_ms-=2000; FxCheck("two_second_boundary",FxValidate(w,bad,volume)=="OK");
   bad=c; bad.login="43"; FxCheck("wrong_account",FxValidate(w,bad,volume)=="ACCOUNT_MISMATCH");
   bad=c; bad.policy="b"; FxCheck("wrong_policy",FxValidate(w,bad,volume)=="RELEASE_POLICY_MISMATCH");
   bad=c; bad.symbol="FXT_USDJPY"; FxCheck("wrong_symbol",FxValidate(w,bad,volume)=="SYMBOL_MISMATCH");
   bad=c; bad.now_ms=w.expires_ms; FxCheck("expiry",FxValidate(w,bad,volume)=="EXPIRED");
   bad=c; bad.clock_error_ms=101; FxCheck("clock_uncertainty",FxValidate(w,bad,volume)=="CLOCK_UNCERTAIN");
   bad=c; bad.lot_step=4000000; bad.min_lot=4000000; FxCheck("volume_rounds_down",FxValidate(w,bad,volume)=="OK" && volume==8000000);
   bad=c; bad.min_lot=10000000; FxCheck("minimum_lot",FxValidate(w,bad,volume)=="MINIMUM_LOT");
   bad=c; bad.unknown_exposure=true; FxCheck("unknown_exposure",FxValidate(w,bad,volume)=="ENTRY_BLOCKED");
   bad=c; bad.loss_halt=true; FxCheck("persistent_loss_halt",FxValidate(w,bad,volume)=="ENTRY_BLOCKED");
   FxCheck("tamper",FxDecode(frames[0]+"x",w)=="HASH_MISMATCH" || FxDecode(frames[0]+"x",w)=="SCHEMA_INVALID");
   FxCheck("sell_decode",FxDecode(frames[6],w)=="OK");
   FxCheck("entry_sell",FxValidate(w,c,volume)=="OK");
   FxCheck("jpy_decode",FxDecode(frames[7],w)=="OK");
   bad=c; bad.symbol="FXT_USDJPY"; bad.bid=150; bad.ask=150.02; bad.tick_size=0.001; bad.min_stop=0.01;
   FxCheck("jpy_sell",FxValidate(w,bad,volume)=="OK");
   FxCheck("close_decode",FxDecode(frames[3],w)=="OK");
   bad=c; bad.owned=true; bad.position=101; bad.position_version=3; bad.position_volume=9000000;
   FxCheck("owned_close",FxValidate(w,bad,volume)=="OK");
   bad.position_volume=1000000; FxCheck("oversized_close",FxValidate(w,bad,volume)=="STATE_MISMATCH");
   bad.position_volume=9000000; bad.position_version=4; FxCheck("stale_close",FxValidate(w,bad,volume)=="STATE_MISMATCH");
   bad.position_version=3; bad.mutation_unknown=true; FxCheck("unknown_close",FxValidate(w,bad,volume)=="STATE_MISMATCH");
   FxCheck("tighten_decode",FxDecode(frames[4],w)=="OK");
   bad.mutation_unknown=false; bad.accepted_stop=1.098;
   FxCheck("tighten_only",FxValidate(w,bad,volume)=="OK");
   bad.accepted_stop=1.0995; FxCheck("stop_widening_rejected",FxValidate(w,bad,volume)=="STOP_NOT_TIGHTER");
   FxCheck("cancel_decode",FxDecode(frames[5],w)=="OK");
   bad.order=202; FxCheck("owned_cancel",FxValidate(w,bad,volume)=="OK");
   bad.owned=false; FxCheck("external_cancel",FxValidate(w,bad,volume)=="NOT_OWNED");

   string path="fx-m2b-tests/"+IntegerToString((long)GetTickCount64())+".journal";
   FxGateway gateway; FxCheck("durable_journal_open",gateway.Open(path));
   FxGateway second; FxCheck("single_writer_lock",!second.Open(path));
   int index; FxCheck("first_admission",gateway.Admit(frames[0],c,index)=="OK");
   FxCheck("write_ahead",gateway.MarkSubmitting(index));
   FxCheck("lost_ack",gateway.Result(index,false,0,"LOST_RESPONSE"));
   FxCheck("unknown_blocks_account",gateway.Uncertain());
   FxCheck("replay_no_resend",gateway.Admit(frames[0],c,index)=="REPLAY" && !gateway.MarkSubmitting(index));
   FxCheck("payload_conflict",gateway.Admit(frames[1],c,index)=="HASH_CONFLICT");
   gateway.Close(); FxCheck("restart_load",gateway.Open(path));
   FxCheck("restart_unknown_retained",gateway.Uncertain() && gateway.Count()==1);
   FxCheck("empty_history_not_proof",!gateway.Reconcile(0,false,0,0,0,0,0,0,true));
   FxCheck("partial_fill",gateway.Reconcile(0,true,3000000,3000000,6000000,202,101,0,false));
   FxEntry entry=gateway.At(0);
   FxCheck("partial_conservation",entry.filled+entry.remaining==9000000 && entry.state=="PROTECTION_PENDING");
   FxCheck("protection_query",gateway.Reconcile(0,true,3000000,3000000,6000000,202,101,1.098,false));
   FxCheck("protected_partial_still_reserved",gateway.Uncertain());
   FxCheck("wider_stop_query",gateway.Reconcile(0,true,3000000,3000000,6000000,202,101,1.097,false));
   entry=gateway.At(0); FxCheck("wider_stop_not_protected",entry.state=="PROTECTION_PENDING");
   FxCheck("restored_stop_query",gateway.Reconcile(0,true,3000000,3000000,6000000,202,101,1.098,false));
   entry=gateway.At(0); long version=entry.version;
   FxCheck("duplicate_callback",gateway.Reconcile(0,true,3000000,3000000,6000000,202,101,1.098,false));
   entry=gateway.At(0); FxCheck("callback_idempotency",entry.version==version);
   FxCheck("fill_cannot_regress",!gateway.Reconcile(0,true,1000000,1000000,8000000,202,101,1.098,false));
   FxCheck("final_fill",gateway.Reconcile(0,true,9000000,9000000,0,202,101,1.098,true));
   FxCheck("closed_positive",gateway.Reconcile(0,true,9000000,0,0,202,101,0,true));
   gateway.Close(); FxCheck("completed_restart",gateway.Open(path));
   entry=gateway.At(0); FxCheck("closed_retained",entry.state=="CLOSED" && entry.remaining==0);
   gateway.Close();
   file=FileOpen(path,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8); FileWriteString(file,"corrupt\r\n"); FileClose(file);
   FxCheck("corruption_halts",!gateway.Open(path));
   FxCheck("journal_failure_no_submit",!gateway.MarkSubmitting(0));
   Print("FX_M2B_NATIVE_RESULT checks=",fx_checks," failures=",fx_failures);
   return fx_failures==0;
}
#endif
