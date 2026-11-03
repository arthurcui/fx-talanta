#ifndef FX_CORE_MQH
#define FX_CORE_MQH
#include "Wire.mqh"

struct FxContext
{
   string broker,server,login,currency,release,policy,symbol;
   long now_ms,tick_ms,clock_error_ms,min_lot,max_lot,lot_step;
   double bid,ask,tick_size,min_stop,freeze_distance;
   bool connected,session_open,unknown_exposure,owner_pause,loss_halt;
   bool owned,mutation_unknown;
   ulong position,order;
   long position_volume,position_version;
   string position_side;
   double accepted_stop,accepted_target;
};

struct FxEntry
{
   FxWork work;
   string state,reason;
   long version,filled,open_volume,remaining;
   ulong order,position;
   double accepted_stop;
};

class FxJournal
{
private:
   int handle;
   long sequence;
   string previous;
public:
   FxJournal(){ handle=INVALID_HANDLE; sequence=0; previous="GENESIS"; }
   void Close(){ if(handle!=INVALID_HANDLE) FileClose(handle); handle=INVALID_HANDLE; }
   bool Open(const string path,string &records[])
   {
      Close(); sequence=0; previous="GENESIS"; ArrayResize(records,0);
      // No share flags: one writer owns this journal for the entire EA lifetime.
      handle=FileOpen(path,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
      if(handle==INVALID_HANDLE) return false;
      while(!FileIsEnding(handle))
      {
         string line=FileReadString(handle),part[];
         if(StringLen(line)==0 || StringLen(line)>8192 || StringSplit(line,'|',part)!=4) { Close(); return false; }
         if(StringToInteger(part[0])!=sequence+1 || part[1]!=previous || FxHash(part[0]+"|"+part[1]+"|"+part[2])!=part[3]) { Close(); return false; }
         int n=ArraySize(records); ArrayResize(records,n+1); records[n]=part[2];
         sequence++; previous=part[3];
      }
      return true;
   }
   bool Append(const string record)
   {
      if(handle==INVALID_HANDLE || StringFind(record,"|")>=0) return false;
      string body=IntegerToString(sequence+1)+"|"+previous+"|"+record;
      string digest=FxHash(body),line=body+"|"+digest+"\r\n";
      ResetLastError();
      if(FileWriteString(handle,line)!=StringLen(line)) return false;
      FileFlush(handle);
      if(GetLastError()!=0) return false;
      sequence++; previous=digest;
      return true;
   }
};

string FxValidate(const FxWork &w,const FxContext &c,long &volume)
{
   volume=0;
   if(w.broker!=c.broker || w.server!=c.server || w.login!=c.login || w.currency!=c.currency) return "ACCOUNT_MISMATCH";
   if(w.release!=c.release || w.policy!=c.policy) return "RELEASE_POLICY_MISMATCH";
   if(w.broker_symbol!=c.symbol || w.broker_symbol!="FXT_"+w.symbol) return "SYMBOL_MISMATCH";
   if(c.clock_error_ms<0 || c.clock_error_ms>100) return "CLOCK_UNCERTAIN";
   if(w.created_ms>c.now_ms-c.clock_error_ms) return "FUTURE_MESSAGE";
   if(w.expires_ms<=c.now_ms+c.clock_error_ms) return "EXPIRED";
   if(!c.connected || !c.session_open) return "CHANNEL_UNAVAILABLE";
   if(c.tick_ms>c.now_ms || c.now_ms+c.clock_error_ms-c.tick_ms>2000) return "STALE_QUOTE";
   if(!MathIsValidNumber(c.bid) || !MathIsValidNumber(c.ask) || c.bid<=0 || c.ask<c.bid || c.tick_size<=0) return "INVALID_QUOTE";
   if(c.lot_step<=0 || c.min_lot<=0 || c.max_lot<c.min_lot) return "INVALID_VOLUME_SPEC";
   volume=(w.volume<c.max_lot ? w.volume : c.max_lot)/c.lot_step*c.lot_step;
   if(volume<c.min_lot) return "MINIMUM_LOT";
   if(w.action=="ENTER")
   {
      if(c.loss_halt || c.owner_pause || c.unknown_exposure || c.position!=0 || c.order!=0) return "ENTRY_BLOCKED";
   }
   else
   {
      if(!c.owned) return "NOT_OWNED";
      if(c.mutation_unknown || c.position_version!=w.expected_version) return "STATE_MISMATCH";
      if(w.action=="CANCEL") return w.order==c.order ? "OK" : "STATE_MISMATCH";
      if(w.position!=c.position || c.position_volume<=0 || w.volume>c.position_volume) return "STATE_MISMATCH";
      // Never round an oversized close down and silently accept a stale request.
      if(w.action=="CLOSE") return "OK";
      if(w.side!="~" && w.side!=c.position_side) return "STATE_MISMATCH";
   }
   double stop=(double)w.stop/100000000,target=(double)w.target/100000000;
   bool buy=(w.action=="ENTER" ? w.side=="BUY" : c.position_side=="BUY");
   double market=buy ? c.bid : c.ask;
   if(stop<=0 || MathAbs(stop/c.tick_size-MathRound(stop/c.tick_size))>1e-6) return "INVALID_STOP";
   if((buy && stop>=market-c.min_stop) || (!buy && stop<=market+c.min_stop)) return "INVALID_STOP";
   if(w.action=="ENTER")
   {
      if(target<=0 || MathAbs(target/c.tick_size-MathRound(target/c.tick_size))>1e-6) return "INVALID_TARGET";
      if((buy && target<=c.ask+c.min_stop) || (!buy && target>=c.bid-c.min_stop)) return "INVALID_TARGET";
   }
   else
   {
      if(c.accepted_stop>0 && ((buy && stop<=c.accepted_stop) || (!buy && stop>=c.accepted_stop))) return "STOP_NOT_TIGHTER";
      if(MathAbs(market-stop)<=c.freeze_distance) return "FREEZE_LEVEL";
   }
   return "OK";
}

class FxGateway
{
private:
   FxJournal journal;
   FxEntry entries[];
   bool healthy;
   long request_sequence;
   int Find(const string id){ for(int i=0;i<ArraySize(entries);i++) if(entries[i].work.id==id) return i; return -1; }
   string Encode(const FxEntry &e)
   {
      return e.state+"\t"+e.reason+"\t"+IntegerToString(e.version)+"\t"+IntegerToString(e.filled)+"\t"+IntegerToString(e.open_volume)+"\t"+
         IntegerToString(e.remaining)+"\t"+IntegerToString((long)e.order)+"\t"+IntegerToString((long)e.position)+"\t"+FxDecimal(e.accepted_stop)+"\t"+e.work.frame;
   }
   bool Store(FxEntry &e)
   {
      if(!healthy || !journal.Append(Encode(e))) { healthy=false; return false; }
      int index=Find(e.work.id);
      if(index<0) { index=ArraySize(entries); ArrayResize(entries,index+1); }
      entries[index]=e;
      return true;
   }
public:
   FxGateway(){ healthy=false; request_sequence=0; }
   void Close(){ journal.Close(); healthy=false; }
   bool Open(const string path)
   {
      healthy=false; request_sequence=0; ArrayResize(entries,0); string rows[];
      if(!journal.Open(path,rows)) return false;
      for(int i=0;i<ArraySize(rows);i++)
      {
         string f[]; if(StringSplit(rows[i],'\t',f)!=37) { journal.Close(); return false; }
         string frame=f[9]; for(int j=10;j<37;j++) frame+="\t"+f[j];
         FxEntry e;
         if(FxDecode(frame,e.work)!="OK") { journal.Close(); return false; }
         e.state=f[0]; e.reason=f[1]; e.version=StringToInteger(f[2]); e.filled=StringToInteger(f[3]); e.open_volume=StringToInteger(f[4]);
         e.remaining=StringToInteger(f[5]); e.order=(ulong)StringToInteger(f[6]); e.position=(ulong)StringToInteger(f[7]); e.accepted_stop=StringToDouble(f[8]);
         int index=Find(e.work.id);
         if(index<0) { if(e.work.sequence!=request_sequence+1 || e.version!=1) { journal.Close(); return false; } index=ArraySize(entries); ArrayResize(entries,index+1); request_sequence++; }
         else if(entries[index].work.digest!=e.work.digest || e.version!=entries[index].version+1) { journal.Close(); return false; }
         entries[index]=e;
      }
      healthy=true;
      return true;
   }
   int Count(){ return ArraySize(entries); }
   FxEntry At(const int index){ return entries[index]; }
   bool Uncertain()
   {
      if(!healthy) return true;
      for(int i=0;i<ArraySize(entries);i++) if(entries[i].remaining>0 || entries[i].state=="READY" || entries[i].state=="SUBMITTING" || entries[i].state=="OUTCOME_UNKNOWN" || entries[i].state=="PROTECTION_PENDING" || entries[i].state=="ACKNOWLEDGED") return true;
      return false;
   }
   string Admit(const string frame,const FxContext &context,int &index)
   {
      index=-1; if(!healthy) return "JOURNAL_UNAVAILABLE";
      FxWork w; string decoded=FxDecode(frame,w); if(decoded!="OK") return decoded;
      if(w.broker!=context.broker || w.server!=context.server || w.login!=context.login) return "ACCOUNT_MISMATCH";
      index=Find(w.id);
      if(index>=0) return entries[index].work.digest==w.digest ? "REPLAY" : "HASH_CONFLICT";
      if(w.sequence!=request_sequence+1) return "SEQUENCE_GAP";
      if(ArraySize(entries)>=1024) return "JOURNAL_CAPACITY";
      for(int i=0;i<ArraySize(entries);i++) if(entries[i].work.reservation==w.reservation) return "RESERVATION_CONFLICT";
      long lots; string reason=FxValidate(w,context,lots);
      if(reason=="OK" && w.action=="ENTER" && Uncertain()) reason="OUTCOME_UNKNOWN";
      FxEntry e; e.work=w; e.state=reason=="OK" ? "READY" : "REJECTED"; e.reason=reason; e.version=1;
      e.filled=0; e.open_volume=0; e.remaining=reason=="OK" ? lots : 0; e.order=0; e.position=0; e.accepted_stop=0;
      if(!Store(e)) return "JOURNAL_UNAVAILABLE";
      request_sequence++; index=Find(w.id);
      return reason;
   }
   bool MarkSubmitting(const int index)
   {
      if(index<0 || index>=Count() || entries[index].state!="READY") return false;
      FxEntry e=entries[index]; e.state="SUBMITTING"; e.version++; return Store(e);
   }
   bool Result(const int index,const bool accepted,const ulong order,const string reason)
   {
      if(index<0 || index>=Count() || entries[index].state!="SUBMITTING") return false;
      FxEntry e=entries[index]; e.state=accepted ? "ACKNOWLEDGED" : "OUTCOME_UNKNOWN";
      e.reason=reason; e.order=order; e.version++; return Store(e);
   }
   bool AbortBeforeCall(const int index,const string reason)
   {
      if(index<0 || index>=Count() || (entries[index].state!="READY" && entries[index].state!="SUBMITTING")) return false;
      FxEntry e=entries[index]; e.state="REJECTED"; e.reason=reason; e.remaining=0; e.version++; return Store(e);
   }
   bool Reconcile(const int index,const bool positive,const long filled,const long open_volume,const long pending,
                  const ulong order,const ulong position,const double stop,const bool final_order)
   {
      if(index<0 || index>=Count() || !positive || !MathIsValidNumber(stop) || stop<0) return false;
      FxEntry e=entries[index];
      if(e.state=="READY" || e.state=="REJECTED" || filled<e.filled || filled<open_volume || open_volume<0 || pending<0 || filled+pending>e.work.volume) return false;
      if(open_volume>0 && position==0) return false;
      double requested_stop=(double)e.work.stop/100000000;
      bool protected_stop=stop>0 && (e.work.side=="BUY" ? stop>=requested_stop : stop<=requested_stop);
      string state=open_volume>0 ? (protected_stop ? "PROTECTED" : "PROTECTION_PENDING") : (final_order ? "CLOSED" : "OUTCOME_UNKNOWN");
      long unfilled=e.work.volume-filled;
      long remaining=final_order ? pending : (pending>unfilled ? pending : unfilled);
      if(state==e.state && filled==e.filled && open_volume==e.open_volume && remaining==e.remaining && stop==e.accepted_stop && order==e.order && position==e.position) return true;
      e.filled=filled; e.open_volume=open_volume; e.remaining=remaining; e.order=order; e.position=position; e.accepted_stop=stop;
      e.state=state; e.reason="BROKER_QUERY"; e.version++; return Store(e);
   }
};
#endif
