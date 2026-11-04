#ifndef FX_DISABLED_KERNEL
#define FX_DISABLED_KERNEL
#include "../gateway/Core.mqh"
#include "../shadow/Protocol.mqh"
#include "../safety/Preflight.mqh"
// One journal: binding, authoritative loss replica, native verdict and ACK.
// There is deliberately no Broker.mqh, dispatcher, OrderSend or CTrade import.
string DgFileTip(string path)
{
   int h=FileOpen(path,FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(h==INVALID_HANDLE) return "";
   string text="";
   while(!FileIsEnding(h)) { text+=FileReadString(h)+"\n"; if(StringLen(text)>8388608) { FileClose(h); return ""; } }
   FileClose(h); return FxHash(text);
}
string DgRowsTip(string &rows[])
{
   string previous="GENESIS",text="";
   for(int i=0;i<ArraySize(rows);i++)
   {
      string body=IntegerToString(i+1)+"|"+previous+"|"+rows[i];
      previous=FxHash(body); text+=body+"|"+previous+"\n";
   }
   return FxHash(text);
}
bool DgNumber(string value)
{
   int dots=0,n=StringLen(value); if(n<1 || n>32) return false;
   for(int i=0;i<n;i++) { ushort c=StringGetCharacter(value,i);
      if(c==45 && i==0 && n>1) continue;
      if(c==46 && i>0 && i<n-1 && ++dots==1) continue;
      if(c<48 || c>57) return false;
   }
   double v=StringToDouble(value); return MathIsValidNumber(v) && MathAbs(v)<=100000000;
}
bool DgLedger(string &f[],SLoss &s)
{
   if(ArraySize(f)!=11 || f[0]!="disabled-work/1" || !FxInteger(f[2]) || StringLen(f[2])!=8) return false;
   for(int i=3;i<=7;i++) if(!DgNumber(f[i])) return false;
   for(int i=8;i<=10;i++) if(f[i]!="0" && f[i]!="1") return false;
   s.day=(int)StringToInteger(f[2]); s.start=StringToDouble(f[3]); s.flows=StringToDouble(f[4]);
   s.units=StringToDouble(f[5]); s.high=StringToDouble(f[6]); s.loss=StringToDouble(f[7]);
   s.paused=f[8]=="1"; s.hard=f[9]=="1"; s.owner=f[10]=="1";
   return s.start>0 && s.units>0 && s.high>0 && s.loss>=0;
}
class DgKernel
{
private:
   FxJournal journal;
   string scope,release,policy,binding;
   string packets[],receipts[];
   int acknowledged;
   SLoss ledger;
   bool loaded,has_ledger;
   bool Transition(SLoss &s)
   {
      return !has_ledger || (s.day>=ledger.day && s.high>=ledger.high &&
         (s.day!=ledger.day || (s.start==ledger.start && (!ledger.paused || s.paused))) &&
         (!ledger.hard || s.hard) && (!ledger.owner || s.owner));
   }
   string Assess(string packet,long now,int error,SLoss &next)
   {
      string f[],work,w[],v[],k[];
      if(StringSplit(packet,'\t',f)!=11 || !DgLedger(f,next) || !Transition(next) ||
         !ShUnhex(f[1],work) || !ShWork(work,scope,release,policy,w,v)) return "";
      MqlDateTime dt; if(!TimeToStruct((datetime)(now/1000),dt) ||
         next.day!=dt.year*10000+dt.mon*100+dt.day) return "";
      StringSplit(SHADOW_FIELDS,'\t',k);
      long required=(next.hard ? 1 : 0)|(next.paused ? 2 : 0)|(next.owner ? 64 : 0);
      if(((long)SV(k,v,"flags")&required)!=required || SV(k,v,"day_start")!=next.start ||
         SV(k,v,"day_loss")!=next.loss) return "";
      string receipt=ShAssess(work,scope,release,policy,now,error),r[];
      if(StringSplit(receipt,'\t',r)!=10) return "";
      // The composed preflight consumes the same bound snapshot and durable replica.
      SSet(k,v,"clock_error_ms",IntegerToString((long)MathMax(error,SV(k,v,"clock_error_ms"))));
      double volume=0,risk=0,gross=0,margin=0;
      long elapsed=now-(long)SV(k,v,"measured_at_ms");
      SSet(k,v,"expires_in_ms",IntegerToString((long)MathMin(SV(k,v,"expires_in_ms"),StringToInteger(w[8])-(long)SV(k,v,"measured_at_ms"))));
      string reason=SPreflight(k,v,next,elapsed,SV(k,v,"request_volume"),SV(k,v,"request_risk"),true,true,volume,risk,gross,margin);
      // Transport expiry/future refusals remain refusals without native risk evaluation.
      if(r[4]!="FUTURE_MESSAGE" && r[4]!="EXPIRED" && r[4]!="STALE_SNAPSHOT" &&
         (reason!=r[4] || MathAbs(volume-StringToDouble(r[7]))>0.000000001)) return "";
      return receipt;
   }
public:
   DgKernel(){ loaded=false; has_ledger=false; acknowledged=0; }
   void Close(){ journal.Close(); loaded=false; }
   string Pending(){ return acknowledged<ArraySize(receipts) ? receipts[acknowledged] : ""; }
   bool Open(string path,string account_scope,string client,string pinned_release,string pinned_policy,
             string key,bool bootstrap,string retained_tip)
   {
      Close(); ArrayResize(packets,0); ArrayResize(receipts,0); acknowledged=0; has_ledger=false;
      scope=account_scope; release=pinned_release; policy=pinned_policy;
      if(StringLen(key)<32 || StringLen(key)>64 || !FxHex(scope,64) || !FxHex(client,64) || !FxHex(release,64) || !FxHex(policy,64)) return false;
      if(bootstrap ? (FileIsExist(path) || retained_tip!="") :
         (!FxHex(retained_tip,64) || !FileIsExist(path))) return false;
      binding="DGBIND\t"+scope+"\t"+client+"\t"+release+"\t"+policy+"\t"+FxHash(ShHex(key));
      string rows[];
      if(!journal.Open(path,rows)) return false;
      if(bootstrap) { loaded=journal.Append(binding); return loaded; }
      if(ArraySize(rows)<1 || rows[0]!=binding || DgRowsTip(rows)!=retained_tip) { Close(); return false; }
      for(int i=1;i<ArraySize(rows);i++)
      {
         string f[],packet,receipt,r[];
         int n=StringSplit(rows[i],'\t',f);
         if(n==3 && f[0]=="DGRECEIPT")
         {
            if(Pending()!="" || !ShUnhex(f[1],packet) || !ShUnhex(f[2],receipt) ||
               StringSplit(receipt,'\t',r)!=10 || !FxInteger(r[5]) || !FxInteger(r[8]) ||
               StringToInteger(r[3])!=ArraySize(receipts)+1) { Close(); return false; }
            SLoss next;
            if(Assess(packet,StringToInteger(r[5]),(int)StringToInteger(r[8]),next)!=receipt) { Close(); return false; }
            int size=ArraySize(receipts); ArrayResize(receipts,size+1); ArrayResize(packets,size+1);
            receipts[size]=receipt; packets[size]=packet; ledger=next; has_ledger=true;
         }
         else if(n==2 && f[0]=="DGACK" && Pending()!="" && f[1]==FxHash(Pending())) acknowledged++;
         else { Close(); return false; }
      }
      loaded=true; return true;
   }
   bool Receive(string packet,long now,int error)
   {
      if(!loaded || Pending()!="" || ArraySize(receipts)>=1000 || StringLen(packet)>3500) return false;
      SLoss next; string receipt=Assess(packet,now,error,next),r[];
      if(StringSplit(receipt,'\t',r)!=10 || StringToInteger(r[3])!=ArraySize(receipts)+1) return false;
      for(int i=0;i<ArraySize(receipts);i++) { string old[]; StringSplit(receipts[i],'\t',old); if(old[1]==r[1]) return false; }
      if(!journal.Append("DGRECEIPT\t"+ShHex(packet)+"\t"+ShHex(receipt))) { loaded=false; return false; }
      int n=ArraySize(receipts); ArrayResize(receipts,n+1); ArrayResize(packets,n+1);
      receipts[n]=receipt; packets[n]=packet; ledger=next; has_ledger=true; return true;
   }
   bool Ack(string hash)
   {
      if(!loaded || Pending()=="" || hash!=FxHash(Pending())) return false;
      if(!journal.Append("DGACK\t"+hash)) { loaded=false; return false; }
      acknowledged++; return true;
   }
};
// Advisory management composes SProtect but never advances into a state claiming
// that an unsent repair/exit occurred. Persist actual/proposed/action before use.
string DgProtection(SProtection &actual,SProtection &proposed,long now,string boot,
                    bool storage,bool broker,bool reconciled,bool protected_ok,
                    bool closed,bool unknown,bool rejected,bool &suppressed)
{
   proposed=actual;
   string action=SProtect(proposed,now,boot,storage,broker,reconciled,protected_ok,closed,unknown,rejected);
   suppressed=action=="ATTACH_STOP_ONCE" || action=="CONTROLLED_EXIT_ONCE";
   string phase=actual.phase; actual=proposed; if(suppressed) actual.phase=phase;
   return action;
}
#endif
