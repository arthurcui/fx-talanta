#ifndef FX_SAFETY_STATE_STORE
#define FX_SAFETY_STATE_STORE
#include "Control.mqh"
#include "../gateway/Core.mqh"
// Durable local loss replica; creation is explicit and no reset method exists.
class SStateStore
{
private:
   FxJournal journal;
   SLoss state;
   string scope;
   long epoch;
   bool loaded;
public:
   SStateStore(){ loaded=false; epoch=0; }
   void Close(){ journal.Close(); loaded=false; }
   SLoss State(){ return state; }
   long Epoch(){ return epoch; }
   bool Store(const SLoss &next,long new_epoch,bool owner_resume=false)
   {
      if(!loaded || next.day<state.day || new_epoch<epoch || next.start<=0 || next.units<=0 || next.high<=0 || next.loss<0
         || !MathIsValidNumber(next.units) || !MathIsValidNumber(next.high) || !MathIsValidNumber(next.start)
         || !MathIsValidNumber(next.loss) || !MathIsValidNumber(next.flows)
         || next.high<state.high || (next.day==state.day && next.start!=state.start)
         || (state.hard && !next.hard) || (state.paused && !next.paused && next.day==state.day)
         || (state.owner && !next.owner && !owner_resume)) return false;
      string row=scope+"\t"+IntegerToString(new_epoch)+"\t"+IntegerToString(next.day)+"\t"+
         DoubleToString(next.start,16)+"\t"+DoubleToString(next.flows,16)+"\t"+DoubleToString(next.units,16)+"\t"+
         DoubleToString(next.high,16)+"\t"+DoubleToString(next.loss,16)+"\t"+
         IntegerToString((int)next.paused)+"\t"+IntegerToString((int)next.hard)+"\t"+IntegerToString((int)next.owner);
      if(!journal.Append(row)) { loaded=false; return false; }
      state=next; epoch=new_epoch; return true;
   }
   bool Open(string path,string account_scope,bool bootstrap,const SLoss &initial)
   {
      Close();
      if(!bootstrap && !FileIsExist(path)) return false;
      string rows[]; if(!journal.Open(path,rows)) return false;
      scope=account_scope; epoch=0; state=initial;
      for(int i=0;i<ArraySize(rows);i++)
      {
         string f[];
         if(StringSplit(rows[i],'\t',f)!=11 || f[0]!=scope) { Close(); return false; }
         long e=StringToInteger(f[1]); SLoss next;
         next.day=(int)StringToInteger(f[2]); next.start=StringToDouble(f[3]); next.flows=StringToDouble(f[4]);
         next.units=StringToDouble(f[5]); next.high=StringToDouble(f[6]); next.loss=StringToDouble(f[7]);
         next.paused=f[8]=="1"; next.hard=f[9]=="1"; next.owner=f[10]=="1";
         if(e<epoch || next.day<state.day || next.units<=0 || next.start<=0 || next.high<=0 || next.loss<0
            || (i>0 && (next.high<state.high || (next.day==state.day && next.start!=state.start)
                       || (state.hard && !next.hard)))) { Close(); return false; }
         state=next; epoch=e;
      }
      loaded=true;
      if(ArraySize(rows)==0)
      {
         if(!bootstrap || !Store(initial,0)) { Close(); return false; }
      }
      return true;
   }
};
#endif
